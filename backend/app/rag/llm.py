"""Клиент llama-server (OpenAI-совместимый API) с потоковой генерацией."""
from typing import AsyncIterator

import httpx
from openai import AsyncOpenAI


class LlamaClient:
    def __init__(self, base_url: str, temperature: float, max_tokens: int):
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        # повторы только при сбое соединения/запроса до начала потока (редкие обрывы сети Docker Desktop);
        # уже начавшийся поток не повторяется
        self._client = AsyncOpenAI(base_url=f"{self.base_url}/v1", api_key="no-key", timeout=300, max_retries=2)

    async def health(self) -> str:
        """ready | loading | down — по /health llama-server."""
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"{self.base_url}/health")
            if r.status_code == 200:
                return "ready"
            if r.status_code == 503:
                return "loading"
            return "down"
        except httpx.HTTPError:
            return "down"

    async def stream(self, messages: list[dict]) -> AsyncIterator[tuple[str, object]]:
        """Выдаёт ("token", str) по мере генерации и в конце ("usage", {...})."""
        stream = await self._client.chat.completions.create(
            model="local",
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            async for ev in stream:
                if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
                    yield "token", ev.choices[0].delta.content
                if getattr(ev, "usage", None):
                    yield "usage", {
                        "prompt_tokens": ev.usage.prompt_tokens,
                        "completion_tokens": ev.usage.completion_tokens,
                    }
        finally:
            await stream.close()  # обрыв соединения останавливает генерацию на сервере
