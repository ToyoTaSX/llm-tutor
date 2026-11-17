from app.config import Settings

from .conftest import LECTURE, login_as, upload, wait_indexed


def test_upload_and_index(client, fakes):
    _, store, _ = fakes
    login_as(client, "lect")
    r = upload(client, "Лекция 13.txt", LECTURE)
    assert r.status_code == 200, r.text
    doc = r.json()["created"][0]
    assert doc["title"] == "Лекция 13" and doc["status"] == "indexing"
    docs = wait_indexed(client)
    assert docs[0]["status"] == "ready"
    assert docs[0]["chunks_count"] == store.count_by_doc(doc["id"]) > 0
    assert docs[0]["uploaded_by"] == "lect"


def test_custom_title_and_cp1251(client, fakes):
    _, store, _ = fakes
    login_as(client, "lect")
    r = upload(client, "x.txt", LECTURE.decode("utf-8").encode("cp1251"), title="Моя лекция")
    doc = r.json()["created"][0]
    assert doc["title"] == "Моя лекция"
    wait_indexed(client)
    texts = [p["text"] for p in store.points[doc["id"]].values()]
    assert any("Токен — это кусочек текста" in t for t in texts)


def test_rejects_bad_files(make_client):
    with make_client(max_upload_mb=1) as client:
        login_as(client, "lect")
        for name, content, msg in [
            ("a.pdf", b"%PDF", ".txt"),
            ("empty.txt", b"   \n", "пустой"),
            ("big.txt", b"a" * (1024 * 1024 + 10), "1 МБ"),
            ("bin.txt", b"\x00\x01\x02", "двоичный"),
        ]:
            r = upload(client, name, content)
            assert r.status_code == 422, name
            assert msg in r.json()["detail"]["errors"][0]["message"], name
        assert client.get("/api/documents").json() == []


def test_mixed_upload_reports_errors(client):
    login_as(client, "lect")
    r = client.post("/api/documents", files=[("files", ("ok.txt", LECTURE, "text/plain")),
                                             ("files", ("bad.pdf", b"x", "application/pdf"))])
    assert r.status_code == 200
    assert len(r.json()["created"]) == 1 and r.json()["errors"][0]["filename"] == "bad.pdf"


def test_index_error_cleans_up(client, fakes):
    emb, store, _ = fakes
    login_as(client, "lect")
    emb.fail = True
    doc_id = upload(client, "l.txt", LECTURE).json()["created"][0]["id"]
    d = wait_indexed(client)[0]
    assert d["status"] == "error" and "encode failed" in d["error"]
    assert store.count_by_doc(doc_id) == 0

    emb.fail = False  # переиндексация после ошибки
    r = client.post(f"/api/documents/{doc_id}/reindex")
    assert r.status_code == 200 and r.json()["status"] == "indexing"
    d = wait_indexed(client)[0]
    assert d["status"] == "ready" and d["error"] is None and store.count_by_doc(doc_id) > 0


def test_delete_removes_points(client, fakes):
    _, store, _ = fakes
    login_as(client, "lect")
    doc_id = upload(client, "l.txt", LECTURE).json()["created"][0]["id"]
    wait_indexed(client)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get("/api/documents").json() == []
    assert store.count_by_doc(doc_id) == 0
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404


def test_seed_once(make_client, tmp_path, fakes):
    _, store, _ = fakes
    seed = tmp_path / "course.txt"
    seed.write_bytes(LECTURE)
    with make_client(seed_file=seed) as c:
        login_as(c, "lect")
        docs = wait_indexed(c)
        assert [d["title"] for d in docs] == ["Курс: Технологии нейронных сетей"]
        assert docs[0]["status"] == "ready" and docs[0]["uploaded_by"] is None
        c.delete(f"/api/documents/{docs[0]['id']}")
    with make_client(seed_file=seed) as c:  # рестарт: удалённый демо-корпус не возвращается
        login_as(c, "lect")
        assert c.get("/api/documents").json() == []


def test_interrupted_indexing_resumed(make_client, tmp_path):
    from app.db import make_sessionmaker
    from app.documents_service import create_document

    s = Settings(jwt_secret="x", data_dir=tmp_path / "data")
    sm = make_sessionmaker(s.data_dir / "app.db")
    with sm() as db:
        create_document(db, s, "Прерванная", "p.txt", LECTURE.decode(), None)
    with make_client() as c:
        login_as(c, "lect")
        assert wait_indexed(c)[0]["status"] == "ready"
