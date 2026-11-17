"""История своих вопросов (spec rag-qa)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.deps import CurrentUser, current_user, get_db
from ..models import QaLog, iso

router = APIRouter(prefix="/api/history", tags=["history"])


def qa_full(r: QaLog, login: str | None = None) -> dict:
    out = {
        "id": r.id,
        "created_at": iso(r.created_at),
        "question": r.question,
        "answer": r.answer,
        "status": r.status,
        "no_answer": r.no_answer,
        "sources": r.sources or [],
        "rating": r.rating,
        "rated_at": iso(r.rated_at),
        "t_search_ms": r.t_search_ms,
        "t_llm_ms": r.t_llm_ms,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "mode": r.mode or "course",
        "web_query": r.web_query,
        "web_sources": r.web_sources or [],
        "mcp_status": r.mcp_status,
        "mcp_error": r.mcp_error,
        "t_mcp_ms": r.t_mcp_ms,
        "t_total_ms": r.t_total_ms,
    }
    if login is not None:
        out["login"] = login
    return out


@router.get("")
def my_history(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    user: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    base = select(QaLog).where(QaLog.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(QaLog.created_at.desc(), QaLog.id.desc()).offset((page - 1) * limit).limit(limit))
    items = [
        {"id": r.id, "created_at": iso(r.created_at), "question": r.question, "rating": r.rating,
         "status": r.status, "no_answer": r.no_answer, "mode": r.mode or "course"}
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/{qa_id}")
def my_history_item(qa_id: int, user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(QaLog, qa_id)
    if r is None or r.user_id != user.id:  # чужие вопросы не раскрываем
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    return qa_full(r)
