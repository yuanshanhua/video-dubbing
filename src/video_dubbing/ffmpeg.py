import asyncio
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .log import logger


logger = logger.getChild("ffmpeg")


@dataclass
class AudioSegment:
    file: str  # 音频文件路径
    start: float  # 在最终结果中的起始时间
    expected_dur: float  # 在最终结果中的期望时长
    actual_dur: float  # 实际时长


@dataclass
class SubtitleTrack:
    file: Path
    title: str | None = None
    style: str | None = None


async def _run_command(command: list[str], task_name: str) -> tuple[bool, bytes, bytes]:
    """
    执行命令，并处理输出和错误
    """
    logger.debug(f"{task_name}: {command[0]} " + " ".join(f'"{c}"' for c in command[1:]) if len(command) > 1 else "")
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    success = process.returncode == 0
    if not success:
        logger.error(f"{task_name} failed: {stderr.decode()}")
    return success, stdout, stderr


async def concat_tts_segs(
    inputs: Iterable[AudioSegment],
    output_file: Path,
    *,
    cache_dir: str,
):
    """
    按预期时间轴合并 TTS 结果.
    """
    logger.info(f"output: {output_file}")
    file_list = ""
    t = 0.0
    for seg in inputs:
        name = os.path.basename(seg.file)
        path = os.path.abspath(seg.file)
        if seg.start > t:  # 上个片段结束与当前片段开始有间隔
            s_dur = seg.start - t
            s_dur = math.floor(s_dur * 100) / 100
            s_file = f"{cache_dir}/silence_{s_dur}.wav"
            await _create_silence_wav(s_dur, s_file)
            logger.debug(f"insert silence: {s_file}, {s_dur}s")
            file_list += f"file 'silence_{s_dur}.wav'\n"
        t = seg.start
        d = seg.actual_dur
        if d > seg.expected_dur:  # 实际时长大于指定时长, 加速
            speed = math.ceil(100 * d / seg.expected_dur) / 100.0
            if speed > 1.5:
                logger.warning(f"异常加速: {name} ({speed}x, 原始时长:{d:.3f}s, 目标时长:{seg.expected_dur:.3f}s)")
            speed_output = f"{cache_dir}/{name}.{speed}x.wav"
            await _change_speed(seg.file, speed_output, speed)
            d = await get_audio_duration(speed_output)
            logger.debug(f"add file: {name}.{speed}x.wav, {d}s, {speed}x")
            file_list += f"file '{name}.{speed}x.wav'\n"
        else:
            logger.debug(f"add file: {path}, {d}s")
            file_list += f"file '{path}'\n"
        t += d  # 实际将添加的片段时长

    with open(f"{cache_dir}/concat_list.txt", "w") as f:
        logger.debug(f"write concat list to {cache_dir}/concat_list.txt")
        f.write(file_list)

    command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        f"{cache_dir}/concat_list.txt",
        "-y",
        # "-v",
        # "warning",
        str(output_file),
    ]
    await _run_command(command, "concat audios")


async def get_audio_snippet(
    input_file: str,
    start: float,
    duration: Optional[float],
    output_file: str,
):
    """
    从音频文件中提取指定时间段的音频.
    """
    logger.debug(f"{input_file} (ss={start}s, dur={duration}s) -> {output_file}")
    if duration is not None and duration <= 0:
        logger.warning(f"duration={duration} < 0")
        duration = 0.01  # 仍创建 output
    command = [
        "ffmpeg",
        "-ss",
        str(start),
        *(
            [
                "-t",
                str(duration),
            ]
            if duration
            else []
        ),
        "-accurate_seek",
        "-i",
        input_file,
        "-y",
        "-c",
        "copy",
        "-v",
        "warning",
        output_file,
    ]
    await _run_command(command, "get audio snippet")


async def convert_to_wav(
    input_file: str,
    output_file: str,
    sample_rate: int = 24000,
    channels: int = 1,
):
    """
    将音频文件转换为 pcm_s16le 编码 wav 文件.
    """
    logger.debug(f"{input_file} -> {output_file}")
    command = [
        "ffmpeg",
        "-i",
        input_file,
        "-c:a",
        "pcm_s16le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-y",
        "-v",
        "warning",
        output_file,
    ]
    await _run_command(command, "convert to wav")


