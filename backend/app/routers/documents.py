"""Управление лекциями (spec lecture-documents). Только для лектора."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from starlette.concurrency import run_in_threadpool

from ..auth.deps import CurrentUser, get_db, get_settings, require_lecturer
from ..config import Settings
from ..documents_service import create_document
from ..models import Document, iso
from ..rag.chunker import DecodeError, decode_text

router = APIRouter(prefix="/api/documents", tags=["documents"])


def doc_out(d: Document) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "filename": d.filename,
        "status": d.status,
        "error": d.error,
        "chunks_count": d.chunks_count,
        "chars": d.chars,
        "uploaded_by": d.uploader.login if d.uploader else None,
        "created_at": iso(d.created_at),
        "indexed_at": iso(d.indexed_at),
    }


@router.get("")
def list_documents(db: Session = Depends(get_db), _: CurrentUser = Depends(require_lecturer)):
    docs = db.scalars(select(Document).options(joinedload(Document.uploader)).order_by(Document.created_at.desc()))
    return [doc_out(d) for d in docs]


def _validate(filename: str, raw: bytes, max_mb: int) -> str:
    if not filename.lower().endswith(".txt"):
        raise ValueError("Поддерживаются только файлы .txt")
    if len(raw) > max_mb * 1024 * 1024:
        raise ValueError(f"Файл больше {max_mb} МБ")
    try:
        text = decode_text(raw)
    except DecodeError as e:
        raise ValueError(str(e)) from None
    if not text.strip():
        raise ValueError("Файл пустой")
    return text


@router.post("")
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    titles: list[str] | None = Form(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: CurrentUser = Depends(require_lecturer),
):
    created, errors = [], []
    for i, f in enumerate(files):
        filename = Path(f.filename or "lecture.txt").name
        raw = await f.read(settings.max_upload_mb * 1024 * 1024 + 1)
        try:
            text = _validate(filename, raw, settings.max_upload_mb)
        except ValueError as e:
            errors.append({"filename": filename, "message": str(e)})
            continue
        title = (titles[i] if titles and i < len(titles) else "").strip() or Path(filename).stem
        doc = await run_in_threadpool(create_document, db, settings, title[:255], filename, text, user.id)
        request.app.state.indexer.enqueue(doc.id)
        created.append(doc.id)
    if not created:
        raise HTTPException(status_code=422, detail={"message": "Ни один файл не загружен", "errors": errors})
    docs = db.scalars(select(Document).options(joinedload(Document.uploader)).where(Document.id.in_(created)))
    return {"created": [doc_out(d) for d in docs], "errors": errors}


def _get(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return doc


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: int, request: Request, db: Session = Depends(get_db), _: CurrentUser = Depends(require_lecturer)
):
    doc = _get(db, doc_id)
    path = Path(doc.file_path)
    db.delete(doc)
    db.commit()
    await run_in_threadpool(request.app.state.store.delete_by_doc, doc_id)
    path.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/{doc_id}/reindex")
def reindex_document(
    doc_id: int, request: Request, db: Session = Depends(get_db), _: CurrentUser = Depends(require_lecturer)
):
    doc = _get(db, doc_id)
    if doc.status == "indexing":
        raise HTTPException(status_code=409, detail="Документ уже индексируется")
    doc.status = "indexing"
    doc.error = None
    db.commit()
    request.app.state.indexer.enqueue(doc.id)
    db.refresh(doc)
    return doc_out(doc)
