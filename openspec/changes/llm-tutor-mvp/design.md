# Design

## Context

Проект создаётся с нуля. Мотивация описана в proposal.md (раздел Why), требования — в specs/.

Что есть:
- `rag_lab/` — консольный RAG из лабораторных:
  - `rag_core.py`: BGE-M3 dense+sparse (FlagEmbedding), гибридный поиск в Qdrant с RRF (`CANDIDATES=20`, `RRF_K=60`), промпт тьютора, вызов llama-server через OpenAI-совместимый API;
  - `ingest.py`: нарезка предложениями с перекрытием и границей `ГЛАВА NN`, но каждый раз пересоздаёт всю коллекцию;
  - Qdrant работает в локальном режиме (`path=`) с файловой блокировкой — одна база на один процесс;
  - демо-корпус `rag_lab/data/course.txt` (~137 КБ, 12 сессий курса).
- Целевое железо: RTX 5060 Ti 16 ГБ (Blackwell, sm_120), 16 ГБ RAM, Windows + Docker Desktop (WSL2).
- Пользователь один (демо), нагрузка минимальная. Ресурсы можно расходовать свободно.
- Модели уже лежат локально: `Qwen2.5-3B-Instruct-Q4_K_M.gguf`, BGE-M3.

## Goals / Non-Goals

**Goals:**
- Перенести ядро RAG из `rag_lab` с минимальными изменениями логики поиска и промпта.
- Одна команда запуска, все сервисы в контейнерах, данные в томах.
- Вопрос → источники → ответ потоком; после этого оценка; всё пишется в журнал.
- Инкрементальная индексация по документам.

**Non-Goals:**
- Горизонтальное масштабирование, очереди задач (Celery/Redis), HTTPS, обратный прокси для внешнего доступа.
- Миграции схемы БД (Alembic): схема создаётся при старте, для MVP этого достаточно.
- Реранкер, переписывание вопроса, многоходовой контекст.
- Автотесты фронтенда. Бэкенд покрывается pytest на ключевые сценарии.

## Decisions

### D1. Четыре контейнера в docker-compose

```
 browser --> frontend (nginx :3000) --/api/*--> backend (FastAPI :8000)
                                                   |        |         |
                                       SQLite (volume)   qdrant :6333  llm :8080
```

| Сервис | Образ | GPU | Тома |
|---|---|---|---|
| `frontend` | multi-stage: node:22 build → nginx:alpine | – | – |
| `backend` | python:3.12-slim + torch cu128 | да | `app_data:/data`, `${MODELS_DIR}:/models:ro`, `./rag_lab/data:/seed:ro` |
| `llm` | llama.cpp server-cuda (CUDA ≥ 12.8) | да | `${MODELS_DIR}:/models:ro` |
| `qdrant` | qdrant/qdrant (закреплённая версия) | – | `qdrant_data:/qdrant/storage` |

- nginx отдаёт SPA и проксирует `/api` на backend. Фронт и API живут на одном origin, поэтому CORS не нужен, а cookie работают просто. Для `/api/ask` отключена буферизация (`proxy_buffering off`), иначе SSE не будет стримиться.
- Порты наружу: 3000 (UI). Для отладки также открыты 8080 (llama-server) и 6333 (Qdrant dashboard).
- `depends_on: condition: service_healthy`:
  - `llm` проверяется по `GET /health`;
  - `qdrant` — по `/readyz`;
  - backend стартует после qdrant и не ждёт llm жёстко: он сам опрашивает `/health` и отдаёт статус в `GET /api/health`, а UI показывает баннер «модель загружается».
- Альтернатива: Qdrant в локальном режиме внутри backend (как в лабе). Это на один контейнер меньше, но блокировка базы и отсутствие dashboard. Сервер удобнее для демо и отладки.

### D2. Blackwell-совместимость — первый спайк
sm_120 требует CUDA 12.8+. Порядок:
1. Пробуем официальный образ `ghcr.io/ggml-org/llama.cpp:server-cuda` и проверяем, что модель грузится на GPU (`offloaded 37/37 layers`).
2. Если образ собран без sm_120 — свой `llm/Dockerfile`: `nvidia/cuda:12.8.x-devel` → сборка llama.cpp с `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=120` → runtime-образ.
3. Backend: torch с индекса `https://download.pytorch.org/whl/cu128`, проверка `torch.cuda.get_device_capability() == (12, 0)` при старте и лог.

