import ast
import re
import types
from pathlib import Path

import pytest

from app.rag.chunker import DecodeError, decode_text, split_chunks

ROOT = Path(__file__).resolve().parents[2]
COURSE_CANDIDATES = [ROOT / "rag_lab" / "data" / "course.txt", Path("/seed/course.txt")]


def test_heading_not_crossed():
    text = ("Первое предложение главы один. " * 10) + "\n\nГЛАВА 02 · Вторая\n\n" + ("Текст второй главы. " * 10)
    chunks = split_chunks(text, 1000, 200)
    for c in chunks:
        assert not ("главы один" in c and "второй главы" in c)
    assert any(c.startswith("ГЛАВА 02") for c in chunks)


def test_short_heading_line_starts_chunk():
    text = "Длинный абзац про сети. Ещё одно предложение.\n\nАрхитектура трансформера\n\nВнимание — это механизм."
    chunks = split_chunks(text, 1000, 200)
    assert chunks[-1].startswith("Архитектура трансформера")


def test_no_heading_only_chunks():
    text = "Текст. " * 5 + "\n\nГЛАВА 06 · Сессия 6 · Квантизация\n\nЧто такое квантизация\n\nКвантизация сжимает веса."
    chunks = split_chunks(text, 1000, 200)
    assert chunks[-1] == "ГЛАВА 06 · Сессия 6 · Квантизация Что такое квантизация Квантизация сжимает веса."


def test_course_has_no_heading_only_chunks():
    course = next((p for p in COURSE_CANDIDATES if p.exists()), None)
    if course is None:
        pytest.skip("course.txt недоступен")
    for c in split_chunks(decode_text(course.read_bytes()), 1000, 200):
        assert not (c.startswith("ГЛАВА") and len(c) < 120), c


def test_long_sentence_is_split():
    text = "слово " * 1000
    chunks = split_chunks(text, 300, 50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_overlap_between_chunks():
    sentences = [f"Предложение номер {i} про нейросети." for i in range(60)]
    chunks = split_chunks(" ".join(sentences), 300, 80)
    assert len(chunks) > 2
    assert all(len(c) <= 300 for c in chunks)
    first_tail = chunks[0].split(". ")[-1]
    assert first_tail.rstrip(".") in chunks[1]


def test_decode_cp1251_and_utf8():
    s = "Токен — это кусочек текста"
    assert decode_text(s.encode("cp1251")) == s
    assert decode_text(("﻿" + s).encode("utf-8")) == s
    with pytest.raises(DecodeError):
        decode_text(b"\x00\x01\x02binary")


def _lab_split_chunks():
    """Алгоритм нарезки из rag_lab/ingest.py — для сравнения."""
    src_path = ROOT / "rag_lab" / "ingest.py"
    if not src_path.exists():
        return None
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("split_chunks", "split_sentences")]
    ns = {"re": re, "C": types.SimpleNamespace(CHUNK_CHARS=1000, OVERLAP_CHARS=200)}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "ingest", "exec"), ns)
    return ns["split_chunks"]


def test_course_close_to_lab():
    course = next((p for p in COURSE_CANDIDATES if p.exists()), None)
    if course is None:
        pytest.skip("course.txt недоступен")
    text = decode_text(course.read_bytes())
    ours = split_chunks(text, 1000, 200)
    assert all(len(c) <= 1000 for c in ours)
    lab = _lab_split_chunks()
    if lab is None:
        pytest.skip("rag_lab/ingest.py недоступен")
    expected = len(lab(text))
    assert abs(len(ours) - expected) <= expected * 0.25, (len(ours), expected)
