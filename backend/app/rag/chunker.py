"""Декодирование и нарезка текста лекций на фрагменты.

Основано на rag_lab/ingest.py. Граница главы обобщена (design D11): новый фрагмент
начинается на строке-заголовке («ГЛАВА 02 ·…», «Лекция 3», «# …») или на короткой
строке без точки в конце, за которой идёт пустая строка.
"""
import re

HEADING_RE = re.compile(r"^(?:ГЛАВА|Глава|ЛЕКЦИЯ|Лекция|РАЗДЕЛ|Раздел|ТЕМА|Тема|#{1,6})\s")
SENT_SPLIT_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][»)]))\s+(?=[А-ЯЁA-Z0-9—«(])")
ABBR_END_RE = re.compile(r"(?:^|[\s(])[А-ЯЁа-яё]{1,3}\.$")
MAX_HEADING_LEN = 80


class DecodeError(ValueError):
    pass


def decode_text(raw: bytes) -> str:
    """UTF-8 (с BOM или без) или Windows-1251. Иначе — DecodeError."""
    if b"\x00" in raw:
        raise DecodeError("Файл похож на двоичный, а не на текст")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        bad = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t\f")
        if bad <= max(3, len(text) // 1000):
            return text.replace("\r\n", "\n").replace("\r", "\n")
    raise DecodeError("Не удалось определить кодировку (ожидается UTF-8 или Windows-1251)")


def _is_heading(line: str, next_blank: bool) -> bool:
    if HEADING_RE.match(line):
        return True
    return (
        next_blank
        and len(line) < MAX_HEADING_LEN
        and line[-1] not in ".!?…:;,"
        and any(ch.isalpha() for ch in line)
    )


def split_sentences(text: str, max_chars: int) -> list[tuple[str, bool]]:
    """Список (предложение, это_заголовок). Слишком длинные предложения режутся по словам."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    out: list[tuple[str, bool]] = []
    for i, para in enumerate(lines):
        if not para:
            continue
        next_blank = i + 1 >= len(lines) or not lines[i + 1]
        if _is_heading(para, next_blank):
            for piece in _hard_split(para, max_chars):
                out.append((piece, True))
            continue
        parts: list[str] = []
        for p in SENT_SPLIT_RE.split(para):  # не рвём после сокращений: «г.», «т.», «рис.»
            if parts and ABBR_END_RE.search(parts[-1]):
                parts[-1] += " " + p
            else:
                parts.append(p)
        for p in parts:
            out.extend((piece, False) for piece in _hard_split(p, max_chars))
    return out


def _hard_split(s: str, max_chars: int) -> list[str]:
    res = []
    while len(s) > max_chars:
        cut = s.rfind(" ", 0, max_chars)
        cut = cut if cut > 0 else max_chars
        res.append(s[:cut].strip())
        s = s[cut:].strip()
    if s:
        res.append(s)
    return res


def split_chunks(text: str, chunk_chars: int = 1000, overlap_chars: int = 200) -> list[str]:
    """Фрагменты не длиннее chunk_chars, соседние перекрываются ~overlap_chars целыми
    предложениями; заголовок всегда начинает новый фрагмент без перекрытия."""
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    only_headings = False  # в cur пока только заголовки: «ГЛАВА 06 …» + подзаголовок не режем
    for s, heading in split_sentences(text, chunk_chars):
        if heading and only_headings and size + len(s) + 1 <= chunk_chars:
            cur.append(s)
            size += len(s) + 1
            continue
        if cur and (heading or size + len(s) + 1 > chunk_chars):
            chunks.append(" ".join(cur))
            if heading:
                cur, size = [], 0
            else:
                tail: list[str] = []
                tsize = 0
                for x in reversed(cur):
                    if tsize + len(x) + 1 > overlap_chars or tsize + len(x) + len(s) + 2 > chunk_chars:
                        break
                    tail.insert(0, x)
                    tsize += len(x) + 1
                cur, size = tail, tsize
        only_headings = heading and not cur
        cur.append(s)
        size += len(s) + 1
    if cur:
        chunks.append(" ".join(cur))
    return chunks
