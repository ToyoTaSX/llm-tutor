"""Общие фикстуры: приложение с подменёнными эмбеддером, хранилищем и LLM (без GPU)."""
import asyncio
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import Components, create_app
from app.rag.embedder import SparseVec

WORD_RE = re.compile(r"\w+", re.U)


def _words(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text)}


class FakeEmbedder:
    def __init__(self):
        self.ready = threading.Event()
        self.error = None
        self.fail = False
        self.calls = 0

    def load(self):
        self.ready.set()

    def encode(self, texts, max_length=512):
        self.calls += 1
        if self.fail:
            raise RuntimeError("encode failed (test)")
        dense = [[float(b) for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]
        sparse = [SparseVec(indices=[1], values=[1.0]) for _ in texts]
        # «вектор» несёт сам текст, чтобы фейковый поиск мог сравнивать слова
        for d, t in zip(dense, texts):
            d.append(t)  # type: ignore[arg-type]
        return dense, sparse


class FakeStore:
    def __init__(self):
        self.points: dict[int, dict[int, dict]] = {}

    def ping(self):
        return True

    def ensure_collection(self):
        pass

    def upsert_chunks(self, doc_id, doc_title, start_no, texts, dense, sparse):
        d = self.points.setdefault(doc_id, {})
        for i, t in enumerate(texts):
            d[start_no + i] = {"doc_id": doc_id, "doc_title": doc_title, "chunk_no": start_no + i, "text": t}

    def delete_by_doc(self, doc_id):
        self.points.pop(doc_id, None)

    def count_by_doc(self, doc_id):
        return len(self.points.get(doc_id, {}))

    def search(self, dense, sparse, ready_ids, k, candidates, rrf_k):
        q = _words(dense[-1])
        scored = []
        for doc_id in ready_ids:
            for p in self.points.get(doc_id, {}).values():
                overlap = len(q & _words(p["text"]))
                if overlap:
                    scored.append({"score": overlap / 100, **p})
        scored.sort(key=lambda x: -x["score"])
        return scored[:k]


class FakeLLM:
    def __init__(self):
        self.answer = "Токен — это кусочек текста [L1]."
        self.fail_after: int | None = None
        self.messages = None

    async def health(self):
        return "ready"

    async def stream(self, messages):
        self.messages = messages
        for i, tok in enumerate(re.findall(r"\S+\s*", self.answer)):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("Connection error (test)")
            yield "token", tok
        yield "usage", {"prompt_tokens": 100, "completion_tokens": 10}


class FakeWebSearcher:
    """Подмена MCP-поиска: mode = ok | empty | slow | fail."""

    def __init__(self):
        self.mode = "ok"
        self.queries: list[str] = []
        self.results = [
            {"title": "Токенизация — Википедия", "url": "https://ru.wikipedia.org/wiki/Токенизация",
             "content": "Токен — минимальная единица текста для модели."},
            {"title": "Tokenizers docs", "url": "https://huggingface.co/docs/tokenizers",
             "content": "Tokenizers split text into tokens."},
        ]

    async def search(self, query):
        self.queries.append(query)
        if self.mode == "slow":
            await asyncio.sleep(0.05)
            return {"query": query, "status": "timeout", "results": [], "t_ms": 10000,
                    "error": "MCP-поиск не уложился в 10 с", "tool": "tavily_search"}
        if self.mode == "fail":
            return {"query": query, "status": "error", "results": [], "t_ms": 12,
                    "error": "ConnectError: All connection attempts failed", "tool": None}
        if self.mode == "empty":
            return {"query": query, "status": "empty", "results": [], "t_ms": 300, "error": None,
                    "tool": "tavily_search"}
        res = [{"label": f"W{n}", "domain": r["url"].split("/")[2], **r} for n, r in enumerate(self.results, 1)]
        return {"query": query, "status": "ok", "results": res, "t_ms": 800, "error": None, "tool": "tavily_search"}


@pytest.fixture
def fakes():
    return FakeEmbedder(), FakeStore(), FakeLLM()


@pytest.fixture
def fake_web():
    return FakeWebSearcher()


@pytest.fixture
def make_client(tmp_path, fakes, fake_web):
    """make_client(**settings) -> TestClient; повторный вызов с тем же tmp_path имитирует рестарт."""
    opened = []

    @contextmanager
    def _make(**overrides):
        emb, store, llm = fakes
        params = dict(jwt_secret="test-secret", data_dir=tmp_path / "data", lecturer_logins="lect", seed_file=None)
        params.update(overrides)
        settings = Settings(**params)
        comps = Components(embedder=emb, store=store, llm=llm, web=fake_web, load_embedder_in_background=False)
        with TestClient(create_app(settings, comps)) as c:
            opened.append(c)
            yield c

    return _make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def register(client: TestClient, login: str, password: str = "secret123"):
    return client.post("/api/auth/register", json={"login": login, "password": password})


def login_as(client: TestClient, login: str, password: str = "secret123"):
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    if r.status_code == 401:
        r = register(client, login, password)
    assert r.status_code == 200, r.text
    return r.json()


def upload(client: TestClient, name: str, content: bytes, title: str | None = None):
    data = {"titles": [title]} if title else None
    return client.post("/api/documents", files=[("files", (name, content, "text/plain"))], data=data)


def wait_indexed(client: TestClient, timeout: float = 10) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        docs = client.get("/api/documents").json()
        if all(d["status"] != "indexing" for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError("индексация не завершилась")


def parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.strip().split("\n\n"):
        ev, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


LECTURE = (
    "ГЛАВА 01 · Токены\n\n"
    "Токен — это кусочек текста, с которым работает языковая модель. "
    "Модель видит текст как последовательность токенов.\n\n"
    "ГЛАВА 02 · Трансформер\n\n"
    "Трансформер использует механизм внимания. Внимание позволяет учитывать контекст.\n"
).encode("utf-8")
