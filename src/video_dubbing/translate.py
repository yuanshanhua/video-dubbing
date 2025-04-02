import asyncio
import re
from logging import Logger
from typing import Callable

from httpx import Timeout

from .args import TranslateArgument
from .llm import LLMClient
from .log import logger
from .srt import SRT
from .utils import len_hybrid, run_tasks, sub_hybrid, task_with_context


logger = logger.getChild("translate")


class LLMTranslator:
    @staticmethod
    def from_args(args: TranslateArgument) -> "LLMTranslator":
        return LLMTranslator(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.llm_model,
            req_rate=args.llm_req_rate,
        )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: Timeout = Timeout(None, connect=10),
        req_rate: float = 1,
        llm_msg_logger: Logger | None = None,
    ):
        self.client = LLMClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            req_rate=req_rate,
            msg_logger=llm_msg_logger,
        )
        self.model = model

    async def _translate_lines_as_html(
        self,
        lines: list[str],
        target_lang: str,
    ) -> list[str]:
        """
        请求 LLM 翻译多行文本. 使用 HTML 标记使结果行数尽可能与输入一致, 实测此方法行数匹配成功率很高.

        当各行均为完整的句子时, 此方法应是首选; 当行只是任意切分时, 译文各行之间会出现内容重复, 不要使用此方法.
        """
        logger.debug(f"len(lines)={len(lines)}, target_lang={target_lang}")
        src = "\n".join([f"<L{i}>{line}</L{i}>" for i, line in enumerate(lines, 1)])
        res = await self.client.ask(
            self.model,
            f"Please translate the following HTML to {target_lang} with all HTML tags unchanged. The length of each text within an Element should approximate to the original. Output only the translation.",
            user_prompt=src,
        )
        if res is None:
            return []
        list = []
        # 已知的错误格式:
        # - 行数不足
        # - 不匹配的数字, 如 <L1>...</L2>
        # - 重复 tag, 如 <L1><L1>...</L1></L1>
        re.search(r"<L\d+>", res)
        if res.count("</L") != len(lines) or res.count("<L") != len(lines):
            logger.warning("bad format: tag count mismatch")
            return []
        for i in range(1, len(lines) + 1):
            start = res.find(f"<L{i}>")
            end = res.find(f"</L{i}>")
            if start == -1 or end == -1:
                logger.warning(f"bad format: L{i} not found")
                return []
            list.append(res[start + 3 + len(str(i)) : end])
        return list

    async def translate_text(self, text: str, target_lang: str) -> str:
        """
        请求 LLM 翻译文本.

        Returns:
            str: 翻译结果.
        """
        res = await self.client.ask(
            self.model,
            f"Please translate the following text to {target_lang}. Output only the translation without any explanation.",
            user_prompt=text,
        )
        return res if res is not None else ""

    async def translate_lines(
        self,
        lines: list[str],
        target_lang: str,
        try_html: int,
        src_len_func: Callable[[str], int] = len_hybrid,
        tar_len_func: Callable[[str], int] = len_hybrid,
        sub_func: Callable[[str, int, int | None], str] = sub_hybrid,
    ) -> list[str]:
        """
        请求 LLM 翻译多行文本. 此方法保证结果行数与输入一致且含义连贯, 但不保证各行一一对应.

        Args:
            lines: 待翻译的多行文本.
            target_lang: 目标语言.
            try_html: 尝试使用 HTML 标记法的次数.
            src_len_func: 计算原文长度的函数.
            tar_len_func: 计算译文长度的函数.
            sub_func: 截取译文子串的函数.
        """
        # 首先尝试使用 HTML 标记法
        for _ in range(try_html):
            res = await self._translate_lines_as_html(lines, target_lang)
            if len(res) == len(lines):
                return res
        logger.debug(f"len(lines)={len(lines)}, target_lang={target_lang}")
        full_res = await self.translate_text(" ".join(lines), target_lang)
        # 移除结尾可能的省略号
        full_res = full_res.removesuffix("...").removesuffix("……")
        # 按原文每行的字数比例拆分翻译结果
        total_len = sum(src_len_func(line) for line in lines)
        ratio = [src_len_func(line) / total_len for line in lines]
        split_lengths = [int(tar_len_func(full_res) * r) for r in ratio][:-1]
        res = []
        for length in split_lengths:
            res.append(sub_func(full_res, 0, length).strip())
            full_res = sub_func(full_res, length, None)
        res.append(full_res.strip())
        return res


async def _translate_srt_section(
    srt: SRT,
    translator: LLMTranslator,
    target_lang: str,
    batch_size: int,
    try_html: int,
) -> SRT:
    lines = list(srt.texts())
    logger.debug(f"len(lines)={len(lines)}, batch_size={batch_size}")
    res = await asyncio.gather(
        *[
            task_with_context(
                i,
                translator.translate_lines(lines[i : i + batch_size], target_lang, try_html),
            )
            for i in range(0, len(srt), batch_size)
        ]
    )
    translated = [""] * len(srt)
    for i, texts in res:
        translated[i : i + batch_size] = texts
    return srt.with_texts(translated)


async def translate_srt(
    *,
    srt: SRT,
    target_lang: str = "简体中文",
    section_interval: float = 10,
    translator: LLMTranslator,
    batch_size: int,
    try_html: int,
    max_concurrent: int = 10,
) -> SRT:
    """
    对 srt 字幕进行翻译.

    Args:
        srt: 待翻译的字幕.
        target_lang: 目标语言.
        section_interval: 划分翻译段落的时间间隔, 单位秒. 较小意味着翻译分段更多.
        timeout: LLM API 连接超时.
        batch_size: 单次请求 LLM 翻译的最大行数.
        try_html: 尝试使用 HTML 标记法的次数.
        max_concurrent: 最大并发数.
    """
    sections = list(srt.sections(section_interval))
    logger.debug(f"sections={len(sections)} ")
    translated = await run_tasks(
        tasks=[_translate_srt_section(sec, translator, target_lang, batch_size, try_html) for sec in sections],
        max_concurrent=max_concurrent,
    )
    return SRT.from_sections(translated)
