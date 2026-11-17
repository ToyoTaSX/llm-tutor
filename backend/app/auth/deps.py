"""Зависимости FastAPI: сессия БД, текущий пользователь, проверка роли."""
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import User
from .security import COOKIE_NAME, decode_token


@dataclass(frozen=True)
class CurrentUser:
    id: int
    login: str
    role: str  # student | lecturer

    @property
    def is_lecturer(self) -> bool:
        return self.role == "lecturer"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    token = request.cookies.get(COOKIE_NAME)
    user_id = decode_token(token, settings.jwt_secret) if token else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    # роль не хранится в БД: вычисляется из LECTURER_LOGINS на каждом запросе
    return CurrentUser(id=user.id, login=user.login, role=settings.role_for(user.login))


def require_lecturer(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_lecturer:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return user
