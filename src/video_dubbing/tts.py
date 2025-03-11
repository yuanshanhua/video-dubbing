import asyncio
import html
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, no_type_check

from aiolimiter import AsyncLimiter
from edge_tts import Communicate

from .ffmpeg import (
    AudioSegment,
    concat_tts_segs,
    convert_to_wav,
    get_audio_duration,
    get_audio_snippet,
)
from .log import logger
from .srt import SRT, SRTEntry


logger = logger.getChild("tts")


@dataclass
class TTSWord:
    start: float  # seconds
    end: float
    text: str


@dataclass
class TTSAudio:
    duration: float  # seconds
    path: str
    text: str


class TTSProcessor:
    def __init__(self, max_rate: float = 3, time_period: float = 10):
        self._max_rate = max_rate
        self._time_period = time_period
        self._limiter = AsyncLimiter(max_rate, time_period)

    @no_type_check
    @staticmethod
    async def _tts(text, voice, output_file: str) -> list[TTSWord]:
        """
        在保存 tts 结果的同时获取元数据, 以便进一步处理.
        """
        c = Communicate(text, voice)
        entries = []
        with open(output_file, "wb") as f:
            async for chunk in c.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    entries.append(
                        TTSWord(
                            start=chunk["offset"] / 10000000.0,
                            end=(chunk["offset"] + chunk["duration"]) / 10000000.0,
                            text=html.unescape(chunk["text"]),  # 转义 &gt; 等
                        )
                    )
        return entries

    async def _text_to_speech(
        self,
        text: str,
        voice: str,
        output_file: str,
    ) -> list[TTSWord]:
        """
        调用 edge_tts 进行语音合成.

        API 返回的元数据事实上为我们提供了 text 的词(句)级时间戳信息, 据此可以进行进一步拆分.
        """
        logger.debug(f"call edge-tts len={len(text)} voice={voice} output={output_file}")
        count = 1
        while True:
            try:
                # 参考 https://learn.microsoft.com/zh-cn/azure/ai-services/speech-service/rest-text-to-speech?tabs=streaming#audio-outputs
                # edge_tts 请求的格式是 audio-24khz-48kbitrate-mono-mp3
                entries = await self._tts(text, voice, output_file)
                break
            except Exception as e:
                logger.warning(f"edge-tts failed: {e}")
                os.remove(output_file)  # 删除错误的文件, 使缓存总是可用
                logger.warning(f"remove {output_file}")
                logger.warning(f"wait and retry in {count}s")
                time.sleep(count)
                count *= 2
        logger.debug(f"save tts res to {output_file}")
        return entries

    async def _lines_to_speech(
        self,
        lines: Iterable[str],
        voice: str,
        output_file: str,
    ) -> list[TTSAudio]:
        """
        对多行文本进行语音合成. 保存各行音频为 WAV. 返回元数据.
        """
        lines = list(lines)
        if len(lines) == 0:
            return []
        if len(lines) == 1:
            entries = await self._text_to_speech(lines[0], voice, output_file)
            return [TTSAudio(duration=entries[-1].end, path=output_file, text=lines[0])]

        # 拼接所有行进行 TTS
        full_text = "\n".join(lines)
        entries = await self._text_to_speech(full_text, voice, output_file)

        # 进行行匹配
        word_index = 0
        # line_starts 记录原字幕中每行对应的首个 TTSWord 在 entries 中的索引.
        # 第 i 行即对应 entries[line_starts[i]:line_starts[i+1]] 这些 TTSWord.
        line_starts = [0]
        for line in lines:
            # tts 返回的元数据总是包含原文中所有会发音的字符, 即可以认为是原文的离散子串.
            # 因此, 第 i 个 TTSWord 一定有与之对应的第 i+invalid 个字符,
            # 其中 invalid >= 0 表示此前的不发音字符数. 我们只需要逐步增大 invalid 直到找到匹配.
            invalid = 0
            while invalid < len(line) and word_index < len(entries):
                word = entries[word_index]
                r = line.find(word.text, invalid)
                if r == -1:
                    # 当 word 与原文无法匹配时, 认为本行匹配已完成.
                    break
                    # 有一种意料之外的情况, 即此 word 确实不是原文的子串,
                    # 在这种情况下, 必须跳过此 word, 否则会导致后续的匹配错误.
                    # 这一现象目前尚未观测到, 但考虑到 edge_tts API 并未做出保证, 因此保留此处.
                    if word.text not in full_text:
                        word_index += 1
                        # 此 TTSWord 尽管不匹配, 但必然与原文至少一个字符对应, 因此增加 invalid 总是安全的.
                        invalid += 1
                else:
                    word_index += 1
                    invalid += r - invalid + 1
            # 此时 word_index 指向下一行对应的首个 TTSWord.
            if word_index < len(entries):
                line_starts.append(word_index)
            continue

        file_path_prefix = os.path.splitext(output_file)[0]
        wav_path = file_path_prefix + ".wav"
        await convert_to_wav(output_file, wav_path)
        res = []
        for i in range(len(line_starts)):
            segment_start = entries[line_starts[i]].start
            duration = None
            if i < len(line_starts) - 1:
                duration = entries[line_starts[i + 1] - 1].end - segment_start
            line_output = f"{file_path_prefix}_line{i + 1}.wav"
            await get_audio_snippet(wav_path, segment_start, duration, line_output)
            res.append(
                TTSAudio(
                    duration=await get_audio_duration(line_output),
                    path=line_output,
                    text=lines[i],
                )
            )
        return res

    async def srt_tts(
        self,
        *,
        srt: SRT,
        max_length: int,
        voice: str,
        output_file: Path,
        cache_dir: str,
        debug: bool,
    ):
        """
        对 srt 字幕进行语音合成.

        Args:
            srt: 待合成的字幕.
            max_length: 每段 tts 请求的最大长度.
            voice: edge_tts 支持的语音角色.
            output_file: 最终输出音频文件路径.
            cache_dir: 存放临时音频文件的目录.
            max_concurrent: 请求 edge_tts 的最大并发数.
        """
        logger.info(f"length={len(srt)}, max_length={max_length}")
        os.makedirs(cache_dir, exist_ok=True)
        section_indexes: list[tuple[int, int]] = []
        start = 0
        length = 0
        for i, e in enumerate(srt):
            if length + len(e) > max_length:
                section_indexes.append((start, i))
                logger.debug(f"section {len(section_indexes)}: {start} - {i}")
                start = i
                length = len(e)
            else:
                length += len(e)
        section_indexes.append((start, len(srt)))
        logger.debug(f"section {len(section_indexes)}: {start} - {len(srt)}")
        logger.info(f"convert to {len(section_indexes)} sections for tts")

        async def _task(
            entries: list[SRTEntry],
            limiter: AsyncLimiter,
        ) -> list[TTSAudio]:
            duration = entries[-1].end - entries[0].start
            name = f"({entries[0].index}){len(entries)}_{duration:.2f}s.mp3"
            path = os.path.join(cache_dir, name)
            if os.path.exists(path):
                logger.info(f"use tts cache {name}")
                return [
                    TTSAudio(
                        duration=await get_audio_duration(f"{os.path.splitext(path)[0]}_line{i + 1}.wav"),
                        path=f"{os.path.splitext(path)[0]}_line{i + 1}.wav",
                        text=srt[i].text,
                    )
                    for i in range(len(entries))
                ]
            async with limiter:
                return await self._lines_to_speech(SRT(entries).texts(), voice, path)

        res = await asyncio.gather(*[_task(srt[s:e], self._limiter) for s, e in section_indexes])
        segs = self._build_segments(res, srt)
        await concat_tts_segs(segs, output_file, cache_dir=cache_dir)
        if not debug:
            shutil.rmtree(cache_dir)

    @staticmethod
    def _build_segments(
        tts_res: list[list[TTSAudio]],
        srt: SRT,
        borrow_interval=0.5,
        min_borrow=1.0,
    ) -> list[AudioSegment]:
        """
        根据 TTS 信息调整时间轴使时长均匀.

        例如, 由于翻译时 LLM 输出不稳定, 可能出现行间串扰, 导致某些持续时间很短的行却对应了较长的文本, 或者反之.
        此函数尝试找到并纠正这种情况, 以避免后续音频合成中出现极端的加速或减速.

        Args:
            tts_res: TTS 结果, 每个元素恰代表一行对应的音频.
            srt: 原字幕.
            borrow_interval: 间隔小于此长度的行之间可调整.
            min_borrow: 最小借用时长. 避免过多无意义的小调整.
        """
        min_borrow = max(min_borrow, 0.1)
        audios = [a for s in tts_res for a in s]
        srt = srt.copy()
        if len(audios) != len(srt):
            logger.warning(f"TTS 分割结果与原字幕行数不一致: {len(audios)} != {len(srt)}")

        # 标记每行的时间盈余情况, 为正可以借出
        has_time = [srt[i].end - srt[i].start - audios[i].duration for i in range(len(audios))]
        for i in range(len(audios)):
            if has_time[i] >= 0:
                continue
            # 出于简单和稳定, 我们现在只考虑借前后两行的时间
            # 借前一行
            if i > 0 and has_time[i - 1] > min_borrow and srt[i].start - srt[i - 1].end < borrow_interval:
                # 0.1 是一个余量, 避免借出后时长太极限
                borrow = min(-has_time[i], has_time[i - 1] - 0.1)
                has_time[i] += borrow
                has_time[i - 1] -= borrow
                srt[i].start -= borrow
                srt[i - 1].end -= borrow
            # 无须再借
            if has_time[i] >= 0:
                continue
            # 借后一行
            if (
                i + 1 < len(audios)
                and has_time[i + 1] > min_borrow
                and srt[i + 1].start - srt[i].end < borrow_interval
            ):
                borrow = min(-has_time[i], has_time[i + 1] - 0.1)
                has_time[i] += borrow
                has_time[i + 1] -= borrow
                srt[i].end += borrow
                srt[i + 1].start += borrow

        srt = srt.fill_time()
        return [
            AudioSegment(
                a.path,
                start=srt[i].start,
                expected_dur=srt[i].end - srt[i].start,
                actual_dur=a.duration,
            )
            for i, a in enumerate(audios)
        ]
