from datetime import timedelta

import pytest

from app.models import QaLog, User, utcnow

from .conftest import login_as


@pytest.fixture
def seeded(client):
    login_as(client, "lect")
    now = utcnow()
    with client.app.state.sessionmaker() as db:
        s1 = User(login="s1", password_hash="h")
        s2 = User(login="s2", password_hash="h")
        db.add_all([s1, s2])
        db.flush()
        rows = [
            QaLog(user_id=s1.id, question="Что такое Трансформер?", answer="a", rating=5, t_search_ms=100, t_llm_ms=900),
            QaLog(user_id=s1.id, question="Что такое токен?", answer="a", rating=4, t_search_ms=100, t_llm_ms=900),
            QaLog(user_id=s2.id, question="Внимание", answer="a", rating=3, t_search_ms=100, t_llm_ms=900),
            QaLog(user_id=s2.id, question="Как варить борщ?", answer="Эта тема в курсе не разбиралась", no_answer=True,
                  t_search_ms=100, t_llm_ms=900),
            QaLog(user_id=s2.id, question="Слово", answer="a", t_search_ms=100, t_llm_ms=900),
            QaLog(user_id=s2.id, question="Сбой", answer="", status="error"),
            QaLog(user_id=s1.id, question="Старый", answer="a", rating=1, created_at=now - timedelta(days=40)),
        ]
        db.add_all(rows)
        db.commit()
    return client


def test_summary_7d(seeded):
    s = seeded.get("/api/stats/summary?period=7d").json()
    assert s["questions"] == 6 and s["active_users"] == 2 and s["errors"] == 1
    assert s["avg_rating"] == 4.0
    assert s["rated_share"] == 0.6  # 3 из 5 успешных
    assert s["no_answer_share"] == 0.2
    assert s["avg_time_ms"] == 1000
    assert s["histogram"] == {"1": 0, "2": 0, "3": 1, "4": 1, "5": 1}
    assert len(s["daily"]) == 7 and s["daily"][-1]["count"] == 6 and s["daily"][0]["count"] == 0


def test_summary_all(seeded):
    s = seeded.get("/api/stats/summary?period=all").json()
    assert s["questions"] == 7 and s["histogram"]["1"] == 1
    assert len(s["daily"]) == 41


def test_summary_empty(client):
    login_as(client, "lect")
    s = client.get("/api/stats/summary?period=30d").json()
    assert s["questions"] == 0
    assert s["avg_rating"] is None and s["rated_share"] is None and s["no_answer_share"] is None
    assert len(s["daily"]) == 30 and all(d["count"] == 0 for d in s["daily"])


def test_log_filters(seeded):
    def qs(**params):
        return [i["question"] for i in seeded.get("/api/stats/log", params=params).json()["items"]]

    assert set(qs(filter="low")) == {"Старый"}
    assert set(qs(filter="unrated")) == {"Как варить борщ?", "Слово"}
    assert qs(filter="no_answer") == ["Как варить борщ?"]
    assert qs(q="трансформер") == ["Что такое Трансформер?"]  # кириллица без учёта регистра
    page = seeded.get("/api/stats/log", params={"limit": 2, "page": 2}).json()
    assert page["total"] == 7 and len(page["items"]) == 2
    first = seeded.get("/api/stats/log").json()["items"][0]
    assert first["login"] in {"s1", "s2"} and "sources" not in first


def test_log_item(seeded):
    item = seeded.get("/api/stats/log").json()["items"][0]
    full = seeded.get(f"/api/stats/log/{item['id']}").json()
    assert full["sources"] == [] and full["login"] == item["login"]


def test_bad_period(seeded):
    assert seeded.get("/api/stats/summary?period=1y").status_code == 422
