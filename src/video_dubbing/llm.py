import asyncio
import time
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
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.sem = asyncio.Semaphore(max_concurrent)
        self.limiter = AsyncLimiter(req_rate, 1)  # todo: allow to configure

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
        logger.debug(f"System:\n{system_prompt}\nUser:\n{user_prompt}\nAssistant:\n{chat.choices[0].message.content}")
        return chat.choices[0].message.content
