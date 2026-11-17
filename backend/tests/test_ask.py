from app.models import QaLog
from app.components_util import cited_labels
from app.rag.prompt import CITATION_REMINDER_COURSE, NO_ANSWER_PHRASE, build_messages, is_no_answer

from .conftest import LECTURE, login_as, parse_sse, upload, wait_indexed


def _prepare(client, student="student1"):
    login_as(client, "lect")
    upload(client, "Лекция 1.txt", LECTURE)
    wait_indexed(client)
    client.post("/api/auth/logout")
    login_as(client, student)


def _ask(client, q="Что такое токен?"):
    r = client.post("/api/ask", json={"question": q})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


def test_prompt_numbering():
    msgs = build_messages("вопрос", [{"text": f"фрагмент {i}"} for i in range(6)])
    assert "[L1] фрагмент 0" in msgs[1]["content"] and "[L6] фрагмент 5" in msgs[1]["content"]
    assert msgs[1]["content"].startswith("МАТЕРИАЛЫ КУРСА:")
    assert "РЕЗУЛЬТАТЫ ВЕБ-ПОИСКА" not in msgs[1]["content"]
    assert NO_ANSWER_PHRASE in msgs[0]["content"]
    assert msgs[1]["content"].rstrip().endswith(CITATION_REMINDER_COURSE)


def test_cited_labels():
    assert cited_labels("Ответ [L1]. Ещё [L2, L3] и [W1][w2], [L4; W3], [L5, 6].") == {
        "L1", "L2", "L3", "W1", "W2", "L4", "W3", "L5", "L6"}
    assert cited_labels("без ссылок [1] [X2]") == set()
    assert cited_labels("[Л1] и [л2, W1]") == {"L1", "L2", "W1"}  # кириллическая «Л» от 3B-модели


def test_no_answer_detection():
    assert is_no_answer("Эта тема в курсе не разбиралась.")
    assert is_no_answer("К сожалению, эта тема в курсе НЕ разбиралась")
    assert not is_no_answer("Токен — это кусочек текста [1].")


def test_events_order_and_log(client, fakes):
    _prepare(client)
    events = _ask(client)
    kinds = [e for e, _ in events]
    assert kinds[0] == "sources" and kinds[-1] == "done"
    assert set(kinds[1:-1]) == {"token"}
    sources = events[0][1]
    assert sources and sources[0]["n"] == 1 and sources[0]["label"] == "L1" and sources[0]["doc_title"] == "Лекция 1"
    assert "токен" in sources[0]["text"].lower()
    answer = "".join(d["t"] for e, d in events if e == "token")
    done = events[-1][1]
    with client.app.state.sessionmaker() as db:
        rec = db.get(QaLog, done["qa_id"])
        assert rec.question == "Что такое токен?" and rec.answer == answer.strip()
        assert rec.user.login == "student1" and rec.rating is None and rec.status == "ok"
        assert rec.sources[0]["text"] == sources[0]["text"]
        assert rec.prompt_tokens == 100 and rec.t_llm_ms is not None
        assert rec.mode == "course" and rec.mcp_status is None and rec.web_sources == []
        assert rec.t_total_ms is not None and rec.t_total_ms >= rec.t_llm_ms
    # модель получила фрагменты с метками [L*]
    assert "[L1]" in fakes[2].messages[1]["content"]


def test_no_answer_flag(client, fakes):
    _prepare(client)
    fakes[2].answer = "Эта тема в курсе не разбиралась."
    done = _ask(client, "Как варить борщ?")[-1][1]
    assert done["no_answer"] is True


def test_llm_error(client, fakes):
    _prepare(client)
    fakes[2].fail_after = 2
    events = _ask(client)
    assert events[-1][0] == "error"
    assert "недоступна" in events[-1][1]["message"]
    assert [e for e, _ in events].count("token") == 2
    with client.app.state.sessionmaker() as db:
        rec = db.query(QaLog).one()
        assert rec.status == "error"
        r = client.post(f"/api/qa/{rec.id}/rating", json={"stars": 5})
        assert r.status_code == 409


def test_question_validation(client):
    _prepare(client)
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 2001}).status_code == 422


def test_no_documents(client):
    login_as(client, "student1")
    r = client.post("/api/ask", json={"question": "Что такое токен?"})
    assert r.status_code == 409 and "не загружены" in r.json()["detail"]


def test_rating(client):
    _prepare(client)
    qa_id = _ask(client)[-1][1]["qa_id"]
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 0}).status_code == 422
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 6}).status_code == 422
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 2}).json()["rating"] == 2
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 5}).json()["rating"] == 5
    assert client.get(f"/api/history/{qa_id}").json()["rating"] == 5
    client.post("/api/auth/logout")
    login_as(client, "student2")
    assert client.post(f"/api/qa/{qa_id}/rating", json={"stars": 1}).status_code == 403


def test_history_isolation(client):
    _prepare(client, "student1")
    _ask(client, "Что такое токен?")
    _ask(client, "Что такое трансформер?")
    h = client.get("/api/history").json()
    assert [i["question"] for i in h["items"]] == ["Что такое трансформер?", "Что такое токен?"]
    own_id = h["items"][0]["id"]
    item = client.get(f"/api/history/{own_id}").json()
    assert item["sources"] and item["answer"]
    client.post("/api/auth/logout")
    login_as(client, "student2")
    assert client.get("/api/history").json()["items"] == []
    assert client.get(f"/api/history/{own_id}").status_code == 404


def test_deleted_document_not_used_and_log_kept(client):
    _prepare(client)
    qa_id = _ask(client)[-1][1]["qa_id"]
    client.post("/api/auth/logout")
    login_as(client, "lect")
    doc_id = client.get("/api/documents").json()[0]["id"]
    client.delete(f"/api/documents/{doc_id}")
    item = client.get(f"/api/stats/log/{qa_id}").json()
    assert item["sources"][0]["doc_title"] == "Лекция 1" and item["sources"][0]["text"]
    r = client.post("/api/ask", json={"question": "Что такое токен?"})
    assert r.status_code == 409  # документов больше нет
