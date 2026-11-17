"""Статистика и журнал для лектора (spec usage-analytics)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..auth.deps import CurrentUser, get_db, require_lecturer
from ..models import QaLog, utcnow
from .history import qa_full

router = APIRouter(prefix="/api/stats", tags=["stats"])

PERIODS = {"7d": 7, "30d": 30, "all": None}


@router.get("/summary")
def summary(
    period: str = Query("7d"),
    tz_offset: int = Query(0, ge=-840, le=840, description="смещение часового пояса клиента в минутах (UTC+5 → 300)"),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_lecturer),
):
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail="period: 7d | 30d | all")
    shift = timedelta(minutes=tz_offset)
    now_local = utcnow() + shift
    days = PERIODS[period]
    since_utc = None
    if days is not None:
        first_day = now_local.date() - timedelta(days=days - 1)
        since_utc = datetime.combine(first_day, datetime.min.time()) - shift

    q = select(QaLog)
    if since_utc is not None:
        q = q.where(QaLog.created_at >= since_utc)
    rows = list(db.scalars(q))

    ok = [r for r in rows if r.status == "ok"]
    rated = [r.rating for r in ok if r.rating is not None]
    times = [r.t_total_ms if r.t_total_ms is not None else (r.t_search_ms or 0) + (r.t_llm_ms or 0)
             for r in ok if r.t_llm_ms is not None]

    def share(n: int, d: int):
        return round(n / d, 4) if d else None

    hist = {str(i): 0 for i in range(1, 6)}
    for v in rated:
        hist[str(v)] += 1

    per_day: dict[date, int] = {}
    for r in rows:
        d = (r.created_at + shift).date()
        per_day[d] = per_day.get(d, 0) + 1
    if days is not None:
        start = now_local.date() - timedelta(days=days - 1)
    else:
        start = min(per_day) if per_day else now_local.date()
    daily = []
    d = start
    while d <= now_local.date():
        daily.append({"date": d.isoformat(), "count": per_day.get(d, 0)})
        d += timedelta(days=1)

    return {
        "period": period,
        "questions": len(rows),
        "active_users": len({r.user_id for r in rows}),
        "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
        "rated_count": len(rated),
        "rated_share": share(len(rated), len(ok)),
        "no_answer_share": share(sum(1 for r in ok if r.no_answer), len(ok)),
        "errors": len(rows) - len(ok),
        "avg_time_ms": round(sum(times) / len(times)) if times else None,
        "histogram": hist,
        "daily": daily,
    }


FILTERS = {"", "low", "unrated", "no_answer"}
MODES = {"", "course", "web"}


@router.get("/log")
def log_list(
    filter: str = Query(""),
    q: str = Query(""),
    mode: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_lecturer),
):
    if filter not in FILTERS:
        raise HTTPException(status_code=422, detail="filter: low | unrated | no_answer")
    if mode not in MODES:
        raise HTTPException(status_code=422, detail="mode: course | web")
    base = select(QaLog)
    if mode:
        base = base.where(QaLog.mode == mode)
    if filter == "low":
        base = base.where(QaLog.rating <= 2)
    elif filter == "unrated":
        base = base.where(QaLog.rating.is_(None), QaLog.status == "ok")
    elif filter == "no_answer":
        base = base.where(QaLog.no_answer.is_(True))
    if q.strip():
        base = base.where(func.py_lower(QaLog.question).contains(q.strip().lower()))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(
        base.options(joinedload(QaLog.user))
        .order_by(QaLog.created_at.desc(), QaLog.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = []
    for r in rows:
        item = qa_full(r, r.user.login if r.user else None)
        item.pop("sources")
        item.pop("web_sources")
        item.pop("mcp_error")
        item["answer"] = r.answer[:200] + ("…" if len(r.answer) > 200 else "")
        items.append(item)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/log/{qa_id}")
def log_item(qa_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require_lecturer)):
    r = db.get(QaLog, qa_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return qa_full(r, r.user.login if r.user else None)
