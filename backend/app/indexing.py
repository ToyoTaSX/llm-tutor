"""Фоновая индексация документов: очередь + один воркер (design D10)."""
import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .models import Document, utcnow
from .rag.chunker import split_chunks

log = logging.getLogger(__name__)
BATCH = 16


class Indexer:
    def __init__(self, settings: Settings, sm: sessionmaker, embedder, store):
        self.settings = settings
        self.sm = sm
        self.embedder = embedder
        self.store = store
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    # ---------- управление ----------
    def start(self) -> None:
        self._task = asyncio.create_task(self._worker(), name="indexer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def enqueue(self, doc_id: int) -> None:
        self.queue.put_nowait(doc_id)

    def requeue_interrupted(self) -> int:
        """Документы, чья индексация прервалась перезапуском, ставятся в очередь заново."""
        with self.sm() as db:
            ids = list(db.scalars(select(Document.id).where(Document.status == "indexing").order_by(Document.id)))
        for i in ids:
            self.enqueue(i)
        return len(ids)

    async def join(self) -> None:
        await self.queue.join()

    # ---------- работа ----------
    async def _worker(self) -> None:
        while True:
            doc_id = await self.queue.get()
            try:
                await self.index_document(doc_id)
            except Exception:  # noqa: BLE001  воркер не должен умирать
                log.exception("Сбой воркера индексации на документе %s", doc_id)
            finally:
                self.queue.task_done()

    def _exists(self, doc_id: int) -> bool:
        with self.sm() as db:
            return db.get(Document, doc_id) is not None

    async def index_document(self, doc_id: int) -> None:
        with self.sm() as db:
            doc = db.get(Document, doc_id)
            if doc is None:
                return
            title, path = doc.title, Path(doc.file_path)
        log.info("Индексация документа %s «%s»", doc_id, title)
        try:
            ready = await asyncio.to_thread(self.embedder.ready.wait, 600)
            if not ready or self.embedder.error:
                raise RuntimeError(self.embedder.error or "Модель эмбеддингов не загрузилась")
            text = path.read_text(encoding="utf-8")
            chunks = split_chunks(text, self.settings.chunk_chars, self.settings.overlap_chars)
            if not chunks:
                raise ValueError("В документе нет текста")
            await run_in_threadpool(self.store.delete_by_doc, doc_id)
            for start in range(0, len(chunks), BATCH):
                if not self._exists(doc_id):  # документ удалили во время индексации
                    await run_in_threadpool(self.store.delete_by_doc, doc_id)
                    return
                part = chunks[start : start + BATCH]
                # блокировка эмбеддера берётся на батч: вопросы студентов проходят между батчами
                dense, sparse = await run_in_threadpool(self.embedder.encode, part)
                await run_in_threadpool(self.store.upsert_chunks, doc_id, title, start, part, dense, sparse)
        except Exception as e:  # noqa: BLE001
            log.exception("Ошибка индексации документа %s", doc_id)
            try:
                await run_in_threadpool(self.store.delete_by_doc, doc_id)
            except Exception:  # noqa: BLE001
                log.exception("Не удалось очистить фрагменты документа %s", doc_id)
            self._finish(doc_id, status="error", error=str(e) or e.__class__.__name__)
            return
        self._finish(doc_id, status="ready", chunks=len(chunks), chars=len(text))
        log.info("Документ %s готов: %d фрагментов", doc_id, len(chunks))

    def _finish(self, doc_id: int, status: str, error: str | None = None, chunks: int = 0, chars: int | None = None):
        with self.sm() as db:
            doc = db.get(Document, doc_id)
            if doc is None:
                if status == "ready":  # удалён в последний момент
                    self.store.delete_by_doc(doc_id)
                return
            doc.status = status
            doc.error = error
            doc.chunks_count = chunks
            if chars is not None:
                doc.chars = chars
            doc.indexed_at = utcnow() if status == "ready" else None
            db.commit()
