"""Состояние сервисов для UI и healthcheck."""
from fastapi import APIRouter, Request
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from ..models import Document

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(request: Request):
    st = request.app.state
    emb = st.embedder
    if not emb.ready.is_set():
        embedder = "loading"
    else:
        embedder = "error" if emb.error else "ready"
    with st.sessionmaker() as db:
        ready_docs = db.scalar(select(func.count()).where(Document.status == "ready"))
        indexing = db.scalar(select(func.count()).where(Document.status == "indexing"))
    return {
        "llm": await st.llm.health(),
        "qdrant": "ready" if await run_in_threadpool(st.store.ping) else "down",
        "embedder": embedder,
        "embedder_error": emb.error,
        "gpu": st.gpu_name,
        "model": st.settings.llm_file,
        "documents_ready": ready_docs,
        "documents_indexing": indexing,
    }
