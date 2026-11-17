"""Режим «Курс + интернет»: конвейер, SSE, журнал (spec rag-qa, usage-analytics)."""
import asyncio

from app.models import QaLog
from app.rag.engine import RagEngine
from app.rag.prompt import NO_ANSWER_PHRASE, SYSTEM_PROMPT_WEB, WEB_UNAVAILABLE, build_messages

from .conftest import LECTURE, FakeWebSearcher, login_as, parse_sse, upload, wait_indexed


def _prepare(client, student="student1"):
    login_as(client, "lect")
    upload(client, "Лекция 1.txt", LECTURE)
    wait_indexed(client)
    client.post("/api/auth/logout")
    login_as(client, student)


def _ask(client, q="Что такое токен?", mode="web"):
    r = client.post("/api/ask", json={"question": q, "mode": mode})
    assert r.status_code == 200, r.text
    return parse_sse(r.text)


def _rec(client, qa_id) -> QaLog:
    with client.app.state.sessionmaker() as db:
        return db.get(QaLog, qa_id)


# ---------- промпт ----------

def test_web_prompt_blocks_and_no_urls():
    web = {"status": "ok", "results": [
        {"label": "W1", "title": "Стр", "url": "https://example.com/a", "domain": "example.com", "content": "x" * 800}]}
    msgs = build_messages("вопрос", [{"text": "лекция"}], web, "web")
    user = msgs[1]["content"]
    assert msgs[0]["content"] == SYSTEM_PROMPT_WEB and NO_ANSWER_PHRASE not in msgs[0]["content"]
    assert "МАТЕРИАЛЫ КУРСА:" in user and "РЕЗУЛЬТАТЫ ВЕБ-ПОИСКА:" in user
    assert "[L1] лекция" in user and "[W1] Стр — example.com" in user
    assert "https://" not in user  # URL модели не передаются


def test_web_prompt_status_lines():
    down = build_messages("в", [], {"status": "timeout", "results": []}, "web")[1]["content"]
    assert WEB_UNAVAILABLE in down
    empty = build_messages("в", [], {"status": "empty", "results": []}, "web")[1]["content"]
    assert "не доказывает" in empty


# ---------- конвейер ----------

def test_answer_events_order_and_query_privacy(fakes):
    emb, store, llm = fakes
    emb.load()
    store.upsert_chunks(1, "Лекция", 0, ["Токен — это кусочек текста."], None, None)
    web = FakeWebSearcher()
    from app.config import Settings
    eng = RagEngine(Settings(jwt_secret="x"), emb, store, llm, web)

    async def run(mode):
        return [k async for k, _ in eng.answer_events("  Что такое токен?  ", [1], mode)]

    kinds = asyncio.run(run("web"))
    assert kinds[:3] == ["web_status", "sources", "web_sources"] and kinds[-1] == "timings"
    assert web.queries == ["  Что такое токен?  "]  # уходит только текст вопроса
    kinds = asyncio.run(run("course"))
    assert "web_status" not in kinds and "web_sources" not in kinds and len(web.queries) == 1


# ---------- API ----------

def test_web_ok(client, fakes, fake_web):
    _prepare(client)
    fakes[2].answer = "Токен — единица текста [L1], см. также [W1]."
    events = _ask(client)
    kinds = [e for e, _ in events]
    assert kinds[:3] == ["web_status", "sources", "web_sources"] and kinds[-1] == "done"
    assert events[0][1] == {"state": "searching"}
    ws = events[2][1]
    assert ws["status"] == "ok" and [r["label"] for r in ws["results"]] == ["W1", "W2"]
    assert ws["results"][0]["domain"] == "ru.wikipedia.org"
    done = events[-1][1]
    assert done["mode"] == "web" and done["t_mcp_ms"] == 800 and done["t_total_ms"] is not None
    assert done["no_answer"] is False
    rec = _rec(client, done["qa_id"])
    assert rec.mode == "web" and rec.mcp_status == "ok" and rec.web_query == "Что такое токен?"
    assert [s["url"] for s in rec.web_sources] == [r["url"] for r in fake_web.results]
    assert rec.t_mcp_ms == 800 and rec.t_total_ms is not None
    msgs = fakes[2].messages
    assert "РЕЗУЛЬТАТЫ ВЕБ-ПОИСКА" in msgs[1]["content"] and "[W1]" in msgs[1]["content"]
    assert fake_web.queries == ["Что такое токен?"]


def test_course_mode_does_not_call_mcp(client, fake_web):
    _prepare(client)
    events = _ask(client, mode="course")
    assert "web_status" not in [e for e, _ in events]
    assert fake_web.queries == []
    rec = _rec(client, events[-1][1]["qa_id"])
    assert rec.mode == "course" and rec.mcp_status is None


