# -*- coding: utf-8 -*-
"""Вопросы к системе. Три способа задать вопрос:

  python ask.py --id 1                 # вопрос №1 из questions.csv (с эталоном)
  python ask.py                        # диалог: вводите вопросы по одному, пустая строка — выход
  python ask.py "Когда Чехов прибыл в Николаевск?"

Ключи:
  --mode norag | dense | sparse | hybrid (по умолчанию hybrid)
  --show        печатать найденные фрагменты целиком

Почему не всегда вопрос в командной строке: старая версия PowerShell
при вставке (Ctrl+V) теряет заглавные русские буквы. В диалоговом режиме
и с --id этой проблемы нет.
"""
import argparse
import csv

import rag_core as R

p = argparse.ArgumentParser()
p.add_argument("question", nargs="?", help="текст вопроса (необязательно)")
p.add_argument("--id", help="номер вопроса из questions.csv")
p.add_argument("--mode", default="hybrid", choices=["norag", "dense", "sparse", "hybrid"])
p.add_argument("--show", action="store_true", help="печатать текст найденных фрагментов")
a = p.parse_args()


def question_by_id(qid):
    raw = open("questions.csv", "rb").read()
    text = None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    first = text.splitlines()[0]
    delim = ";" if first.count(";") >= first.count(",") else ","
    for row in csv.DictReader(text.splitlines(), delimiter=delim):
        if (row.get("id") or "").strip() == str(qid).strip():
            return row["question"], row.get("reference", "")
    raise SystemExit(f"В questions.csv нет вопроса с id = {qid}")


def show(question, reference=None):
    r = R.answer(question, a.mode)
    print(f"\n=== ВОПРОС ({a.mode}) ===\n{question}")
    if reference:
        print(f"\n=== ЭТАЛОН ===\n{reference}")
    print("\n=== ОТВЕТ ===")
    print(r["answer"])
    if r["chunks"]:
        print("\n=== ИСТОЧНИКИ ===")
        for n, c in enumerate(r["chunks"], 1):
            head = c["text"][:150] + ("…" if len(c["text"]) > 150 else "")
            print(f"[{n}] фрагмент №{c['chunk_no']} (score {c['score']:.4f}): "
                  + (c["text"] if a.show else head))
    print(f"\nпоиск {r['t_search']:.2f} с | LLM {r['t_llm']:.2f} с | "
          f"токены: промпт {r['prompt_tokens']}, ответ {r['completion_tokens']}")


if a.id:
    show(*question_by_id(a.id))
elif a.question:
    show(a.question)
else:
    print(f"Режим: {a.mode}. Введите вопрос и нажмите Enter. Пустая строка — выход.")
    while True:
        try:
            q = input("\nВопрос: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        show(q)
