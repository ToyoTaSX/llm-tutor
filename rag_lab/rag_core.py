# -*- coding: utf-8 -*-
"""Ядро RAG-конвейера: эмбеддинги, поиск, сборка промпта, вызов LLM."""
import atexit
import time

from qdrant_client import QdrantClient, models
from openai import OpenAI

import config as C

_embedder = None
_db = None
_llm = None


# ---------- Эмбеддер BGE-M3: плотные + разреженные векторы ----------
def model_path():
    """Локальная папка с моделью эмбеддера. Если модель уже скачана — берём её
    с диска без обращения к интернету; иначе качаем один раз, без ненужной
    ONNX-версии (экономит ~2,3 ГБ)."""
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(C.EMB_MODEL, local_files_only=True)
    except Exception:
        print(f"Скачиваю эмбеддер {C.EMB_MODEL} (один раз, ~2,3 ГБ)…")
        return snapshot_download(C.EMB_MODEL, ignore_patterns=["onnx/*", "*.onnx", "*.onnx_data", "imgs/*"])


def embedder():
    global _embedder
    if _embedder is None:
        from FlagEmbedding import BGEM3FlagModel
        use_fp16 = C.EMB_DEVICE == "cuda"
        path = model_path()
        try:
            _embedder = BGEM3FlagModel(path, use_fp16=use_fp16, devices=[C.EMB_DEVICE])
        except TypeError:  # старые версии FlagEmbedding без параметра devices
            _embedder = BGEM3FlagModel(path, use_fp16=use_fp16)
    return _embedder


def encode(texts, max_length=512):
    """Возвращает (список плотных векторов, список разреженных векторов Qdrant)."""
    out = embedder().encode(
        texts,
        batch_size=C.EMB_BATCH,
        max_length=max_length,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = [v.tolist() for v in out["dense_vecs"]]
    sparse = [
        models.SparseVector(
            indices=[int(k) for k in w.keys()],
            values=[float(x) for x in w.values()],
        )
        for w in out["lexical_weights"]
    ]
    return dense, sparse


# ---------- База ----------
def db():
    global _db
    if _db is None:
        _db = QdrantClient(path=C.DB_PATH)
        atexit.register(close_db)   # закрыть базу аккуратно до остановки Python
    return _db


def close_db():
    global _db
    if _db is not None:
        try:
            _db.close()
        except Exception:
            pass
        _db = None


# ---------- Поиск ----------
def search(query, mode="hybrid", k=None):
    """mode: dense | sparse | hybrid. Гибрид = слияние рангов (RRF) двух списков."""
    k = k or C.TOP_K
    dense, sparse = encode([query], max_length=256)
    lists = []
    if mode in ("dense", "hybrid"):
        lists.append(db().query_points(C.COLLECTION, query=dense[0], using="dense",
                                       limit=C.CANDIDATES, with_payload=True).points)
    if mode in ("sparse", "hybrid"):
        lists.append(db().query_points(C.COLLECTION, query=sparse[0], using="sparse",
                                       limit=C.CANDIDATES, with_payload=True).points)

    scores, payloads = {}, {}
    for lst in lists:
        for rank, p in enumerate(lst):
            scores[p.id] = scores.get(p.id, 0.0) + 1.0 / (C.RRF_K + rank + 1)
            payloads[p.id] = p.payload
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    return [{"id": i, "score": scores[i], **payloads[i]} for i in top]


# ---------- Промпт ----------
def build_messages(question, chunks):
    if chunks is None:  # режим без RAG
        return [{"role": "system", "content": C.SYSTEM_PROMPT_NORAG},
                {"role": "user", "content": question}]
    context = "\n\n".join(f"[{n}] {c['text']}" for n, c in enumerate(chunks, 1))
    user = f"Фрагменты:\n{context}\n\nВопрос: {question}"
    return [{"role": "system", "content": C.SYSTEM_PROMPT},
            {"role": "user", "content": user}]


# ---------- LLM ----------
def llm():
    global _llm
    if _llm is None:
        _llm = OpenAI(base_url=C.LLM_URL, api_key="no-key")
    return _llm


def answer(question, mode="hybrid"):
    """mode: norag | dense | sparse | hybrid. Возвращает словарь с ответом и замерами.
    Загрузка эмбеддера и базы (один раз на запуск скрипта) в замер поиска не входит."""
    if mode != "norag":
        embedder()
        db()
    t0 = time.perf_counter()
    chunks = None if mode == "norag" else search(question, mode)
    t1 = time.perf_counter()
    try:
        resp = llm().chat.completions.create(
            model=C.LLM_MODEL,
            messages=build_messages(question, chunks),
            temperature=C.TEMPERATURE,
            max_tokens=C.MAX_TOKENS,
        )
    except Exception as e:
        if "context" in str(e).lower():
            raise SystemExit(
                "Промпт не помещается в контекст слота сервера.\n"
                f"Подробности: {e}\n"
                "Что сделать: уменьшить TOP_K или CHUNK_CHARS в config.py (и заново выполнить ingest.py), "
                "либо увеличить контекст сервера ключом -c.")
        if "connect" in str(e).lower():
            raise SystemExit("Нет связи с сервером llama.cpp: запущен ли он в первом окне (шаг 4)?")
        raise
    t2 = time.perf_counter()
    usage = resp.usage
    return {
        "answer": resp.choices[0].message.content.strip(),
        "chunks": chunks or [],
        "t_search": t1 - t0,
        "t_llm": t2 - t1,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }
