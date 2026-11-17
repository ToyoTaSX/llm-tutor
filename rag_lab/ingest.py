# -*- coding: utf-8 -*-
"""Индексация корпуса: чтение -> нарезка -> эмбеддинги BGE-M3 -> Qdrant.
Запуск:  python ingest.py
"""
import re
import time

from qdrant_client import models

import config as C
import rag_core as R


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise SystemExit("Не удалось определить кодировку файла (ожидается UTF-8 или CP1251)")


def split_chunks(text):
    """Режем текст на предложения и собираем из них фрагменты не длиннее CHUNK_CHARS.
    Соседние фрагменты перекрываются на ~OVERLAP_CHARS (целыми предложениями).
    Главы не смешиваем: фрагмент не переходит через заголовок «ГЛАВА NN»."""
    sentences = split_sentences(text)
    chunks, cur, size = [], [], 0
    for s in sentences:
        new_chapter = s.startswith("ГЛАВА ")
        if cur and (new_chapter or size + len(s) + 1 > C.CHUNK_CHARS):
            chunks.append(" ".join(cur))
            if new_chapter:
                cur, size = [], 0
            else:                              # хвост предыдущего фрагмента для перекрытия
                tail, tsize = [], 0
                for x in reversed(cur):
                    if tsize + len(x) > C.OVERLAP_CHARS:
                        break
                    tail.insert(0, x)
                    tsize += len(x) + 1
                cur, size = tail, tsize
        cur.append(s)
        size += len(s) + 1
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def split_sentences(text):
    """Делит текст на предложения; слишком длинные предложения режет по словам."""
    out = []
    for para in text.splitlines():
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        # конец предложения: . ! ? … (и закрывающая кавычка/скобка), затем пробел и заглавная буква, тире или «
        raw = re.split(r"(?:(?<=[.!?…])|(?<=[.!?…][»)]))\s+(?=[А-ЯЁA-Z0-9—«(])", para)
        parts = []
        for p in raw:                          # не рвём после сокращений: «г.», «Г.», «губ.», «дес.»
            if parts and re.search(r"(?:^|[\s(])[А-ЯЁа-яё]{1,3}\.$", parts[-1]):
                parts[-1] += " " + p
            else:
                parts.append(p)
        for p in parts:
            while len(p) > C.CHUNK_CHARS:      # аварийная нарезка очень длинных предложений
                cut = p.rfind(" ", 0, C.CHUNK_CHARS)
                cut = cut if cut > 0 else C.CHUNK_CHARS
                out.append(p[:cut])
                p = p[cut:].strip()
            if p:
                out.append(p)
    return out


def main():
    t0 = time.perf_counter()
    text = read_text(C.CORPUS_FILE)
    chunks = split_chunks(text)
    print(f"Символов в корпусе: {len(text):,}; фрагментов: {len(chunks)}")

    client = R.db()
    if client.collection_exists(C.COLLECTION):
        client.delete_collection(C.COLLECTION)
    client.create_collection(
        C.COLLECTION,
        vectors_config={"dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
    )

    step = 64
    for start in range(0, len(chunks), step):
        part = chunks[start:start + step]
        dense, sparse = R.encode(part)
        points = [
            models.PointStruct(
                id=start + i,
                vector={"dense": dense[i], "sparse": sparse[i]},
                payload={"text": part[i], "chunk_no": start + i},
            )
            for i in range(len(part))
        ]
        client.upsert(C.COLLECTION, points=points)
        print(f"  проиндексировано {min(start + step, len(chunks))}/{len(chunks)}")

    print(f"Готово за {time.perf_counter() - t0:.1f} с")


if __name__ == "__main__":
    main()
