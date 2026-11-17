"""Таблицы базы данных (design D5)."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Время в UTC без tzinfo (так его хранит SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="indexing")  # indexing | ready | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    uploader: Mapped[User | None] = relationship()


class QaLog(Base):
    __tablename__ = "qa_log"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="rating_range"),
        Index("ix_qa_log_created_at", "created_at"),
        Index("ix_qa_log_user_created", "user_id", "created_at"),
        Index("ix_qa_log_rating", "rating"),
        Index("ix_qa_log_mode", "mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(8), default="ok")  # ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    no_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_search_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_llm_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # режим ответа и веб-поиск через MCP (design D7)
    mode: Mapped[str] = mapped_column(String(8), default="course", server_default="course")  # course | web
    web_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    web_sources: Mapped[list] = mapped_column(JSON, default=list)
    mcp_status: Mapped[str | None] = mapped_column(String(8), nullable=True)  # ok | empty | timeout | error
    mcp_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    t_mcp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship()


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
