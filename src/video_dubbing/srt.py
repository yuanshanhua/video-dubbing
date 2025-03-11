from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, overload

from .log import logger
from .types import Segment
from .utils import len_hybrid


logger = logger.getChild("srt")


def _convert_time(seconds: float) -> str:
    """
    Convert seconds to SRT time format.

    Args:
        seconds (float): Time in seconds.

    Returns:
        str: Time in SRT format. e.g. "00:00:00,000"
    """
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    milliseconds = int((secs - int(secs)) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(secs):02},{milliseconds:03}"


@dataclass
class SRTEntry:
    index: int
    start: float
    end: float
    text: str

    def __str__(self):
        return f"{self.index}\n{_convert_time(self.start)} --> {_convert_time(self.end)}\n{self.text}\n"

    def __len__(self):
        return len(self.text)


class SRT:
    """
    用于表示及处理 srt (SubRip Subtitle) 格式的字幕.

    ASR 流程中的任务以字幕作为输入/输出. 对于不同任务, 字幕具有不同的性质.
    - 最理想的字幕: 各行长度适中, 包含一个/几个整句(以标点符号划分), 时间戳准确.
    - VAD + Whisper 识别结果: 时间戳较准确, 长度部分可控, 不保证句子完整, 不保证标点符号(英语转译可保证).
    - 翻译任务期待: 各行需为整句, 否则容易导致行间干扰, 长度, 标点无要求.
    - TTS 任务期待: 要求最高. 由于只能通过起止时间戳进行对齐, 因此要求每行为一个完整句子, 且长度适中.
        行长度过长, 则后部分会出现音画不同步; 句子不完整, 会导致听感割裂.
    """

    @staticmethod
    def from_segments(segments: list[Segment]) -> "SRT":
        logger.info(f"len={len(segments)}")
        return SRT([SRTEntry(i, seg["start"], seg["end"], seg["text"].strip()) for i, seg in enumerate(segments, 1)])

    @staticmethod
    def from_file(path: str | Path) -> "SRT":
        """
        读取 srt 文件. 仅适用于格式正确的简单 srt 文件.
        """
        logger.info(f"{path}")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = []
        finish = True
        for line in lines:
            t = line.strip()
            if not t:
                continue
            if t.isdigit() and finish:
                finish = False
                index = int(t)
                entries.append(SRTEntry(index, 0, 0, ""))
                continue
            if " --> " in t:
                start, end = t.split(" --> ")
                start = start.strip()  # 00:02:09,061
                end = end.strip()
                start = start.replace(",", ".")
                end = end.replace(",", ".")
                start = sum(float(x) * 60.0**i for i, x in enumerate(reversed(start.split(":"))))
                end = sum(float(x) * 60.0**i for i, x in enumerate(reversed(end.split(":"))))
                entries[-1].start = start
                entries[-1].end = end
                continue
            if not finish:
                entries[-1].text += t
                finish = True
        logger.debug(f"parse {len(entries)} entries from {len(lines)} lines")
        return SRT(entries)

    @staticmethod
    def from_sections(sections: list["SRT"]) -> "SRT":
        """
        依次合并多个 SRT, 不进行任何调整. 返回一个新的 SRT 对象.
        """
        logger.info(f"merge {len(sections)} sections")
        entries = []
        for s in sections:
            for e in s:
                entries.append(SRTEntry(e.index, e.start, e.end, e.text))
        return SRT(entries)

    def __init__(self, entries: list[SRTEntry]):
        self.entries = entries

    def get_index(self, index: int) -> Optional[SRTEntry]:
        """
        获取索引为 index 的字幕行. 若不存在则返回 None.
        """
        # fast path
        if 1 <= index <= len(self) and self[index - 1].index == index:
            return self[index - 1]
        for entry in self.entries:
            if entry.index == index:
                return entry

    def with_texts(self, texts: list[str]) -> "SRT":
        """
        返回一个新的 SRT, 其文本内容由 texts 提供.
        """
        if len(texts) != len(self):
            logger.warning(f"length mismatch: texts({len(texts)}) != raw({len(self)})")
        return SRT(
            [
                SRTEntry(
                    e.index,
                    e.start,
                    e.end,
                    text,
                )
                for e, text in zip(self, texts)
            ]
        )

    def concat_text(self, other: "SRT", sep="\n") -> "SRT":
        """
        返回一个新的 SRT, 其长度和时间戳来自较长者, 文本按索引合并.

        一般用于创建双语字幕.

        Args:
            other: 另一个 SRT 对象, 只有其中文本会被合并.
            sep: 合并文本时使用的分隔符.
        """
        if len(self) < len(other):
            self, other = other, self
        return SRT(
            [
                SRTEntry(
                    e.index,
                    e.start,
                    e.end,
                    (e.text + sep + e1.text) if (e1 := other.get_index(e.index)) else e.text,
                )
                for e in self
            ]
        )

    def merge(self, other: "SRT") -> "SRT":
        """
        将两个字幕合并, 按起始时间排序各行并重新编号.
        """
        entries = sorted(self.entries + other.entries, key=lambda x: x.start)
        for i, entry in enumerate(entries, 1):
            entry.index = i
        return SRT(entries)

    def sort(self) -> "SRT":
        """
        返回一个新的 SRT, 其字幕行按起始时间排序并重新编号.
        """
        entries = sorted(self.entries, key=lambda x: x.start)
        for i, entry in enumerate(entries, 1):
            entry.index = i
        return SRT(entries)

    def offset(self, seconds: float) -> "SRT":
        """
        就地偏移此字幕的时间戳. 不进行负时间戳检查.
        """
        for entry in self.entries:
            entry.start += seconds
            entry.end += seconds
        return self

    def concat(self, other: "SRT", interval: float = 0) -> "SRT":
        """
        返回一个新的字幕, 依次包含此字幕和另一个字幕的内容, 并调整索引和时间戳.

        Args:
            other: 待添加的字幕.
            interval: 两字幕间的时间间隔.
        """
        s = other.copy().offset(self[-1].end + interval)
        for entry in s.entries:
            entry.index += len(self)
        return SRT(self.entries + s.entries)

    def __add__(self, other: "SRT") -> "SRT":
        return self.concat(other)

    @overload
    def __getitem__(self, key: slice) -> list[SRTEntry]: ...
    @overload
    def __getitem__(self, key: int) -> SRTEntry: ...
    def __getitem__(self, key):
        return self.entries[key]

    def __iter__(self):
        return iter(self.entries)

    def __str__(self):
        return "\n".join(str(entry) for entry in self.entries)

    def __len__(self):
        return len(self.entries)

    def copy(self) -> "SRT":
        return SRT([SRTEntry(e.index, e.start, e.end, e.text) for e in self.entries])

    def sections(self, max_interval: float = 1.0) -> Iterable["SRT"]:
        """
        将字幕按照时间间隔分割成多个部分. 每部分内相邻字幕的时间间隔不超过 max_interval.

        Args:
            max_interval: 相邻字幕间超过此时间则分割, 单位为秒.
        """
        start = 0
        for i in range(1, len(self)):
            if self[i].start - self[i - 1].end > max_interval:
                yield SRT(self[start:i])
                start = i
        yield SRT(self[start:])

    @property
    def average_length(self) -> float:
        return sum(len(entry) for entry in self.entries) / len(self)

    @property
    def min_length(self) -> int:
        return min(len(entry) for entry in self.entries)

    @property
    def max_length(self) -> int:
        return max(len(entry) for entry in self.entries)

    def save(self, path: str | Path) -> "SRT":
        logger.info(f"{path}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(self))
        return self

    def remove_ellipsis(self) -> "SRT":
        """
        修改原对象. 移除行首尾出现的省略号.

        使用 VAD + Whisper 识别时, 若 VAD 区间不是完整句子, 则识别结果可能以 ... 开头/结尾, 影响后续句子合并.
        """
        for entry in self.entries:
            if entry.text.startswith(("...", "……")) or entry.text.endswith(("...", "……")):
                entry.text = entry.text.removeprefix("...").removesuffix("……").removesuffix("...").removesuffix("……")
        return self

    def merge_by_length(
        self,
        interval: float = 0.5,
        max_length: int = 80,
        sep: str = " ",
    ) -> "SRT":
        """
        返回一个新的 SRT, 其中符合要求的相邻字幕被合并.

        Args:
            interval: 若相邻字幕的时间间隔小于此, 将进行合并. 单位为秒.
            max_length: 合并后单行字幕的最大长度.
            sep: 合并文本时使用的分隔符.
        """
        logger.debug(f"interval={interval}, max_length={max_length}, sep='{sep}'")
        new_entries = [SRTEntry(1, self[0].start, self[0].end, self[0].text)]
        for entry in self[1:]:
            last_entry = new_entries[-1]
            if entry.start - last_entry.end < interval and len(entry) + len(last_entry) < max_length:
                last_entry.end = entry.end
                last_entry.text += sep + entry.text
            else:
                new_entries.append(SRTEntry(last_entry.index + 1, entry.start, entry.end, entry.text))
        logger.info(f"merge {len(self)} entries to {len(new_entries)}")
        return SRT(new_entries)

    def split_by_length(
        self,
        max_length: int = 80,
        min_tail_length: int = 20,
        sep: str = " ",
    ) -> "SRT":
        """
        返回一个新的 SRT, 其中文本过长的行被分割.

        时间戳按长度比例计算, 因此会产生偏差.

        分割后会产生短的尾部, 可使用 min_tail_length 参数控制.

        Args:
            max_length: 分割后单行字幕的最大长度.
            min_tail_length: 分割后尾部的最小长度. 若分割后尾部长度小于此值, 则不分割.
            sep: 分割文本时用于定界的分隔符. 对字母语言通常使用空格. 对于中文使用空串.
        """
        logger.debug(f"max_length={max_length}, min_tail_length={min_tail_length}, sep='{sep}'")
        new_entries = []
        i = 1
        for entry in self:
            entry_length = len(entry)
            if entry_length <= max_length:
                new_entries.append(SRTEntry(i, entry.start, entry.end, entry.text))
                i += 1
                continue
            s = entry.text
            start = entry.start
            # 按长度比例计算每段的大概持续时间
            duration = (max_length - 1) / entry_length * (entry.end - entry.start)
            split_index = max_length
            while split_index > 0:
                # 寻找第 max_length 个字符后的第一个 sep 作为分割位置
                split_index = s.find(sep, split_index)
                # 短尾部, 合并到上一段
                if split_index == -1 and len(s) < min_tail_length:
                    new_entries[-1].text += sep + s
                    new_entries[-1].end = entry.end
                    break
                # 最后一段可能不足时长
                end = min(start + duration, entry.end)
                new_entries.append(SRTEntry(i, start, end, s[:split_index] if split_index > 0 else s))
                i += 1
                start = end
                s = s[split_index + 1 :]
        logger.info(f"split {len(self)} entries to {len(new_entries)}")
        return SRT(new_entries)

    def adjust_by_length(
        self,
        max_length: int = 80,
        min_tail_length: int = 40,
        merge_sep: str = " ",
        split_sep: str = " ",
    ) -> "SRT":
        """
        合并短行, 分割长行. 此方法尽力满足约束. 返回一个新的 SRT 对象.

        在调整前通常要先进行时间戳校正, 使得相邻字幕的时间不重叠.

        Args:
            min_tail_length: 最短长度约束. 分割时保证不产生短于此长度的字幕, 但不保证原有短字幕一定被合并.
            max_length: 最长长度约束. 由于受短尾部约束, 实际最长不超过 max_length + min_tail_length. 另外, 限制字符长度时会上取到完整单词.
            merge_sep: 合并文本时使用的分隔符.
            split_sep: 分割文本时用于定界的分隔符. 对字母语言通常使用空格. 对于中文使用空串.
        """
        if self.max_length <= max_length:
            return self.merge_by_length(0.5, max_length, merge_sep)
        return self.split_by_length(max_length, min_tail_length, split_sep).merge_by_length(0.5, max_length, merge_sep)

    def split_sentences(
        self,
        puncs: str = "。！？.!?",
        interval: float = 0.5,
        len_func: Callable[[str], int] = len_hybrid,
    ) -> "SRT":
        """
        分割字幕中较长的行, 使得最终每行恰好包含一句. 返回一个新的 SRT 对象.

        此方法使用标点符号界定句子, 按文本长度计算分割后的时间戳, 可能造成时间戳偏差.

        Args:
            puncs: 用于界定句子的标点.
            interval: 若相邻字幕的时间间隔小于此, 将进行合并. 单位为秒.
            len_func: 用于计算文本长度的函数.
        """
        logger.debug(f"puncs='{puncs}', interval={interval}")
        entries = []
        i = 1
        for entry in self:
            s = entry.text
            start = entry.start
            end = entry.end
            while len_func(s) > 0:
                split_index = -1
                for punc in puncs:
                    split_index = s.find(punc)
                    if split_index != -1:
                        break
                if split_index == -1:
                    entries.append(SRTEntry(i, start, end, s))
                    i += 1
                    break
                split_index += 1
                if len_func(s[:split_index]) > 0:
                    entries.append(
                        SRTEntry(
                            i,
                            start,
                            start + (end - start) * len_func(s[:split_index]) / len_func(s),
                            s[:split_index],
                        )
                    )
                    i += 1
                start += (end - start) * len_func(s[:split_index]) / len_func(s)
                s = s[split_index:]
        logger.info(f"{len(self)} -> {len(entries)}")
        return SRT(entries)

    def merge_sentences(
        self,
        puncs: str = "。！？.!?",
        interval: float = 0.5,
        min_length: int = 10,
        len_func: Callable[[str], int] = len_hybrid,
    ) -> "SRT":
        """
        合并不完整的和较短的句子. 由于仅进行合并操作, 因此不会产生时间戳偏差.

        Args:
            puncs: 用于界定句子的标点.
            interval: 允许合并的最大时间间隔. 单位为秒.
            min_length: 单句的最小长度. 短于此长度的句子会被强制合并到下一句.
            len_func: 用于计算文本长度的函数.
        """
        logger.debug(f"puncs='{puncs}', interval={interval}")
        sentences = [SRTEntry(1, self[0].start, self[0].end, self[0].text)]
        for entry in self[1:]:
            last_entry = sentences[-1]
            if (last_entry.text[-1] not in puncs and entry.start - last_entry.end < interval) or len_func(
                entry.text
            ) < min_length:
                last_entry.end = entry.end
                last_entry.text += " " + entry.text
            else:
                sentences.append(SRTEntry(last_entry.index + 1, entry.start, entry.end, entry.text))
        logger.info(f"{len(self)} -> {len(sentences)}")
        return SRT(sentences)

    def sentences_percent(self, puncs: str = "。！？.!?") -> float:
        """
        检查字幕是否分句良好, 返回以句尾标点结尾的行比例.

        Args:
            puncs: 用于界定句子的标点.

        Returns:
            float: 0~1, 表示完整句子的比例.
        """
        logger.debug(f"puncs='{puncs}'")
        count = 0
        for entry in self:
            if entry.text[-1] in puncs:
                count += 1
        logger.debug(f"{count} / {len(self)} = {count / len(self) * 100:.2f}%")
        return count / len(self)

    def correct_time(self, modify_start: bool = False) -> "SRT":
        """
        就地修正字幕时间戳, 使得相邻字幕的时间不重叠.

        Args:
            modify_start: 为 True 则修改开始时间, 否则修改结束时间.
        """
        logger.info("correct time")
        for i in range(1, len(self)):
            if self[i - 1].end > self[i].start:
                if modify_start:
                    self[i].start = self[i - 1].end
                else:
                    self[i - 1].end = self[i].start
        return self

    def fill_time(self, modify_start: bool = False) -> "SRT":
        """
        就地填充时间戳使得相邻字幕间无间隔.
        """
        logger.info("fill time")
        for i in range(1, len(self)):
            if modify_start:
                self[i].start = self[i - 1].end
            else:
                self[i - 1].end = self[i].start
        return self

    def texts(self) -> Iterable[str]:
        yield from (entry.text for entry in self.entries)
