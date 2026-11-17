"""Вопрос → источники → потоковый ответ (spec rag-qa, design D8), оценка ответа."""
import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import CurrentUser, current_user, get_db, get_settings
from ..config import Settings
from ..models import Document, QaLog, utcnow
from ..rag.prompt import is_no_answer

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["qa"])


class AskBody(BaseModel):
    question: str = ""
    mode: Literal["course", "web"] = "course"


class RatingBody(BaseModel):
    stars: int = Field(ge=1, le=5)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sources(chunks: list[dict]) -> list[dict]:
    return [
        {
            "n": n,
            "doc_id": c.get("doc_id"),
            "doc_title": c.get("doc_title"),
            "chunk_no": c.get("chunk_no"),
            "score": round(float(c.get("score", 0.0)), 6),
            "rank": n,
            "label": f"L{n}",
            "text": c.get("text", ""),
        }
        for n, c in enumerate(chunks, 1)
    ]


@router.post("/ask")
async def ask(
    body: AskBody,
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Введите вопрос")
    if len(question) > settings.max_question_chars:
        raise HTTPException(status_code=422, detail=f"Вопрос длиннее {settings.max_question_chars} символов")
    ready_ids = list(db.scalars(select(Document.id).where(Document.status == "ready")))
    if not ready_ids:
        raise HTTPException(status_code=409, detail="Лекции ещё не загружены")

    engine = request.app.state.engine
    sm = request.app.state.sessionmaker

    mode = body.mode

    def save(**fields) -> int:
        with sm() as s:
            rec = QaLog(user_id=user.id, question=question, mode=mode, **fields)
            s.add(rec)
            s.commit()
            return rec.id

    async def events():
        sources: list[dict] = []
        parts: list[str] = []
        usage: dict = {}
        web: dict | None = None
        timings: dict = {}

        def web_fields() -> dict:
            if web is None:
                return {}
            return {"web_query": web.get("query"), "web_sources": web.get("results") or [],
                    "mcp_status": web.get("status"), "mcp_error": web.get("error"), "t_mcp_ms": web.get("t_ms")}

        try:
            async for kind, val in engine.answer_events(question, ready_ids, mode):
                if kind == "web_status":
                    yield sse("web_status", val)
                elif kind == "sources":
                    timings["t_search_ms"] = val["t_search_ms"]
                    sources = _sources(val["chunks"])
                    yield sse("sources", sources)
                elif kind == "web_sources":
                    web = val
                    yield sse("web_sources", {"status": web["status"], "query": web.get("query"),
                                              "results": web.get("results") or [], "t_mcp_ms": web.get("t_ms")})
                elif kind == "token":
                    parts.append(val)
                    yield sse("token", {"t": val})
                elif kind == "usage":
                    usage = val
                elif kind == "timings":
                    timings = val
        except asyncio.CancelledError:
            # клиент ушёл: генерация прервана, сохраняем то, что успели
            answer = "".join(parts).strip()
            save(answer=answer, status="ok" if answer else "error", error=None if answer else "Клиент отключился",
                 no_answer=mode == "course" and is_no_answer(answer), sources=sources,
                 t_search_ms=timings.get("t_search_ms"), **web_fields())
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Ошибка при ответе на вопрос")
            msg = _user_error(e)
            save(answer="".join(parts).strip(), status="error", error=str(e)[:2000], sources=sources,
                 t_search_ms=timings.get("t_search_ms"), **web_fields())
            yield sse("error", {"message": msg})
            return
        answer = "".join(parts).strip()
        # признак «тема не разбиралась» — только для режима «Только курс» (в веб-режиме другой промпт)
        no_answer = mode == "course" and is_no_answer(answer)
        qa_id = save(
            answer=answer, status="ok", no_answer=no_answer, sources=sources,
            t_search_ms=timings.get("t_search_ms"), t_llm_ms=timings.get("t_llm_ms"),
            t_total_ms=timings.get("t_total_ms"),
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            **web_fields(),
        )
        yield sse("done", {"qa_id": qa_id, "no_answer": no_answer, "mode": mode,
                           "t_search_ms": timings.get("t_search_ms"), "t_llm_ms": timings.get("t_llm_ms"),
                           "t_mcp_ms": timings.get("t_mcp_ms"), "t_total_ms": timings.get("t_total_ms")})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _user_error(e: Exception) -> str:
    text = str(e).lower()
    if "connect" in text or "connection" in text:
        return "Языковая модель недоступна. Попробуйте позже."
    if "context" in text:
        return "Вопрос с найденными фрагментами не помещается в контекст модели."
    if "эмбеддинг" in text:
        return str(e)
    return "Не удалось получить ответ модели. Попробуйте ещё раз."


@router.post("/qa/{qa_id}/rating")
def rate(
    qa_id: int,
    body: RatingBody,
    user: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    rec = db.get(QaLog, qa_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Ответ не найден")
    if rec.user_id != user.id:
        raise HTTPException(status_code=403, detail="Можно оценивать только свои ответы")
    if rec.status != "ok":
        raise HTTPException(status_code=409, detail="Ответ с ошибкой нельзя оценить")
    rec.rating = body.stars
    rec.rated_at = utcnow()
    db.commit()
    return {"id": rec.id, "rating": rec.rating}
