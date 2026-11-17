"""Сборка RAG: поиск фрагментов, веб-поиск через MCP и потоковый ответ (design D5)."""
import asyncio
import time
from typing import Any, AsyncIterator, Protocol

from starlette.concurrency import run_in_threadpool

from ..config import Settings
from .prompt import build_messages


class Embedder(Protocol):
    ready: object
    error: str | None

    def encode(self, texts: list[str], max_length: int = 512): ...


class Store(Protocol):
    def search(self, dense, sparse, ready_ids, k, candidates, rrf_k) -> list[dict]: ...


class Llm(Protocol):
    def stream(self, messages: list[dict]) -> AsyncIterator[tuple[str, object]]: ...
    async def health(self) -> str: ...


class WebSearch(Protocol):
    async def search(self, query: str) -> dict: ...


MODES = ("course", "web")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


class RagEngine:
    def __init__(self, settings: Settings, embedder: Embedder, store: Store, llm: Llm, web: WebSearch | None = None):
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.llm = llm
        self.web = web

    async def wait_embedder(self, timeout: float = 180) -> None:
        ok = await asyncio.to_thread(self.embedder.ready.wait, timeout)
        if not ok:
            raise RuntimeError("Модель эмбеддингов ещё загружается, попробуйте через минуту")
        if self.embedder.error:
            raise RuntimeError(f"Модель эмбеддингов недоступна: {self.embedder.error}")

    async def retrieve(self, question: str, ready_ids: list[int]) -> list[dict]:
        await self.wait_embedder()
        dense, sparse = await run_in_threadpool(self.embedder.encode, [question], 256)
        s = self.settings
        return await run_in_threadpool(
            self.store.search, dense[0], sparse[0], ready_ids, s.top_k, s.candidates, s.rrf_k
        )

    def stream_answer(self, question: str, chunks: list[dict], web: dict | None = None,
                      mode: str = "course") -> AsyncIterator[tuple[str, object]]:
        return self.llm.stream(build_messages(question, chunks, web, mode))

    async def _search_web(self, question: str) -> dict:
        if self.web is None:
            return {"query": question, "status": "error", "results": [], "t_ms": 0,
                    "error": "Веб-поиск не настроен", "tool": None}
        return await self.web.search(question)

    async def answer_events(self, question: str, ready_ids: list[int],
                            mode: str = "course") -> AsyncIterator[tuple[str, Any]]:
        """Общий конвейер для /api/ask и scripts/eval.py. События:
        web_status {state} (только web) → sources {chunks, t_search_ms} → web_sources {…WebSearchResult} (только web)
        → token str* → usage {…} → timings {t_search_ms, t_mcp_ms, t_llm_ms, t_total_ms}.
        Во внешний поиск уходит только текст вопроса. Сбой веб-поиска не прерывает ответ."""
        t0 = time.perf_counter()
        web_task: asyncio.Task | None = None
        if mode == "web":
            # MCP и поиск по лекциям идут параллельно, каждый этап засекается отдельно
            web_task = asyncio.create_task(self._search_web(question))
            yield "web_status", {"state": "searching"}
        try:
            chunks = await self.retrieve(question, ready_ids)
            t_search = _ms(t0)
            yield "sources", {"chunks": chunks, "t_search_ms": t_search}
            web = None
            if web_task is not None:
                web = await web_task
                yield "web_sources", web
            t1 = time.perf_counter()
            async for kind, val in self.stream_answer(question, chunks, web, mode):
                yield kind, val
            yield "timings", {"t_search_ms": t_search, "t_mcp_ms": web["t_ms"] if web else None,
                              "t_llm_ms": _ms(t1), "t_total_ms": _ms(t0)}
        finally:
            if web_task is not None and not web_task.done():
                web_task.cancel()
