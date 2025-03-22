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
from rapidfuzz import fuzz

from .ffmpeg import AudioSegment, concat_tts_segs, convert_to_wav, get_audio_duration, get_audio_snippet
from .log import logger
from .srt import SRT, SRTEntry


logger = logger.getChild("tts")


@dataclass
class TTSWord:
    start: float  # seconds
    end: float
    text: str


@dataclass
class TTSLine:
    duration: float  # seconds
    path: str
    text: str


def find_best_matches(lines, words):
    """
    找出 lines 中每行文本在 words 列表中的最佳起始索引

    Args:
        lines: 文本行列表
        words: 短语或单词列表

    Returns:
        与 lines 等长的数组，表示每行在 words 中的起始索引
    """
    results: list[int] = []
    # 设置搜索窗口, 每轮搜索的起始位置数
    search_window = max(len(line) for line in lines) * 2

    for line in lines:
        best_start_idx = 0
        best_match_ratio = -1
        word_start_idx = 0 if not results else results[-1]  # 上一行的行首作为搜索起点
        end_idx = min(word_start_idx + search_window, len(words))

        for i in range(word_start_idx, end_idx):  # 遍历起点
            for j in range(i + 1, end_idx):  # 遍历终点
                combined = "".join(words[i:j])
                ratio = fuzz.ratio(line, combined) / 100.0
                if ratio > best_match_ratio:
                    best_match_ratio = ratio
                    best_start_idx = i

        results.append(best_start_idx)
    return results


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
        debug=False,
    ) -> list[TTSLine]:
        """
        对多行文本进行语音合成. 保存各行音频为 WAV. 返回元数据.
        """
        lines = list(lines)
        if len(lines) == 0:
            return []
        if len(lines) == 1:
            tts_words = await self._text_to_speech(lines[0], voice, output_file)
            return [TTSLine(duration=tts_words[-1].end, path=output_file, text=lines[0])]

        # 拼接所有行进行 TTS
        full_text = " ".join(lines)
        tts_words = await self._text_to_speech(full_text, voice, output_file)

        # 定位每行在 TTS 结果中的起始索引
        words = [w.text for w in tts_words]
        line_starts = find_best_matches(lines, words)

        file_path_prefix = os.path.splitext(output_file)[0]
        wav_path = file_path_prefix + ".wav"
        await convert_to_wav(output_file, wav_path)
        res = []
        for i in range(len(line_starts)):
            segment_start = tts_words[line_starts[i]].start
            duration = None
            if i < len(line_starts) - 1:
                duration = tts_words[line_starts[i + 1] - 1].end - segment_start
                if debug:
                    matched_text = " ".join(w.text for w in tts_words[line_starts[i] : line_starts[i + 1]])
                    logger.debug(f"line {i + 1}: {lines[i]} -> {matched_text}")
            elif debug:
                matched_text = " ".join(w.text for w in tts_words[line_starts[i] :])
                logger.debug(f"line {i + 1}: {lines[i]} -> {matched_text}")
            line_output = f"{file_path_prefix}_line{i + 1}.wav"
            await get_audio_snippet(wav_path, segment_start, duration, line_output)
            res.append(
                TTSLine(
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
        ) -> list[TTSLine]:
            duration = entries[-1].end - entries[0].start
            name = f"({entries[0].index}){len(entries)}_{duration:.2f}s.mp3"
            path = os.path.join(cache_dir, name)
            if os.path.exists(path):
                logger.info(f"use tts cache {name}")
                return [
                    TTSLine(
                        duration=await get_audio_duration(f"{os.path.splitext(path)[0]}_line{i + 1}.wav"),
                        path=f"{os.path.splitext(path)[0]}_line{i + 1}.wav",
                        text=srt[i].text,
                    )
                    for i in range(len(entries))
                ]
            async with limiter:
                return await self._lines_to_speech(SRT(entries).texts(), voice, path, debug)

        res = await asyncio.gather(*[_task(srt[s:e], self._limiter) for s, e in section_indexes])
        segs = self._adjust_time(res, srt)
        await concat_tts_segs(segs, output_file, cache_dir=cache_dir)
        if not debug:
            shutil.rmtree(cache_dir)

    @staticmethod
    def _adjust_time(
        tts_res: list[list[TTSLine]],
        srt: SRT,
        min_borrow=1.0,
    ) -> list[AudioSegment]:
        """
        根据 TTS 发音长度调整音频时间轴以避免加速.

        翻译算法可保证原文和译文字幕的总行数一定相等, 但无法保证其发音时长的对应. 这是因为:
        1. 二者的信息密度和语速不同. 例如, 原文可能有重复和停顿, 经过翻译及 TTS 消除了语义/语音的冗余, 从而导致 TTS 时长较短.
        2. 翻译时 LLM 输出不稳定, 可能出现行间串扰. 如某行本来是短句, 但翻译后包含了部分相邻句的内容, 从而导致 TTS 时长较长.
        当 TTS 时长过长时, 必须加速该行才能对齐原时间轴, 影响观感. 此函数尝试取长补短, 以减少加速.

        Args:
            tts_res: TTS 结果, 每个元素恰代表一行对应的音频.
            srt: 原字幕.
            min_borrow: 最小借用时长. 避免过多无意义的小调整.
        """
        min_borrow = max(min_borrow, 0.1)
        audios = [a for s in tts_res for a in s]
        # 填充时间戳, 使所有字幕行紧邻
        srt = srt.copy().fill_time()
        if len(audios) != len(srt):
            logger.warning(f"TTS 分割结果与原字幕行数不一致: {len(audios)} != {len(srt)}")

        # 标记每行的时间盈余 (字幕时长-音频时长), 为正表示可以借出
        has_time = [srt[i].end - srt[i].start - audios[i].duration for i in range(len(audios))]
        for i in range(len(audios)):
            if has_time[i] >= 0:  # 本行无需借入
                continue
            # 出于简单和稳定, 只考虑借前后两行的时间.
            # 借前一行 (提前当前行)
            if i > 0 and has_time[i - 1] > min_borrow:
                # 0.1 是一个余量, 即调整后至少尚有 0.1s 间隔
                borrow = min(-has_time[i], has_time[i - 1] - 0.1)
                has_time[i] += borrow
                has_time[i - 1] -= borrow
                srt[i].start -= borrow
                srt[i - 1].end -= borrow
            # 无须再借
            if has_time[i] >= 0:
                continue
            # 借后一行 (推后后一行)
            if i + 1 < len(audios) and has_time[i + 1] > min_borrow:
                borrow = min(-has_time[i], has_time[i + 1] - 0.1)
                has_time[i] += borrow
                has_time[i + 1] -= borrow
                srt[i].end += borrow
                srt[i + 1].start += borrow

        return [
            AudioSegment(
                a.path,
                start=srt[i].start,
                expected_dur=srt[i].end - srt[i].start,
                actual_dur=a.duration,
            )
            for i, a in enumerate(audios)
        ]
