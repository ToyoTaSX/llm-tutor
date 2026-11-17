"""Точка входа FastAPI."""
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from .auth.router import router as auth_router
from .config import Settings, load_settings
from .db import make_sessionmaker
from .documents_service import seed_demo_corpus
from .indexing import Indexer
from .rag.mcp_search import install_secret_mask
from .rag.engine import RagEngine
from .routers import ask, documents, health, history, stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@dataclass
class Components:
    embedder: object
    store: object
    llm: object
    web: object | None = None
    gpu_name: str | None = None
    load_embedder_in_background: bool = True


def detect_gpu() -> str | None:
    try:
        import torch

        if not torch.cuda.is_available():
            log.warning("CUDA недоступна: модели будут работать на CPU")
            return None
        name = torch.cuda.get_device_name(0)
        log.info("GPU: %s, compute capability %s, torch %s, CUDA %s",
                 name, torch.cuda.get_device_capability(0), torch.__version__, torch.version.cuda)
        return name
    except Exception:  # noqa: BLE001
        log.exception("Не удалось определить GPU")
        return None


def real_components(settings: Settings) -> Components:
    from .rag.embedder import BgeM3Embedder
    from .rag.llm import LlamaClient
    from .rag.mcp_search import WebSearcher
    from .rag.store import QdrantStore

    gpu = detect_gpu()
    device = settings.emb_device if gpu else "cpu"
    return Components(
        embedder=BgeM3Embedder(settings.emb_model_path, device, settings.emb_batch),
        store=QdrantStore(settings.qdrant_url, settings.collection),
        llm=LlamaClient(settings.llm_url, settings.temperature, settings.max_tokens),
        web=WebSearcher.from_settings(settings),
        gpu_name=gpu,
    )


def _ensure_collection(store, attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            store.ensure_collection()
            return
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            log.info("Qdrant пока недоступен (%s), жду…", e)
            time.sleep(2)


def create_app(settings: Settings | None = None, components: Components | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = app.state.settings
        comps = components or real_components(s)
        app.state.embedder = comps.embedder
        app.state.store = comps.store
        app.state.llm = comps.llm
        app.state.gpu_name = comps.gpu_name
        app.state.web = comps.web
        app.state.engine = RagEngine(s, comps.embedder, comps.store, comps.llm, comps.web)

        await asyncio.to_thread(_ensure_collection, comps.store)
        if comps.load_embedder_in_background:
            threading.Thread(target=comps.embedder.load, name="embedder-load", daemon=True).start()
        else:
            comps.embedder.load()

        indexer = Indexer(s, app.state.sessionmaker, comps.embedder, comps.store)
        app.state.indexer = indexer
        n = indexer.requeue_interrupted()
        if n:
            log.info("Возобновлена индексация %d документов", n)
        with app.state.sessionmaker() as db:
            seed_id = seed_demo_corpus(db, s)
        if seed_id is not None:
            indexer.enqueue(seed_id)
        indexer.start()
        yield
        await indexer.stop()

    settings = settings or load_settings()
    install_secret_mask(settings.mcp_api_key)
    app = FastAPI(title="LLM Tutor", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(settings.data_dir / "app.db")
    for r in (auth_router, ask.router, history.router, documents.router, stats.router, health.router):
        app.include_router(r)
    return app
# запуск: uvicorn app.main:create_app --factory