async def add_audio_to_video(
    audio_file: Path,
    video_file: Path,
    output_file: Path,
    title: str | None = None,
):
    """
    将音频文件添加到视频文件中.
    """
    logger.info(f"{audio_file} + {video_file} -> {output_file}")
    command = [
        "ffmpeg",
        "-i",
        str(video_file),
        "-i",
        str(audio_file),
        "-map",
        "0",
        "-map",
        "-0:a",
        "-map",
        "1:a",
        "-map",
        "0:a",
        *(
            [
                "-metadata:s:a:0",
                f"title={title}",
            ]
            if title
            else []
        ),
        "-c",
        "copy",
        "-y",
        "-v",
        "warning",
        str(output_file),
    ]
    await _run_command(command, "add audio to video")


async def get_audio_duration(file: str | Path) -> float:
    """
    获取音频文件的时长, 单位为秒.
    """
    logger.debug(f"{file}")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file),
    ]
    success, stdout, _ = await _run_command(command, "get duration")
    if not success:
        return 0.0
    return float(stdout.decode().strip())


async def add_subs_to_video(
    video: Path,
    subs: list[SubtitleTrack],
    output: Path,
    soft: bool = True,
):
    """
    将字幕添加到视频.

    此方法会移除视频中原有的字幕和其他数据, 仅保留音视频流.
    Args:
        soft: 使用软字幕模式, 无须重编码. 此模式须输出为 MKV 格式.
    """
    logger.info(f"({', '.join([str(s.file) for s in subs])}) + {video} -> {output}")
    srt_inputs: list[str] = []
    metadatas: list[str] = []
    maps: list[str] = []
    for i, sub in enumerate(subs):
        srt_inputs.extend(["-i", str(sub.file)])
        if sub.title:
            metadatas.extend([f"-metadata:s:s:{i}", f"title={sub.title}"])
        maps.extend(["-map", f"{i + 1}"])
    command = [
        "ffmpeg",
        "-i",
        str(video),
        *srt_inputs,
        *metadatas,
        "-map",
        "0:v",
        "-map",
        "0:a",
        *maps,
        "-c",
        "copy",
        "-y",
        "-v",
        "warning",
        str(output),
    ]
    await _run_command(command, "add subtitles to video")


async def convert_any(
    input: Path,
    output: Path,
):
    """
    使用 FFmpeg 默认配置转换任意文件.

    相当于 ffmpeg -i {input} {output}
    """
    if input == output:
        return
    logger.info(f"{input} -> {output}")
    command = [
        "ffmpeg",
        "-i",
        str(input),
        "-y",
        "-v",
        "warning",
        str(output),
    ]
    await _run_command(command, "convert any")


async def _get_audio_info(file: str | Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=sample_rate,channels",
        "-of",
        "json",
        str(file),
    ]
    success, stdout, _ = await _run_command(command, "get audio info error")
    if not success:  # 如果有错误输出
        return {"sample_rate": -1, "channels": -1}
    import json

    info = json.loads(stdout.decode())
    stream = info["streams"][0]
    return {
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
    }


async def _change_speed(input_file: str | Path, output_file: str | Path, speed: float):
    """
    将指定音频文件加/减速. 输出为 pcm_s16le 编码 wav 文件.
    """
    logger.debug(f"{input_file}, {speed}x -> {output_file}")
    if speed > 2.0:
        filter_str = []
        while speed > 2.0:
            filter_str.append("atempo=2.0")
            speed /= 2.0
        filter_str.append(f"atempo={speed}")
        filter_str = ",".join(filter_str)
    elif speed < 0.5:
        filter_str = []
        while speed < 0.5:
            filter_str.append("atempo=0.5")
            speed /= 0.5
        filter_str.append(f"atempo={speed}")
        filter_str = ",".join(filter_str)
    else:
        filter_str = f"atempo={speed}"
    command = [
        "ffmpeg",
        "-i",
        str(input_file),
        "-filter:a",
        filter_str,
        "-vn",
        "-y",
        "-v",
        "warning",
        "-c:a",
        "pcm_s16le",
        str(output_file),
    ]
    await _run_command(command, "change speed error")


async def _create_silence_wav(
    duration: float,
    output_file: str | Path,
    sample_rate: int = 24000,
    channels: int = 1,
):
    logger.debug(f"dur={duration}s, output={output_file}")
    command = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=mono",
        "-t",
        str(duration),
        "-ac",
        str(channels),
        "-c:a",
        "pcm_s16le",
        "-y",
        "-v",
        "warning",
        str(output_file),
    ]
    await _run_command(command, "create empty audio")
