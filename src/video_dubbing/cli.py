import json
import os
import random
import threading
import time
from argparse import ArgumentParser
from dataclasses import asdict
from logging import DEBUG, INFO
from pathlib import Path
from typing import cast

import yaml
from httpx import Timeout

from .args import USAGE, ASRArgument, GeneralArgument, SubtitleArgument, TranslateArgument, TTSArgument
from .ass import ASS, Style
from .executor import AsyncBackgroundExecutor
from .ffmpeg import SubtitleTrack, add_audio_to_video, add_hard_sub, add_soft_subs, convert_any
from .hf_argparser import HfArgumentParser
from .log import get_llm_msg_logger, log_to_console, log_to_file, logger
from .split import split_segments
from .srt import SRT
from .translate import LLMTranslator, translate_srt
from .tts import TTSProcessor
from .version import __version__


ArgTypes = [GeneralArgument, ASRArgument, TranslateArgument, TTSArgument, SubtitleArgument]


class VideoDubbing:
    def __init__(
        self,
        general_args: GeneralArgument,
        asr_args: ASRArgument,
        translate_args: TranslateArgument,
        tts_args: TTSArgument,
        sub_args: SubtitleArgument,
    ):
        self.general_args = general_args
        self.asr_args = asr_args
        self.translate_args = translate_args
        self.tts_args = tts_args
        self.sub_args = sub_args

        # 设置日志
        log_level = DEBUG if general_args.debug else INFO
        log_to_file(general_args.log_dir, log_level)
        log_to_console(log_level)
        self.llm_msg_logger = None
        if general_args.debug and general_args.log_dir:
            self.llm_msg_logger = get_llm_msg_logger(general_args.log_dir, "llm.msg")

        # 初始化失败任务记录
        self.lock = threading.Lock()
        self.failed_tasks: list[tuple[str, str]] = []  # task_name, error

        # 初始化各模块
        self.background_executor = AsyncBackgroundExecutor()
        self.asr_processor = cast("ASRProcessor", None)  # safe
        if general_args.asr:
            # 延迟导入 whisperx
            from .asr import ASRProcessor

            self.asr_processor = ASRProcessor(asr_args.device, asr_args.model_dir)
        self.translator = LLMTranslator(
            api_key=translate_args.api_key,
            base_url=translate_args.base_url,
            model=translate_args.llm_model,
            timeout=Timeout(None, connect=5.0),
            req_rate=translate_args.llm_req_rate,
            llm_msg_logger=self.llm_msg_logger,
        )
        self.tts_processor = TTSProcessor(tts_args.tts_req_rate, 10)

    def run(self) -> None:
        t_start = time.time()

        logger.info(f"process {len(self.general_args.videos)} videos: {list(map(str, self.general_args.videos))}")
        logger.info(
            f"process {len(self.general_args.subtitles)} subtitles: {list(map(str, self.general_args.subtitles))}"
        )
        logger.debug(f"general args: {self.general_args}")
        logger.debug(f"asr args: {self.asr_args}")
        logger.debug(f"translate args: {self.translate_args}")
        logger.debug(f"tts args: {self.tts_args}")

        for i in range(max(len(self.general_args.videos), len(self.general_args.subtitles))):
            self._process_one_file(i)

        self.background_executor.wait_all()
        logger.info(f"process all files in {time.time() - t_start:.2f}s")

        if self.failed_tasks:
            logger.error("failed tasks:")
            for task_name, error in self.failed_tasks:
                logger.error(f"{task_name}: {error}")

    def _process_one_file(self, index: int) -> None:
        task_file = self.general_args.videos[index] if self.general_args.videos else self.general_args.subtitles[index]
        task_name = task_file.stem
        logger.info(f"processing task {index}: {task_name}")

        video = self.general_args.videos[index] if self.general_args.videos else None
        output_dir = Path(self.general_args.output_dir) if self.general_args.output_dir else task_file.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.general_args.asr:
            asr_sub = output_dir / f"{task_name}.asr.srt"
        else:
            asr_sub = self.general_args.subtitles[index]

        try:
            if self.general_args.asr:
                assert video is not None  # never failed
                self._run_asr(task_name, video, asr_sub)
        except Exception as e:
            logger.error(f"ASR task {index} ({task_name}) failed: {e}", exc_info=True)
            with self.lock:
                self.failed_tasks.append(("asr: " + task_name, str(e)))

        if self.general_args.translate or self.general_args.tts:
            self.background_executor.execute(self._run_translate_and_tts(task_name, asr_sub, video, output_dir))

    def _run_asr(self, task_name: str, video: Path, output_sub: Path) -> None:
        import whisperx

        ts = time.time()
        audio = whisperx.load_audio(str(video))
        logger.info(f"[load] in {time.time() - ts:.2f}s: <{task_name}>")

        ts = time.time()
        tr = self.asr_processor.transcribe(
            audio=audio,
            whisper_model=self.asr_args.model,
            batch_size=8,
            compute_type="int8",
        )
        logger.info(f"[transcribe] in {time.time() - ts:.2f}s: <{task_name}>")

        if self.asr_args.align:
            ts = time.time()
            tr = self.asr_processor.align(
                t_result=tr,
                audio=audio,
            )
            logger.info(f"[align] in {time.time() - ts:.2f}s: <{task_name}>")

        if self.asr_args.diarize:
            ts = time.time()
            tr = self.asr_processor.diarize(
                audio=audio,
                t_result=tr,
                hf_token=self.asr_args.hf_token,
            )
            logger.info(f"[diarize] in {time.time() - ts:.2f}s: <{task_name}>")

        r = tr["segments"]
        if self.asr_args.align:  # split_segments 必须词级时间戳
            r = split_segments(r, " ")  # type: ignore
        SRT.from_segments(r).save(output_sub)  # type: ignore

    async def _run_translate_and_tts(
        self,
        task_name: str,
        raw_sub: Path,
        raw_video: Path | None,
        output_dir: Path | None,
    ) -> None:
        # 基准输出文件名. 非实际文件
        output_file = output_dir / f"{task_name}" if output_dir else raw_sub
        # 用于添加字幕的视频文件. 取决于是否执行 TTS, 可能是原视频或添加音轨后的视频
        add_sub_input_video = raw_video
        try:
            # 翻译
            translated_srt, billing_srt = await self._translation(task_name, raw_sub, output_file)
            # TTS
            add_sub_input_video = await self._tts(task_name, translated_srt, raw_video, output_file)
            if add_sub_input_video is None:
                return
            # 添加字幕
            subs = await self._add_subs(raw_sub, output_file, add_sub_input_video, translated_srt, billing_srt)
            # 清理临时文件
            if not self.general_args.debug:
                self._cleanup_files(subs, raw_video, add_sub_input_video)
        except Exception as e:
            logger.error(f"Translate & TTS {task_name} failed: {e}", exc_info=True)
            with self.lock:
                self.failed_tasks.append(("translate & tts: " + task_name, str(e)))

    async def _translation(
        self,
        task_name: str,
        raw_sub: Path,
        output_file: Path,
    ) -> tuple[Path, Path | None]:
        """返回翻译所得字幕和双语字幕"""
        if not self.general_args.translate:
            return raw_sub, None

        adjusted_srt = output_file.with_suffix(".adjusted.srt")
        translated_srt = output_file.with_suffix(".trans.srt")
        billing_srt = output_file.with_suffix(".billing.srt")

        en_srt = SRT.from_file(raw_sub).correct_time()
        if self.translate_args.remove_ellipsis:
            en_srt = en_srt.remove_ellipsis()

        if en_srt.sentences_percent() > 0.8:  # magic number, 后续可允许配置
            en_srt = en_srt.merge_sentences()
        else:
            en_srt = en_srt.merge_by_length()

        if self.general_args.debug:
            en_srt.save(adjusted_srt)

        ts = time.time()
        zh_srt = await translate_srt(
            srt=en_srt,
            target_lang=self.translate_args.target_lang,
            translator=self.translator,
            try_html=2 if self.translate_args.use_html else 0,
            batch_size=self.translate_args.batch_size,
        )
        logger.info(f"[translate] in {time.time() - ts:.2f}s: <{task_name}>")

        # 调整字幕长度以适合显示
        zh_srt = zh_srt.split_by_length(25, 10).save(translated_srt)  # 适用于中文, 英文约*2 TODO 允许配置
        en_srt = en_srt.split_with_ref(zh_srt)
        # 组装双语字幕
        if self.sub_args.trans_first:
            zh_srt.concat_text(en_srt, "\n<newstyle>").save(billing_srt)
        else:
            en_srt.concat_text(zh_srt, "\n<newstyle>").save(billing_srt)

        return translated_srt, billing_srt

    async def _tts(
        self,
        task_name: str,
        translated_srt: Path,
        raw_video: Path | None,
        output_file: Path,
    ) -> Path | None:
        """处理 TTS, 返回更新后的视频文件路径"""
        if not self.general_args.tts:
            return raw_video

        tts_audio = output_file.with_suffix("." + self.tts_args.audio_format)
        tts_srt = output_file.with_suffix(".tts.srt")

        srt = SRT.from_file(translated_srt).correct_time()
        if srt.sentences_percent() > 0.8:
            srt = srt.merge_sentences(min_length=0)
        else:
            srt = srt.merge_by_length()

        if self.general_args.debug:
            srt.save(tts_srt)

        tmp_dir = random.Random(translated_srt.as_posix()).randint(0, 1000000)
        ts = time.time()

        await self.tts_processor.srt_tts(
            srt=srt,
            voice=self.tts_args.voice,
            max_length=1000,
            output_file=tts_audio,
            cache_dir=f".cache/{tmp_dir}",
            debug=self.general_args.debug,
        )
        logger.info(f"[tts] in {time.time() - ts:.2f}s: <{task_name}>")

        if raw_video and self.tts_args.add_track:
            tts_video = output_file.with_suffix(".tts.mp4")
            await add_audio_to_video(tts_audio, raw_video, tts_video, self.tts_args.track_title)
            if not self.general_args.debug:
                logger.info(f"remove: {tts_audio}")
                os.remove(tts_audio)
            return tts_video
        return raw_video

    async def _add_subs(
        self,
        raw_sub: Path,
        output_file: Path,
        video: Path,
        translated_srt: Path,
        billing_srt: Path | None,
    ) -> list[SubtitleTrack]:
        """添加字幕到视频，返回添加的字幕轨道列表"""
        subs: list[SubtitleTrack] = []
        # 添加原/译文字幕
        if self.sub_args.soft and self.sub_args.add_asr_sub:
            subs.append(SubtitleTrack(raw_sub, self.sub_args.asr_sub_title, self.sub_args.asr_sub_style))

        if self.sub_args.soft and self.sub_args.add_trans_sub and self.general_args.translate:
            subs.append(SubtitleTrack(translated_srt, self.sub_args.trans_sub_title, self.sub_args.trans_sub_style))

        for sub in subs:
            ass_p = sub.file.with_suffix(".ass")
            await convert_any(sub.file, ass_p)
            ass = ASS.from_file(ass_p)
            ass.add_or_update_style(sub.style if sub.style else Style.get_default_kv_string())
            ass.save(ass_p)
            # 清理 srt
            if not self.general_args.debug and sub.file not in self.general_args.subtitles:  # 避免删除输入文件
                logger.info(f"remove: {sub.file}")
                sub.file.unlink(missing_ok=True)
            sub.file = ass_p

        # 应用双语字幕样式
        if (not self.sub_args.soft or self.sub_args.add_bilingual_sub) and billing_srt:
            ass_p = billing_srt.with_suffix(".ass")
            await convert_any(billing_srt, ass_p)
            billing_srt.unlink(missing_ok=True)
            ass = ASS.from_file(ass_p)
            raw_style = self.sub_args.asr_sub_style or Style.get_default_kv_string()
            trans_style = self.sub_args.trans_sub_style or Style.get_default_kv_string()
            first_style, second_style = (
                (trans_style, raw_style) if self.sub_args.trans_first else (raw_style, trans_style)
            )
            ass.add_or_update_style(first_style)
            ass.add_or_update_style(second_style, "second")
            ass.apply_style("second", "<newstyle>").save(ass_p)
            subs.append(SubtitleTrack(ass_p, self.sub_args.bilingual_sub_title))

        if self.sub_args.soft:
            await add_soft_subs(video, subs, output_file.with_suffix(".sub.mkv"))
        elif subs:
            await add_hard_sub(video, subs[0].file, output_file.with_suffix(".sub.mkv"))
        return subs

    def _cleanup_files(self, subs: list[SubtitleTrack], raw_video: Path | None, add_sub_input_video: Path) -> None:
        """清理临时文件"""
        # 清理 ass
        for sub in subs:
            logger.info(f"remove: {sub.file}")
            sub.file.unlink(missing_ok=True)

        # 清理视频
        if raw_video and add_sub_input_video != raw_video:  # 实际上此处 raw_video 一定非 None
            logger.info(f"remove: {raw_video}")
            add_sub_input_video.unlink(missing_ok=True)


