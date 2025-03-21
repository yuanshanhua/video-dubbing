import asyncio
import time
from logging import Logger
from typing import Optional

from aiolimiter import AsyncLimiter
from httpx import Timeout
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .log import logger


logger = logger.getChild("llm")


class LLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: Timeout,
        req_rate: float,
        max_concurrent: int = 20,
        msg_logger: Logger | None = None,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.sem = asyncio.Semaphore(max_concurrent)
        self.limiter = AsyncLimiter(req_rate, 1)  # todo: allow to configure
        if msg_logger:
            self.log_msg = msg_logger.info
        else:
            self.log_msg = lambda *_, **__: None

    async def ask(
        self,
        model: str,
        system_prompt: str,
        user_prompt: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Optional[str]:
        messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": system_prompt}]
        if user_prompt:
            messages.append({"role": "user", "content": user_prompt})
        async with self.sem, self.limiter:
            count = 1
            while True:
                try:
                    chat = await self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                    )
                    break
                except Exception as e:
                    logger.warning(f"request LLM API failed: {e}")
                    logger.warning(f"wait and retry in {count}s")
                    time.sleep(count)
                    count *= 2
        reasoning_content = getattr(chat.choices[0].message, "reasoning_content", None)
        self.log_msg(f"[System] {system_prompt}")
        if user_prompt:
            self.log_msg(f"[User] {user_prompt}")
        if reasoning_content:
            self.log_msg(f"[Reasoning] {reasoning_content}")
        self.log_msg(f"[LLM] {chat.choices[0].message.content}")
        return chat.choices[0].message.content
