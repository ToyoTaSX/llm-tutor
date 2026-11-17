# -*- coding: utf-8 -*-
"""Прогон контрольного набора вопросов в нескольких режимах.
Запуск:  python eval.py                      # режимы norag и hybrid
         python eval.py --modes norag dense sparse hybrid
Результат: results_<время>.csv (открывается в Excel). Колонку correct
заполняете вручную: 1 — верно, 0 — неверно, 0.5 — частично.
"""
import argparse
import csv
import statistics
import time

import rag_core as R

p = argparse.ArgumentParser()
p.add_argument("--questions", default="questions.csv")
p.add_argument("--modes", nargs="+", default=["norag", "hybrid"])
a = p.parse_args()

def read_questions(path):
    """Читает CSV в любой из типичных форм, в которых его сохраняет Excel:
    UTF-8 с BOM или Windows-1251; разделитель «;» или «,»."""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0]
    delim = ";" if first.count(";") >= first.count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    need = {"id", "type", "question", "reference"}
    if not rows or not need <= set(rows[0].keys()):
        raise SystemExit(f"В {path} нужны колонки: id; type; question; reference. "
                         f"Найдены: {list(rows[0].keys()) if rows else 'ничего'}")
    return [r for r in rows if r["question"] and r["question"].strip()]


questions = read_questions(a.questions)

out_name = f"results_{time.strftime('%Y%m%d_%H%M%S')}.csv"
rows, lat = [], {m: [] for m in a.modes}
for q in questions:
    for mode in a.modes:
        r = R.answer(q["question"], mode)
        lat[mode].append(r["t_search"] + r["t_llm"])
        rows.append({
            "id": q["id"], "type": q["type"], "mode": mode,
            "question": q["question"], "reference": q["reference"],
            "answer": r["answer"],
            "sources": ",".join(str(c["chunk_no"]) for c in r["chunks"]),
            "t_total": f"{r['t_search'] + r['t_llm']:.2f}",
            "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
            "correct": "",
        })
        print(f"[{q['id']}/{mode}] {r['answer'][:90]!r}")

with open(out_name, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
    w.writeheader()
    w.writerows(rows)

print(f"\nСохранено: {out_name}")
for m, v in lat.items():
    print(f"{m:7s}: среднее время {statistics.mean(v):.2f} с, максимум {max(v):.2f} с")
