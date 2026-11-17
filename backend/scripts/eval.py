"""Прогон контрольного набора вопросов через тот же конвейер, что и приложение (spec quality-eval, design D11).

Запуск (из корня проекта, при работающем docker compose):
    docker compose exec backend python scripts/eval.py --mode course
    docker compose exec backend python scripts/eval.py --mode web --questions scripts/questions_web.csv
    docker compose exec backend python scripts/eval.py --summarize /data/eval/results_web_….csv /data/eval/results_course_….csv
    docker compose cp backend:/data/eval ./eval_results

Результат: CSV (UTF-8 с BOM, разделитель «;», открывается в Excel) и сводка в консоли.
Вопросы прогоняются строго последовательно: живой веб-поиск нагрузочным тестом не нагружаем.
Колонки разметки заполняете вручную:
    correct     — 1 верно, 0.5 частично, 0 неверно (как в лабораторной 4);
    citation_ok — 1, если указанные источники существуют и подтверждают утверждения, иначе 0;
    abstained   — для вопросов trap: 1, если ассистент воздержался от выдуманного ответа.
Формат вопросов: id; type; question; reference [; allowed_sources; checked_at].
"""
import argparse
import asyncio
import csv
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIELDS = [
    "id", "type", "question", "reference", "allowed_sources", "checked_at", "mode", "answer",
    "lecture_sources", "cited", "web_status", "web_urls", "t_mcp", "t_search", "t_llm", "t_total", "no_answer",
    "correct", "citation_ok", "abstained",
]


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("Не удалось определить кодировку CSV (нужна UTF-8 или Windows-1251)")


def read_csv(path: Path) -> list[dict]:
    text = _decode(path.read_bytes())
    first = text.splitlines()[0]
    delim = ";" if first.count(";") >= first.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delim))


def read_questions(path: Path) -> list[dict]:
    rows = read_csv(path)
    need = {"id", "type", "question", "reference"}
    if not rows or not need <= set(rows[0]):
        raise SystemExit(f"В {path} нужны колонки: id; type; question; reference [; allowed_sources; checked_at]")
    return [r for r in rows if (r.get("question") or "").strip()]


# ---------- сводка ----------

def _num(v) -> float | None:
    v = (v or "").strip().replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _mean(xs: list[float]) -> float | None:
    return statistics.mean(xs) if xs else None


def summarize_rows(rows: list[dict]) -> dict:
    """Строка сравнительной таблицы ЛР7 по одному файлу результатов."""
    def acc(rs):
        return _mean([c for c in (_num(r.get("correct")) for r in rs) if c is not None])

    traps = [r for r in rows if r.get("type") == "trap"]
    cit = [c for c in (_num(r.get("citation_ok")) for r in rows) if c is not None]
    mcp = [t for t in (_num(r.get("t_mcp")) for r in rows) if t is not None]
    return {
        "mode": (rows[0].get("mode") if rows else "") or "",
        "n": len(rows),
        "acc_all": acc(rows),
        "acc_course": acc([r for r in rows if r.get("type") == "course"]),
        "acc_web": acc([r for r in rows if r.get("type") == "web"]),
        "traps_passed": sum(1 for r in traps if _num(r.get("abstained")) == 1),
        "traps_total": len(traps),
        "citation_ok_share": _mean(cit),
        "avg_t_mcp": _mean(mcp),
        "avg_t_total": _mean([t for t in (_num(r.get("t_total")) for r in rows) if t is not None]),
        "mcp_statuses": dict(Counter(r.get("web_status") for r in rows if r.get("web_status"))),
    }


def _fmt(v, kind="f") -> str:
    if v is None:
        return "—"
    return f"{v:.0%}" if kind == "%" else f"{v:.2f}"


