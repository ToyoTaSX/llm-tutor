"""Создание документов и демо-корпус."""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .config import Settings
from .models import AppMeta, Document
from .rag.chunker import decode_text

log = logging.getLogger(__name__)
SEED_TITLE = "Курс: Технологии нейронных сетей"


def create_document(
    db: Session, settings: Settings, title: str, filename: str, text: str, uploaded_by: int | None
) -> Document:
    """Сохраняет текст в /data/docs/<id>.txt (UTF-8) и создаёт запись со статусом indexing."""
    doc = Document(title=title, filename=filename, file_path="", chars=len(text), uploaded_by=uploaded_by)
    db.add(doc)
    db.flush()
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    path = settings.docs_dir / f"{doc.id}.txt"
    path.write_text(text, encoding="utf-8")
    doc.file_path = str(path)
    db.commit()
    return doc


def seed_demo_corpus(db: Session, settings: Settings) -> int | None:
    """Один раз за жизнь базы загружает демо-корпус (design D12). Возвращает id документа."""
    if db.get(AppMeta, "seed_done") is not None:
        return None
    seed: Path | None = settings.seed_file
    if seed is None or not seed.is_file():
        log.info("Демо-корпус не найден (%s), пропускаю", seed)
        return None
    text = decode_text(seed.read_bytes())
    doc = create_document(db, settings, SEED_TITLE, seed.name, text, uploaded_by=None)
    db.add(AppMeta(key="seed_done", value="1"))
    db.commit()
    log.info("Демо-корпус добавлен как документ %s", doc.id)
    return doc.id