def cli():
    # 支持配置文件和命令行参数, 且后者优先级更高:
    # 1. 使用 parser0 解析命令行参数, 它只能解析 --config 参数, 其他参数保留在 remaining 中
    # 2. 如果 --config 参数存在, 则加载配置文件到 file_args
    # 3. 将 file_args 设为 parser 的默认参数, 然后用 parser 解析 remaining
    parser0 = ArgumentParser(add_help=False)
    parser0.add_argument("-c", "--config", type=str, default=None, help="加载 JSON 或 YAML 格式的配置文件")
    cli_args, remaining = parser0.parse_known_args()

    parser = HfArgumentParser(ArgTypes, usage=USAGE)
    parser.add_argument("-c", "--config", type=str, default=None, help="加载 JSON 或 YAML 格式的配置文件")  # for help
    parser.add_argument("-gc", "--gen-config", action="store_true", help="生成默认配置文件")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    # load config file
    config = cli_args.config
    if config:
        config_file = Path(config)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        if config_file.suffix == ".yaml":
            file_args = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        elif config_file.suffix == ".json":
            file_args = json.loads(config_file.read_text(encoding="utf-8"))
        else:
            raise ValueError(f"Unsupported config file format: {config_file}")
        parser.set_defaults(**file_args)

    args = parser.parse_args(remaining).__dict__
    args.pop("config")

    # generate default config file
    gen_config = args.pop("gen_config")
    if gen_config:
        default_args = {}
        for d in ArgTypes:
            default_args.update(asdict(d()))
        j = Path("config.json")
        if not j.is_file():
            j.write_text(json.dumps(default_args, ensure_ascii=False, indent=4), encoding="utf-8")
            print("Write default config to config.json")
        else:
            print("config.json already exists")
        exit(0)

    # parse arguments
    general_args, asr_args, translate_args, tts_args, sub_args = parser.parse_dict(args)
    general_args = cast(GeneralArgument, general_args)
    asr_args = cast(ASRArgument, asr_args)
    translate_args = cast(TranslateArgument, translate_args)
    tts_args = cast(TTSArgument, tts_args)
    sub_args = cast(SubtitleArgument, sub_args)

    app = VideoDubbing(general_args, asr_args, translate_args, tts_args, sub_args)
    app.run()
