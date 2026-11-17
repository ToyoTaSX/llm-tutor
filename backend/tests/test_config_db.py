import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import Settings, load_settings
from app.db import make_sessionmaker
from app.models import QaLog, User


def test_settings_require_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("JWT_SECRET", "   ")
    with pytest.raises(SystemExit) as e:
        load_settings()
    assert "JWT_SECRET" in str(e.value)


def test_lecturer_role_normalized():
    s = Settings(jwt_secret="x", lecturer_logins=" Ivanov , petrova,,")
    assert s.role_for(" IVANOV ") == "lecturer"
    assert s.role_for("petrova") == "lecturer"
    assert s.role_for("student1") == "student"


def test_schema_and_rating_check(tmp_path):
    sm = make_sessionmaker(tmp_path / "app.db")
    with sm() as db:
        u = User(login="a", password_hash="h")
        db.add(u)
        db.commit()
        db.add(QaLog(user_id=u.id, question="q", answer="a", rating=5))
        db.commit()
        for bad in (0, 6):
            db.add(QaLog(user_id=u.id, question="q", answer="a", rating=bad))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
