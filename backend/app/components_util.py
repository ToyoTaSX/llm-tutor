"""Мелкие общие функции разбора ответа."""
import re

# [L1], [W2], [L1, L2], [L1; W3], [L1, 2] (буква наследуется) — как во frontend.
# Qwen2.5-3B иногда пишет кириллическую «Л» вместо L ([Л1]) — принимаем её как L.
_CITE_RE = re.compile(r"\[\s*([LWЛ]\d+(?:\s*[,;]\s*[LWЛ]?\d+)*)\s*\]", re.I)


def cited_labels(answer: str) -> set[str]:
    """Метки источников, на которые ссылается ответ: {"L1", "W2", …}."""
    out: set[str] = set()
    for m in _CITE_RE.finditer(answer or ""):
        prefix = "L"
        for part in re.split(r"[,;]", m.group(1)):
            part = part.strip().upper().replace("Л", "L")
            if part[0] in "LW":
                prefix, num = part[0], part[1:]
            else:
                num = part
            out.add(f"{prefix}{int(num)}")
    return out
