from app.auth.security import COOKIE_NAME, create_token

from .conftest import register


def test_register_logs_in(client):
    r = register(client, "Student1")
    assert r.status_code == 200
    assert r.json() == {"id": 1, "login": "student1", "role": "student"}
    assert client.get("/api/auth/me").json()["login"] == "student1"


def test_login_taken_case_insensitive(client):
    register(client, "student1")
    client.cookies.clear()
    r = register(client, " Student1 ")
    assert r.status_code == 422
    assert r.json()["detail"] == {"field": "login", "message": "Логин уже занят"}


def test_invalid_data(client):
    r = register(client, "ok_login", "1234")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "password"
    r = register(client, "плохой логин")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "login"


def test_same_message_for_bad_login_and_password(client):
    register(client, "student1")
    client.cookies.clear()
    a = client.post("/api/auth/login", json={"login": "student1", "password": "wrong-pass"})
    b = client.post("/api/auth/login", json={"login": "nobody", "password": "wrong-pass"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Неверный логин или пароль"}


def test_password_never_returned(client):
    r = register(client, "student1", "secret123")
    for resp in (r, client.get("/api/auth/me")):
        assert "secret123" not in resp.text
        assert "argon2" not in resp.text and "hash" not in resp.text


def test_password_stored_hashed(client):
    register(client, "student1", "secret123")
    from app.models import User

    with client.app.state.sessionmaker() as db:
        u = db.query(User).one()
        assert u.password_hash != "secret123" and u.password_hash.startswith("$argon2")


def test_unauthorized_without_session(client):
    for method, url in [("get", "/api/auth/me"), ("get", "/api/history"), ("post", "/api/ask"),
                        ("get", "/api/documents"), ("get", "/api/stats/summary")]:
        r = getattr(client, method)(url, **({"json": {"question": "x"}} if method == "post" else {}))
        assert r.status_code == 401, url


def test_expired_session(client):
    register(client, "student1")
    client.cookies.set(COOKIE_NAME, create_token(1, "test-secret", ttl_hours=-1))
    assert client.get("/api/auth/me").status_code == 401


def test_logout(client):
    register(client, "student1")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_student_forbidden_on_lecturer_api(client):
    register(client, "student1")
    assert client.get("/api/documents").status_code == 403
    assert client.get("/api/stats/summary").status_code == 403
    assert client.get("/api/stats/log").status_code == 403
    r = client.post("/api/documents", files=[("files", ("a.txt", b"text", "text/plain"))])
    assert r.status_code == 403


def test_lecturer_from_env(client):
    r = register(client, "LECT")
    assert r.json()["role"] == "lecturer"
    assert client.get("/api/documents").status_code == 200


def test_role_follows_env_after_restart(make_client):
    with make_client(lecturer_logins="petrova") as c:
        assert register(c, "petrova").json()["role"] == "lecturer"
    with make_client(lecturer_logins="ivanov") as c:
        r = c.post("/api/auth/login", json={"login": "petrova", "password": "secret123"})
        assert r.json()["role"] == "student"