def print_summary(paths: list[Path]) -> None:
    print("| Конфигурация | Точность всего | Точность course | Точность web | Ловушки пройдены | "
          "Доля citation_ok = 1 | Среднее время MCP, с | Среднее полное время, с |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for p in paths:
        s = summarize_rows(read_csv(p))
        name = {"course": "Только курс", "web": "Курс + интернет"}.get(s["mode"], s["mode"] or p.name)
        print(f"| {name} | {_fmt(s['acc_all'])} | {_fmt(s['acc_course'])} | {_fmt(s['acc_web'])} | "
              f"{s['traps_passed']}/{s['traps_total']} | {_fmt(s['citation_ok_share'], '%')} | "
              f"{_fmt(s['avg_t_mcp']) if s['mode'] == 'web' else '—'} | {_fmt(s['avg_t_total'])} |")
    for p in paths:
        s = summarize_rows(read_csv(p))
        if s["mcp_statuses"]:
            print(f"{p.name}: статусы MCP {s['mcp_statuses']}")


# ---------- прогон ----------

async def run(questions: Path, mode: str, out_dir: Path) -> Path:
    from sqlalchemy import select

    from app.components_util import cited_labels
    from app.config import load_settings
    from app.db import make_sessionmaker
    from app.models import Document
    from app.rag.embedder import BgeM3Embedder
    from app.rag.engine import RagEngine
    from app.rag.llm import LlamaClient
    from app.rag.mcp_search import WebSearcher, install_secret_mask
    from app.rag.prompt import is_no_answer
    from app.rag.store import QdrantStore

    s = load_settings()
    install_secret_mask(s.mcp_api_key)
    sm = make_sessionmaker(s.data_dir / "app.db")
    with sm() as db:
        ready_ids = list(db.scalars(select(Document.id).where(Document.status == "ready")))
    if not ready_ids:
        raise SystemExit("Нет проиндексированных документов")

    emb = BgeM3Embedder(s.emb_model_path, s.emb_device, s.emb_batch)
    emb.load()
    if emb.error:
        raise SystemExit(emb.error)
    engine = RagEngine(s, emb, QdrantStore(s.qdrant_url, s.collection),
                       LlamaClient(s.llm_url, s.temperature, s.max_tokens), WebSearcher.from_settings(s))

    rows = []
    for q in read_questions(questions):  # строго последовательно
        chunks, web, parts, tm = [], None, [], {}
        async for kind, val in engine.answer_events(q["question"], ready_ids, mode):
            if kind == "sources":
                chunks = val["chunks"]
            elif kind == "web_sources":
                web = val
            elif kind == "token":
                parts.append(val)
            elif kind == "timings":
                tm = val
        answer = "".join(parts).strip()
        known = {f"L{n}" for n in range(1, len(chunks) + 1)} | {r["label"] for r in (web or {}).get("results", [])}
        cited = sorted(cited_labels(answer) & known, key=lambda x: (x[0], int(x[1:])))
        sec = lambda ms: "" if ms is None else f"{ms / 1000:.2f}"  # noqa: E731
        rows.append({
            "id": q["id"], "type": q["type"], "question": q["question"], "reference": q["reference"],
            "allowed_sources": q.get("allowed_sources", ""), "checked_at": q.get("checked_at", ""),
            "mode": mode, "answer": answer,
            "lecture_sources": ", ".join(f"[L{n}] {c['doc_title']}#{c['chunk_no']}" for n, c in enumerate(chunks, 1)),
            "cited": ",".join(cited),
            "web_status": (web or {}).get("status", ""),
            "web_urls": " ".join(f"[{r['label']}] {r['url']}" for r in (web or {}).get("results", [])),
            "t_mcp": sec(tm.get("t_mcp_ms")), "t_search": sec(tm.get("t_search_ms")),
            "t_llm": sec(tm.get("t_llm_ms")), "t_total": sec(tm.get("t_total_ms")),
            "no_answer": int(mode == "course" and is_no_answer(answer)),
            "correct": "", "citation_ok": "", "abstained": "",
        })
        print(f"[{q['id']}/{q['type']}] web={rows[-1]['web_status'] or '-'} cited={cited or '-'} "
              f"t={rows[-1]['t_total']}s {answer[:90]!r}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"results_{mode}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    s_ = summarize_rows(rows)
    print(f"\nСохранено: {out}")
    print(f"режим: {mode}; вопросов: {len(rows)}; со ссылками: {sum(1 for r in rows if r['cited'])}; "
          f"«тема не разбиралась»: {sum(r['no_answer'] for r in rows)}; среднее полное время: "
          f"{_fmt(s_['avg_t_total'])} с; среднее MCP: {_fmt(s_['avg_t_mcp'])} с; статусы MCP: {s_['mcp_statuses'] or '—'}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Прогон контрольного набора и сводка по размеченным результатам")
    p.add_argument("--questions", default=str(Path(__file__).with_name("questions.csv")))
    p.add_argument("--mode", choices=["course", "web"], default="course")
    p.add_argument("--out", default="/data/eval")
    p.add_argument("--summarize", nargs="+", metavar="CSV", help="посчитать строку таблицы по размеченным CSV")
    a = p.parse_args()
    if a.summarize:
        print_summary([Path(x) for x in a.summarize])
        return
    asyncio.run(run(Path(a.questions), a.mode, Path(a.out)))


if __name__ == "__main__":
    main()
