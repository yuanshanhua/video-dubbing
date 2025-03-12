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
from .ffmpeg import SubtitleTrack, add_audio_to_video, add_subs_to_video, convert_any
from .hf_argparser import HfArgumentParser
from .log import log_to_console, log_to_file, logger
from .split import split_segments
from .srt import SRT
from .translate import LLMTranslator, translate_srt
from .tts import TTSProcessor
from .version import __version__


ArgTypes = [GeneralArgument, ASRArgument, TranslateArgument, TTSArgument, SubtitleArgument]


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

    # setup logging
    log_level = DEBUG if general_args.debug else INFO
    log_to_file(general_args.log_dir, log_level)
    log_to_console(log_level)

    # setup recording
    lock = threading.Lock()
    failed_tasks: list[tuple[str, str]] = []  # task_name, error

    # start processing
    logger.info(f"process {len(general_args.videos)} videos: {general_args.videos}")
    logger.info(f"process {len(general_args.subtitles)} subtitles: {general_args.subtitles}")
    logger.debug(f"general args: {general_args}")
    logger.debug(f"asr args: {asr_args}")
    logger.debug(f"translate args: {translate_args}")
    logger.debug(f"tts args: {tts_args}")
    if general_args.asr:
        # 由于 .asr 导入 whisperx, 而后者导入缓慢, 因此采取延迟导入, 以加快无须 asr 时的速度
        from .asr import ASRProcessor

        processor = ASRProcessor(asr_args.device, asr_args.model_dir)
    else:
        processor = cast("ASRProcessor", None)  # safe
    background_executor = AsyncBackgroundExecutor()

    translator = LLMTranslator(
        api_key=translate_args.api_key,
        base_url=translate_args.base_url,
        model=translate_args.llm_model,
        timeout=Timeout(None, connect=5.0),
        req_rate=translate_args.llm_req_rate,
    )
    tts_processor = TTSProcessor(tts_args.tts_req_rate, 10)

    def _asr(
        task_name: str,
        video: Path,
        output_sub: Path,
    ):
        import whisperx

        ts = time.time()
        audio = whisperx.load_audio(str(video))
        logger.info(f"[load] {time.time() - ts:.2f}s {task_name}")

        ts = time.time()
        tr = processor.transcribe(
            audio=audio,
            whisper_model=asr_args.model,
            batch_size=8,
            compute_type="int8",
        )
        logger.info(f"[transcribe] {time.time() - ts:.2f}s {task_name}")

        if asr_args.align:
            ts = time.time()
            tr = processor.align(
                t_result=tr,
                audio=audio,
            )
            logger.info(f"[align] {time.time() - ts:.2f}s {task_name}")

        if asr_args.diarize:
            ts = time.time()
            tr = processor.diarize(
                audio=audio,
                t_result=tr,
                hf_token=asr_args.hf_token,
            )
            logger.info(f"[diarize] {time.time() - ts:.2f}s {task_name}")

        r = tr["segments"]
        if asr_args.align:  # split_segments 必须词级时间戳
            r = split_segments(r, " ")  # type: ignore
        SRT.from_segments(r).save(output_sub)  # type: ignore

    async def _translate_and_tts(
        task_name: str,
        raw_sub: Path,
        raw_video: Path | None,
    ):
        try:
            if general_args.translate:
                adjusted_srt = raw_sub.with_suffix(".adjusted.srt")
                translated_srt = raw_sub.with_suffix(".trans.srt")
                billing_srt = raw_sub.with_suffix(".billing.srt")
                en_srt = SRT.from_file(raw_sub).correct_time()
                if translate_args.remove_ellipsis:
                    en_srt = en_srt.remove_ellipsis()
                if en_srt.sentences_percent() > 0.8:  # magic number, 后续可允许配置
                    en_srt = en_srt.merge_sentences()
                else:
                    en_srt = en_srt.merge_by_length()
                if general_args.debug:
                    en_srt.save(adjusted_srt)
                ts = time.time()
                zh_srt = await translate_srt(
                    srt=en_srt,
                    target_lang=translate_args.target_lang,
                    translator=translator,
                    try_html=2 if translate_args.use_html else 0,
                    batch_size=translate_args.batch_size,
                )
                logger.info(f"[translate] {time.time() - ts:.2f}s {task_name}")
                zh_srt.save(translated_srt)
                en_srt.concat_text(zh_srt).save(billing_srt)
            else:
                translated_srt = raw_sub
                billing_srt = None
            if general_args.tts:
                tts_audio = raw_sub.with_suffix("." + tts_args.audio_format)
                tts_srt = raw_sub.with_suffix(".tts.srt")
                srt = SRT.from_file(translated_srt).correct_time()
                if srt.sentences_percent() > 0.8:
                    srt = srt.merge_sentences(min_length=0)
                else:
                    srt = srt.merge_by_length()
                if general_args.debug:
                    srt.save(tts_srt)
                tmp_dir = random.Random(raw_sub.as_posix()).randint(0, 1000000)
                ts = time.time()
                await tts_processor.srt_tts(
                    srt=srt,
                    voice=tts_args.voice,
                    max_length=1000,
                    output_file=tts_audio,
                    cache_dir=f".cache/{tmp_dir}",
                    debug=general_args.debug,
                )
                logger.info(f"[tts] {time.time() - ts:.2f}s {task_name}")
                if raw_video and tts_args.add_track:
                    tts_video = raw_sub.with_suffix(".tts.mp4")
                    await add_audio_to_video(tts_audio, raw_video, tts_video, tts_args.track_title)
                    raw_video = tts_video
                    if not general_args.debug:
                        logger.info(f"remove: {tts_audio}")
                        os.remove(tts_audio)
            if raw_video is None:
                return
            # add subtitles to video
            subs: list[SubtitleTrack] = []
            if sub_args.add_asr_sub:
                subs.append(SubtitleTrack(raw_sub, sub_args.asr_sub_title, sub_args.asr_sub_style))
            if sub_args.add_trans_sub and general_args.translate:
                subs.append(SubtitleTrack(translated_srt, sub_args.trans_sub_title, sub_args.trans_sub_style))
            if sub_args.add_bilingual_sub and billing_srt:
                subs.append(SubtitleTrack(billing_srt, sub_args.bilingual_sub_title, sub_args.bilingual_sub_style))
            for sub in subs:
                ass_p = sub.file.with_suffix(".ass")
                await convert_any(sub.file, ass_p)
                ass = ASS.from_file(ass_p)
                ass.add_or_update_style(sub.style if sub.style else Style.get_default_kv_string())
                ass.save(ass_p)
                # clean srt
                if not general_args.debug and sub.file not in general_args.subtitles:  # 避免删除输入文件
                    logger.info(f"remove: {sub.file}")
                    sub.file.unlink(missing_ok=True)
                sub.file = ass_p
            await add_subs_to_video(raw_video, subs, raw_sub.with_suffix(".sub.mkv"))
            if general_args.debug:
                return
            # clean ass
            for sub in subs:
                logger.info(f"remove: {sub.file}")
                sub.file.unlink(missing_ok=True)
            # clean video
            if raw_video not in general_args.videos:
                logger.info(f"remove: {raw_video}")
                raw_video.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Translate & TTS {task_name} failed: {e}")
            with lock:
                failed_tasks.append(("translate & tts: " + task_name, str(e)))

    for i in range(max(len(general_args.videos), len(general_args.subtitles))):
        task_file = general_args.videos[i] if general_args.videos else general_args.subtitles[i]
        task_name = task_file.stem
        logger.info(f"processing task {i}: {task_name}")
        video = general_args.videos[i] if general_args.videos else None
        output_dir = Path(general_args.output_dir) if general_args.output_dir else task_file.parent
        if general_args.asr:
            asr_sub = output_dir / f"{task_name}.asr.srt"
        else:
            asr_sub = general_args.subtitles[i]
        try:
            if general_args.asr:
                assert video is not None
                _asr(task_name, video, asr_sub)
            if general_args.translate or general_args.tts:
                background_executor.execute(_translate_and_tts(task_name, asr_sub, video))
        except Exception as e:
            logger.error(f"ASR task {i} ({task_name}) failed: {e}")
            with lock:
                failed_tasks.append(("asr: " + task_name, str(e)))

    background_executor.wait_all()
    logger.info("all tasks done")
    if failed_tasks:
        logger.error("failed tasks:")
        for task_name, error in failed_tasks:
            logger.error(f"{task_name}: {error}")