### D3. Параметры llama-server
`-m /models/<LLM_FILE> -c 32768 -np 4 -ngl 99 -fa on --host 0.0.0.0 --port 8080`

- 4 слота × 8192 токена.
- Бюджет промпта: системный (~150) + 6 фрагментов × ~1000 символов (~350–450 токенов каждый на русском у Qwen) + вопрос ≈ 3000 токенов, плюс до 1024 токенов ответа. Укладывается в 8192 с запасом.
- VRAM: модель ~2 ГБ + KV ~1.2 ГБ + BGE-M3 ~1.5 ГБ ≈ 5 ГБ из 16.

Параметры RAG (через `.env`): `TOP_K=6`, `CANDIDATES=20`, `RRF_K=60`, `CHUNK_CHARS=1000`, `OVERLAP_CHARS=200`, `TEMPERATURE=0.2`, `MAX_TOKENS=1024`. Системный промпт берётся из `rag_lab/config.py` без изменений.

Уточнение по итогам реализации: только с системным промптом Qwen2.5-3B не поставил ни одной ссылки `[n]` (0 из 5 вопросов контрольного набора). Поэтому в конец сообщения пользователя добавляется короткое напоминание: «После каждого утверждения из фрагментов ставь номер фрагмента в квадратных скобках, например [1]». С ним ссылки есть во всех ответах по теме (7 из 7), а вопрос-ловушка по-прежнему получает «Эта тема в курсе не разбиралась». Более длинное напоминание, повторявшее и правило про отказ, ломало ответ-отказ и было отклонено.

### D4. Backend: FastAPI + SQLAlchemy 2 + SQLite
- SQLite в режиме WAL в `/data/app.db`. Писатель один (backend), нагрузка демо. Postgres добавил бы контейнер без выгоды.
- `pydantic-settings` читает `.env`. Отсутствие `JWT_SECRET` — fail fast (spec deployment).
- Структура:

```
backend/app/
  main.py            # app, lifespan: init db, seed, проверка GPU, warmup embedder
  config.py          # Settings
  db.py, models.py   # SQLAlchemy
  auth/              # router, security (hash, jwt), deps (current_user, require_lecturer)
  rag/
    embedder.py      # BGE-M3 singleton + lock      (из rag_core.encode)
    store.py         # Qdrant: ensure_collection, upsert, delete_by_doc, search
    chunker.py       # из ingest.split_chunks/split_sentences, обобщён
    llm.py           # AsyncOpenAI stream
    prompt.py        # SYSTEM_PROMPT, build_messages
  routers/ ask.py, history.py, documents.py, stats.py, health.py
  indexing.py        # фоновая очередь индексации
backend/tests/
```

### D5. Схема данных

```
users     (id PK, login UNIQUE [нормализован lower+strip], password_hash, created_at)
documents (id PK, title, filename, file_path, status ENUM(indexing,ready,error),
           error TEXT NULL, chunks_count, chars, uploaded_by FK users, created_at, indexed_at)
qa_log    (id PK, created_at, user_id FK users, question, answer, status ENUM(ok,error),
           no_answer BOOL, sources JSON, rating INT NULL CHECK 1..5, rated_at,
           t_search_ms, t_llm_ms, prompt_tokens, completion_tokens)
app_meta  (key PK, value)      -- seed_done=1
```

- `qa_log.sources` — денормализованный снимок `[{n, doc_id, doc_title, chunk_no, score, rank, text}]`. Поэтому журнал читается и после удаления документа (spec lecture-documents).
- Индексы: `qa_log(created_at)`, `qa_log(user_id, created_at)`, `qa_log(rating)`.
- Роль в БД **не хранится** (spec user-auth), вычисляется из `LECTURER_LOGINS`.

### D6. Аутентификация
- Хеш паролей: `argon2-cffi` (через `pwdlib`). Альтернатива bcrypt тоже годится, но argon2 — текущая рекомендация, и у него нет лимита в 72 байта.
- JWT (PyJWT, HS256, `exp`=24 ч) в **httpOnly cookie** `SameSite=Lax`. Same-origin через nginx, токен недоступен JS, SSE-запросы через `fetch` несут cookie автоматически.
- В JWT лежит только `sub` (user id). Роль вычисляется в зависимости `current_user` на каждом запросе по логину и `LECTURER_LOGINS`. Поэтому смена `.env` + рестарт сразу меняет права, и подделать роль нельзя.
- `GET /api/auth/me` → `{id, login, role}`. Фронт строит меню по нему.
- Ограничение: логин из `LECTURER_LOGINS` может первым зарегистрировать кто угодно. Принято для локального демо (см. Risks).

