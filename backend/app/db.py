"""Подключение к SQLite."""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_sessionmaker(db_path: Path) -> sessionmaker:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
        # SQLite lower() понимает только латиницу; для поиска по русскому тексту
        conn.create_function("py_lower", 1, lambda s: s.lower() if isinstance(s, str) else s)

    from . import models  # noqa: F401  регистрация таблиц

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