def test_default_mode_is_course(client, fake_web):
    _prepare(client)
    r = client.post("/api/ask", json={"question": "Что такое токен?"})
    done = parse_sse(r.text)[-1][1]
    assert done["mode"] == "course" and fake_web.queries == []


def test_invalid_mode(client):
    _prepare(client)
    assert client.post("/api/ask", json={"question": "Что такое токен?", "mode": "agent"}).status_code == 422


def test_web_empty(client, fake_web):
    _prepare(client)
    fake_web.mode = "empty"
    events = _ask(client)
    assert dict(events)["web_sources"]["status"] == "empty"
    rec = _rec(client, events[-1][1]["qa_id"])
    assert rec.status == "ok" and rec.mcp_status == "empty" and rec.web_sources == []


def test_web_timeout_answers_from_lectures_and_can_be_rated(client, fakes, fake_web):
    _prepare(client)
    fake_web.mode = "slow"
    events = _ask(client)
    assert events[-1][0] == "done"
    assert dict(events)["web_sources"]["status"] == "timeout"
    assert "".join(d["t"] for e, d in events if e == "token")
    assert WEB_UNAVAILABLE in fakes[2].messages[1]["content"]
    qa_id = events[-1][1]["qa_id"]
    rec = _rec(client, qa_id)
    assert rec.status == "ok" and rec.mcp_status == "timeout" and rec.web_sources == [] and rec.mcp_error
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 4}).status_code == 200


def test_web_error(client, fake_web):
    _prepare(client)
    fake_web.mode = "fail"
    events = _ask(client)
    assert events[-1][0] == "done" and dict(events)["web_sources"]["status"] == "error"
    assert _rec(client, events[-1][1]["qa_id"]).mcp_status == "error"


def test_llm_error_in_web_mode_keeps_web_fields(client, fakes):
    _prepare(client)
    fakes[2].fail_after = 1
    events = _ask(client)
    assert events[-1][0] == "error"
    with client.app.state.sessionmaker() as db:
        rec = db.query(QaLog).one()
        assert rec.status == "error" and rec.mode == "web" and rec.mcp_status == "ok"


def test_no_answer_only_in_course_mode(client, fakes):
    _prepare(client)
    fakes[2].answer = "Эта тема в курсе не разбиралась."
    assert _ask(client, mode="web")[-1][1]["no_answer"] is False
    assert _ask(client, mode="course")[-1][1]["no_answer"] is True


# ---------- история и журнал ----------

def test_history_shows_mode_and_web_sources(client):
    _prepare(client)
    qa_id = _ask(client)[-1][1]["qa_id"]
    items = client.get("/api/history").json()["items"]
    assert items[0]["mode"] == "web"
    full = client.get(f"/api/history/{qa_id}").json()
    assert full["mode"] == "web" and full["mcp_status"] == "ok" and len(full["web_sources"]) == 2


def test_lecturer_log_mode_filter_and_details(client, fakes):
    _prepare(client)
    web_id = _ask(client, "Что такое токен?", "web")[-1][1]["qa_id"]
    course_id = _ask(client, "Что такое трансформер?", "course")[-1][1]["qa_id"]
    client.post(f"/api/qa/{web_id}/rating", json={"stars": 1})
    client.post(f"/api/qa/{course_id}/rating", json={"stars": 2})
    assert client.get("/api/stats/log?mode=web").status_code == 403  # студенту журнал недоступен
    client.post("/api/auth/logout")
    login_as(client, "lect")

    def ids(qs):
        r = client.get(f"/api/stats/log?{qs}")
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert ids("mode=web") == [web_id]
    assert ids("mode=course") == [course_id]
    assert set(ids("")) == {web_id, course_id}
    assert ids("mode=web&filter=low") == [web_id]
    assert ids("mode=web&q=трансформер") == []
    assert ids("mode=course&q=трансформер") == [course_id]
    assert client.get("/api/stats/log?mode=agent").status_code == 422
    row = client.get("/api/stats/log?mode=web").json()["items"][0]
    assert row["mode"] == "web" and row["mcp_status"] == "ok" and "web_sources" not in row
    full = client.get(f"/api/stats/log/{web_id}").json()
    assert full["web_query"] == "Что такое токен?" and full["mcp_status"] == "ok"
    assert full["t_mcp_ms"] == 800 and full["t_total_ms"] is not None
    assert [s["url"] for s in full["web_sources"]][0].startswith("https://ru.wikipedia.org")
