from typing import Callable, Iterable, Iterator

from .types import Segment, Word


MIN_SEGMENT_DURATION = 1.0  # seconds


def split_segments(
    segments: list[Segment],
    sep: str,
) -> list[Segment]:
    """
    将长的文本片段分割成多个短片段. 输入中必须包含词汇级时间戳.

    首先根据说话者分割, 然后根据标点符号分割.
    """
    tmp1 = _split_by_f(segments, sep, _split_segment_by_speaker)
    tmp2 = _split_by_f(tmp1, sep, _split_segment_by_punctuation)
    return tmp2


F = Callable[[Segment], Iterable[tuple[int, int]]]


def _split_by_f(segments: list[Segment], sep: str, splitter: F) -> list[Segment]:
    """
    Splits segments into smaller segments based on the provided splitter function.

    Args:
        segments (list[Segment]): A list of Segment objects to be split. Each Segment must contain a "words" key.
        splitter (Callable[[Segment], list[tuple[int, int]]]): A function that takes a Segment and returns a list of tuples,
            where each tuple contains the start and end indices for splitting the segment.

    Returns:
        list[Segment]: A list of new Segment objects created by splitting the original segments.
    """
    tmp = []
    for seg in segments:
        assert "words" in seg
        for start, end in splitter(seg):
            print(f"split: {start}, {end}")
            s = {
                "text": sep.join(word["word"] for word in seg["words"][start : end + 1]).strip(),
                "start": seg["words"][start]["start"],
                "end": seg["words"][end]["end"],
                "speaker": seg["words"][start]["speaker"],
                "words": seg["words"][start : end + 1],
            }
            if s["text"]:
                tmp.append(s)
    return tmp


def _split_segment_by_speaker(seg: Segment) -> Iterator[tuple[int, int]]:
    """
    根据词汇级时间戳将长的文本片段分割成多个短片段.

    Args:
        seg (Segment): 待切分的长片段, 需带有 DiarizationResult 中的 speaker 标签.

    Yields:
        Iterator[tuple[int, int]]: 短片段对应 seg["words"] 中的起始和结束索引.
    """
    assert "words" in seg
    words: list[Word] = seg["words"]
    cur_speaker = ""
    start_time = -1
    start_index = 0
    for i, word in enumerate(words):
        if "speaker" not in word:  # 模型无法识别的词, 只有 word 字段
            j = i + 1
            while j < len(words) and "start" not in words[j]:
                j += 1
            if j < len(words):
                word["end"] = words[j]["start"]
            else:
                word["end"] = seg["end"]
            j = i - 1
            while j > -1 and "end" not in words[j]:
                j -= 1
            if j > -1:
                word["start"] = words[j]["end"]
            else:
                word["start"] = seg["start"]
            word["speaker"] = cur_speaker
            continue
        if start_time == -1:  # 第一个模型识别出的词
            start_time = word["start"]
            cur_speaker = word["speaker"]
            continue
        if word["speaker"] != cur_speaker and word["start"] - start_time >= MIN_SEGMENT_DURATION:
            yield (
                start_index,
                i - 1,
            )
            cur_speaker = word["speaker"]
            start_time = word["start"]
            start_index = i
    yield (start_index, len(words) - 1)


def _split_segment_by_punctuation(seg: Segment) -> Iterator[tuple[int, int]]:
    """
    根据标点符号将长的文本片段分割成多个短片段.

    Args:
        seg (Segment): 待切分的长片段.

    Yields:
        Iterator[tuple[int, int]]: 短片段对应 seg["words"] 中的起始和结束索引.
    """
    assert "words" in seg
    words: list[Word] = seg["words"]
    start_index = 0
    for i, word in enumerate(words):
        if word["word"] in "。！？.!? ":
            yield (start_index, i)
            start_index = i + 1
    if start_index < len(words):
        yield (start_index, len(words) - 1)