### D7. API

| Метод | Путь | Роль | Назначение |
|---|---|---|---|
| POST | `/api/auth/register` | – | регистрация + вход |
| POST | `/api/auth/login` / `/logout` | – | вход / выход |
| GET | `/api/auth/me` | любой | профиль и роль |
| POST | `/api/ask` | любой | SSE-поток ответа |
| POST | `/api/qa/{id}/rating` | автор | `{stars: 1..5}` |
| GET | `/api/history`, `/api/history/{id}` | автор | свои вопросы |
| GET/POST | `/api/documents` | лектор | список / загрузка (multipart, несколько файлов) |
| DELETE | `/api/documents/{id}` | лектор | удаление |
| POST | `/api/documents/{id}/reindex` | лектор | переиндексация |
| GET | `/api/stats/summary?period=7d\|30d\|all` | лектор | карточки + гистограмма + по дням |
| GET | `/api/stats/log?filter=&q=&page=` | лектор | журнал |
| GET | `/api/stats/log/{id}` | лектор | детали записи |
| GET | `/api/health` | – | `{llm: ready\|loading\|down, qdrant, gpu}` |

### D8. Потоковый ответ: SSE через POST
`EventSource` умеет только GET, поэтому фронт использует `fetch` + `ReadableStream` и разбирает формат `text/event-stream` сам (`@microsoft/fetch-event-source` или ~40 строк своего кода).

```
event: sources  data: [{n, doc_title, chunk_no, rank, score, text}]
event: token    data: {"t": "..."}             (много раз)
event: done     data: {"qa_id": 42, "no_answer": false, "t_search_ms":..., "t_llm_ms":...}
event: error    data: {"message": "..."}
```

- Порядок на сервере: поиск → отправка `sources` → стрим из llama-server (`stream=True`, `stream_options.include_usage`) → INSERT в `qa_log` → `done`.
- При ошибке пишется запись со `status=error`, затем отправляется `error`.
- Если клиент отключился посреди ответа, генерация прерывается, и сохраняется то, что успело сгенерироваться.
- `no_answer` = ответ содержит фразу «Эта тема в курсе не разбиралась» (нормализованное сравнение).

### D9. Эмбеддер и конкурентность
- BGE-M3 — один экземпляр в процессе backend, загружается при старте (warmup), fp16 на CUDA.
- `encode` синхронный, поэтому вызывается через `run_in_threadpool` под `threading.Lock`: модель не гарантирует потокобезопасность.
- Индексация берёт lock **на каждый батч** (16 фрагментов), а не на весь документ. Вопросы студентов вклиниваются между батчами и не ждут окончания индексации большого файла.
- Модель грузится по пути `/models/bge-m3` с `HF_HUB_OFFLINE=1`, без `snapshot_download`.

### D10. Индексация и поиск в Qdrant
- Одна коллекция `lectures`: `dense` (1024, cosine) + `sparse`. Payload `{doc_id, doc_title, chunk_no, text}`, payload-индекс на `doc_id` (integer).
- ID точки — `uuid5(NAMESPACE, f"{doc_id}:{chunk_no}")`. Upsert идемпотентен.
- Фоновая очередь: `asyncio.Queue` + один воркер в lifespan. Документы индексируются последовательно, статус пишется в SQLite. Если при старте найдены документы в статусе `indexing` (прерванные рестартом), они ставятся в очередь заново.
- **Видимость через фильтр.** Поиск всегда добавляет фильтр `doc_id IN (ready ids)`, ids берутся из SQLite. Поэтому:
  - частично проиндексированный или упавший документ не попадает в ответы;
  - при переиндексации сначала удаляются старые точки документа, статус ставится `indexing` (документ временно не участвует в ответах — для MVP это допустимо), затем записываются новые;
  - при ошибке выполняется `delete_by_doc`, статус меняется на `error`.
- Сам гибридный поиск — код `rag_core.search` с добавленным фильтром.

### D11. Чанкер
Берётся `split_sentences`/`split_chunks` из `ingest.py`. Граница «новой главы» обобщается: строка считается заголовком, если совпадает с `^(ГЛАВА|Глава|Лекция|ЛЕКЦИЯ|Раздел|#+)\s` **или** это короткая строка (< 80 символов, без точки в конце), стоящая перед пустой строкой. Сокращения и аварийная нарезка длинных предложений сохраняются. Декодирование: `utf-8-sig` → `cp1251`, иначе ошибка (spec).

