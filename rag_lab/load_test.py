# -*- coding: utf-8 -*-
"""Нагрузочный тест LLM-сервера: N одновременных «студентов».

Поиск выполняется один раз, дальше все пользователи шлют промпт с найденными
фрагментами — так мы меряем именно LLM-сервер. Чтобы замер был честным:
  * кэш промпта на сервере отключён (cache_prompt = false) — иначе одинаковый
    промпт «читается» мгновенно, а у настоящих студентов вопросы разные;
  * длина ответа фиксирована (--gen токенов, ignore_eos) — иначе скорость
    зависит от того, насколько многословной оказалась модель.

Запуск:  python load_test.py --users 1 2 4 8 --rounds 3
"""
import argparse
import asyncio
import statistics
import time

from openai import AsyncOpenAI

import config as C
import rag_core as R

p = argparse.ArgumentParser()
p.add_argument("--users", nargs="+", type=int, default=[1, 2, 4, 8])
p.add_argument("--rounds", type=int, default=3, help="запросов на одного пользователя")
p.add_argument("--gen", type=int, default=150, help="длина ответа в токенах")
p.add_argument("--question", default="Как Чехов добирался до Сахалина и что увидел в Николаевске?")
a = p.parse_args()

messages = R.build_messages(a.question, R.search(a.question, "hybrid"))
client = AsyncOpenAI(base_url=C.LLM_URL, api_key="no-key")


async def one_request():
    t0 = time.perf_counter()
    ttft, n_chunks, tokens, prompt_tokens = None, 0, None, None
    stream = await client.chat.completions.create(
        model=C.LLM_MODEL, messages=messages, temperature=C.TEMPERATURE,
        max_tokens=a.gen, stream=True, stream_options={"include_usage": True},
        extra_body={"cache_prompt": False, "ignore_eos": True},
    )
    async for ev in stream:
        if ev.choices and ev.choices[0].delta.content:
            if ttft is None:
                ttft = time.perf_counter() - t0
            n_chunks += 1
        if getattr(ev, "usage", None):
            tokens = ev.usage.completion_tokens
            prompt_tokens = ev.usage.prompt_tokens
    total = time.perf_counter() - t0
    return ttft or total, total, tokens or n_chunks, prompt_tokens


async def user(rounds):
    return [await one_request() for _ in range(rounds)]


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


async def main():
    first = await one_request()  # прогрев
    print(f"Промпт: {first[3]} токенов, ответ: {a.gen} токенов, запросов на пользователя: {a.rounds}\n")
    print(f"{'польз.':>6} | {'TTFT p50':>8} {'p95':>6} | {'время p50':>9} {'p95':>6} | "
          f"{'ток/с на польз.':>15} | {'ток/с всего':>11}")
    for n in a.users:
        t0 = time.perf_counter()
        res = await asyncio.gather(*[user(a.rounds) for _ in range(n)])
        wall = time.perf_counter() - t0
        flat = [r for u in res for r in u]
        ttft = [r[0] for r in flat]
        tot = [r[1] for r in flat]
        per_user = statistics.mean(r[2] / max(r[1] - r[0], 1e-6) for r in flat)
        agg = sum(r[2] for r in flat) / wall
        print(f"{n:>6} | {pct(ttft, .5):8.2f} {pct(ttft, .95):6.2f} | "
              f"{pct(tot, .5):9.2f} {pct(tot, .95):6.2f} | {per_user:15.1f} | {agg:11.1f}")


asyncio.run(main())
