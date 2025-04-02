import asyncio
import unicodedata
from pathlib import Path
from typing import Any, Coroutine, TypeVar


# 空格和标点符号(不包括连字符 Pc 和 Pd)
SPACE = ("Zs", "Cc", "Po", "Ps", "Pe", "Pi", "Pf")
# 字母, 连字符, 下划线, 数字, (非标点)符号
LETTER = ("Ll", "Lu", "Nd", "Nl", "No", "Pc", "Pd")

T = TypeVar("T")
C = TypeVar("C")


async def _task_with_semaphore(
    sem: asyncio.Semaphore,
    coro: Coroutine[Any, Any, T],
) -> T:
    async with sem:
        return await coro


async def task_with_context(
    context: C,
    coro: Coroutine[Any, Any, T],
) -> tuple[C, T]:
    return context, await coro


async def run_tasks(
    tasks: list[Coroutine[Any, Any, T]],
    max_concurrent: int,
) -> list[T]:
    sem = asyncio.Semaphore(max_concurrent)
    return await asyncio.gather(*[_task_with_semaphore(sem, t) for t in tasks])


def len_hybrid(text: str) -> int:
    """
    计算文本长度, 以单词为单位. 适用于 CJK 字符与英文混合的文本.

    单词定义: 连续出现的任意多个 `LETTER` 中的字符视为一个单词; `SPACE` 中的字符视为单词分隔符; 其它字符均视为一个单词.

    通俗来说:
    - 连续的英文字母/连字符/下划线/数字/(非标点)符号是一个单词
    - 单个 CJK 字符等是一个单词
    - 空格/标点符号是单词分隔符

    例如:
    >>> assert len_hybrid("Hello 世界 World") == 4  # Hello, 世, 界, World
    >>> assert len_hybrid("deepseek-r1") == 1
    """
    # unicode category: https://en.wikipedia.org/wiki/Unicode_character_property
    # https://www.compart.com/en/unicode/category
    skip = 0  # 需要跳过的字符数
    in_word = False  # 是否在单词中
    for c in text:
        # 匹配空格等, 作为单词分隔符, 但自身不计入长度
        cat = unicodedata.category(c)
        if cat in SPACE:
            skip += 1
            in_word = False
            continue
        # 匹配字母等
        if cat in LETTER:
            if not in_word:  # 单词开始
                in_word = True
            else:
                skip += 1  # 单词后续字符
            continue
        # 其他字符, 认为只可能是 CJK 字符
        in_word = False
    return len(text) - skip


def sub_hybrid(s: str, start: int, stop: int | None) -> str:
    """
    用于中英文的混合字符串切片, 可避免截断单词. 单词定义见 `len_hybrid`.

    当索引位于单词中间时, 会将起始索引推后到下一个单词的开始, 将终止索引推后到当前单词的结束.
    """
    # 负起始索引
    if start < 0:
        start += len(s)
    # 越界
    if start >= len(s):
        return ""
    if stop is not None:
        if stop < 0:  # 负终止索引
            stop += len(s)
        if stop <= start:  # 终止索引在起始索引之前
            return ""
        if stop >= len(s):  # 终止索引超出范围
            stop = None

    # 推后起始索引到下一个单词开始
    in_word = False
    if start > 0:
        in_word = unicodedata.category(s[start - 1]) in LETTER
    for c in s[start:]:
        cat = unicodedata.category(c)
        # print(c, cat)
        # 空格, 标点符号, 单词内部的字母不能作为子串的开始
        if cat in SPACE:  # 到达单词分隔符, 下一个非分隔符即可开始
            start += 1
            in_word = False
            continue
        if cat in LETTER and in_word:  # 单词内部
            start += 1
            continue
        break
    if stop is None:
        return s[start:]
    if stop <= start:
        return ""
    # 提前终止索引到上一个单词结束
    modified = False  # 记录是否修改了终止索引
    for c in s[stop - 1 :]:
        # stop-1 位置的字符将是子串的最后一个字符
        cat = unicodedata.category(c)
        # print(c, cat)
        if cat in LETTER:  # 当前字符是字母, 不能作为子串的结束
            stop += 1
            modified = True
            continue
        break
    if modified and s[stop - 1] not in SPACE:  # 单词结束, 但不是分隔符
        # 此时子串不应包含这个非分隔符, 因为下一个切片会包含, 导致连续索引切片出现重叠
        stop -= 1
    # print(start, stop)
    return s[start:stop]


def safe_glob(path: str):
    """如果原路径存在, 直接返回, 否则视为 glob."""
    p = Path(path)
    if p.exists():
        return [p]
    return list(Path().glob(path))