### D12. Демо-корпус
При старте: если `app_meta.seed_done` не выставлен и файл `/seed/course.txt` существует, создаётся документ «Курс: Технологии нейронных сетей» (uploaded_by = NULL, «система»), ставится в очередь и выставляется `seed_done=1`.

### D13. Frontend: React + Vite + TypeScript + Tailwind
- Библиотеки: react-router, TanStack Query (кэш и поллинг статусов документов раз в 2 с, пока есть `indexing`), react-markdown + remark-gfm, recharts (гистограмма и активность), lucide-react (иконки).
- Тема в духе LM Studio: тёмный фон `#1e1e1e`/`#252526`, узкая левая иконочная панель, моноширинные акценты, тонкие границы. Только тёмная тема.

```
 +--+------------------+---------------------------------+---------------+
 |  | История вопросов |  Qwen2.5-3B * 3 лекции * ready  | Источники  [<]|
 |Ch|  (свои, qa_log)  |                                 | [1] Лекция 02 |
 |Do|                  |  > вопрос                       |     rank 1 ##|
 |St|                  |  ответ ... [1] [3]              |     "..."     |
 |  |                  |  * * * * o                      | [2] (приглуш.)|
 |Lo|                  |  [ поле ввода ........... ] [>] |               |
 +--+------------------+---------------------------------+---------------+
  Ch чат (все)  Do документы, St статистика (лектор)  Lo выход
```

- Ссылки `[n]` в ответе: пост-обработка markdown заменяет `\[(\d+)\]` на кнопку. Клик прокручивает панель и подсвечивает карточку. «Процитированные» — множество `n`, встреченных в ответе.
- Релевантность: показывается ранг и полоска, нормированная к максимальному RRF-score в выдаче. Сырой score — в tooltip.
- Свёрнутость панели хранится в `localStorage`.
- Лог лектора открывает ту же карточку «вопрос–ответ–источники» (общий компонент `QaView`).

### D14. Проверка качества
`rag_lab/eval.py` адаптируется в `backend/scripts/eval.py` и вызывает тот же код поиска и генерации через `docker compose exec backend`. Это нужно, чтобы сравнить ответы Qwen2.5-3B с лабораторными до демонстрации.

## Risks / Trade-offs

- [Образы без поддержки sm_120 → модель на CPU или падение] → спайк первой задачей (D2), запасной вариант — собственная сборка llama.cpp на CUDA 12.8.
- [Qwen2.5-3B слабее на русском, путает ссылки `[n]` или отвечает вне фрагментов] → низкая temperature, промпт из лабы, прогон eval; модель меняется одной переменной `LLM_FILE` в `.env`.
- [Логин лектора может занять посторонний] → принято для локального демо. На общем сервере закрывается запретом публичной регистрации логинов из `LECTURER_LOGINS` и созданием этих учёток при старте.
- [SQLite + фоновая индексация + запросы одновременно → `database is locked`] → WAL, короткие транзакции, один процесс uvicorn (1 worker).
- [Индексация занимает GPU и замедляет ответы] → lock по батчам (D9); для объёмов курса индексация занимает секунды.
- [Во время переиндексации документ временно не участвует в ответах] → принято для MVP. Альтернатива — поколения точек (`gen` в payload) с атомарным переключением, если понадобится.
- [Буферизация nginx/Docker ломает стриминг] → `proxy_buffering off`, `X-Accel-Buffering: no`, проверка в задачах.
- [Холодный старт: загрузка моделей ~20–60 с] → healthcheck + статус в UI вместо ошибок.
- [`no_answer` по совпадению фразы ненадёжен, если модель перефразирует] → нормализованное сравнение по ключевой части фразы; метрика носит справочный характер.

## Migration Plan

Новый проект, миграции и откат не нужны. Порядок развёртывания:
1. Скопировать `.env.example` → `.env`, задать `JWT_SECRET`, `LECTURER_LOGINS`, `MODELS_DIR`, `LLM_FILE`.
2. `docker compose up --build`.
3. Сразу после старта зарегистрировать логины лекторов (см. Risks).
4. Дождаться индексации демо-корпуса на странице «Документы».

`rag_lab/` не меняется. Существующие `qdrant_course/` и `qdrant_db/` не используются: индекс строится заново в томе `qdrant_data`.
