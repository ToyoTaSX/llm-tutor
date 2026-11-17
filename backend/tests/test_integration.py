"""Интеграционные тесты на живых Qdrant и BGE-M3 (запускаются в контейнере backend)."""
import os
import random
from pathlib import Path

import pytest

from app.rag.embedder import SparseVec

QDRANT_URL = os.environ.get("QDRANT_URL")
MODEL_DIR = Path(os.environ.get("MODELS_PATH", "/models")) / os.environ.get("EMB_MODEL_DIR", "bge-m3")


@pytest.fixture
def store():
    if not QDRANT_URL:
        pytest.skip("QDRANT_URL не задан")
    from app.rag.store import QdrantStore

    s = QdrantStore(QDRANT_URL, "test_lectures")
    if not s.ping():
        pytest.skip("Qdrant недоступен")
    if s.client.collection_exists("test_lectures"):
        s.client.delete_collection("test_lectures")
    s.ensure_collection()
    yield s
    s.client.delete_collection("test_lectures")


def _vec(seed):
    rnd = random.Random(seed)
    return [rnd.random() for _ in range(1024)]


def test_store_filter_and_delete(store):
    for doc_id in (1, 2):
        texts = [f"doc{doc_id} chunk{i}" for i in range(3)]
        dense = [_vec(f"{doc_id}-{i}") for i in range(3)]
        sparse = [SparseVec([doc_id * 10 + i], [1.0]) for i in range(3)]
        store.upsert_chunks(doc_id, f"Doc {doc_id}", 0, texts, dense, sparse)
    assert store.count_by_doc(1) == 3
    res = store.search(_vec("2-0"), SparseVec([20], [1.0]), ready_ids=[1], k=6, candidates=20, rrf_k=60)
    assert res and all(r["doc_id"] == 1 for r in res)
    res = store.search(_vec("2-0"), SparseVec([20], [1.0]), ready_ids=[1, 2], k=1, candidates=20, rrf_k=60)
    assert res[0]["text"] == "doc2 chunk0"
    store.delete_by_doc(1)
    assert store.count_by_doc(1) == 0 and store.count_by_doc(2) == 3


def test_embedder_dims():
    if not (MODEL_DIR / "config.json").exists():
        pytest.skip("модель BGE-M3 недоступна")
    import torch

    from app.rag.embedder import BgeM3Embedder

    emb = BgeM3Embedder(MODEL_DIR, "cuda" if torch.cuda.is_available() else "cpu")
    emb.load()
    assert emb.error is None
    dense, sparse = emb.encode(["Что такое токен?"])
    assert len(dense[0]) == 1024 and len(sparse[0].indices) > 0
