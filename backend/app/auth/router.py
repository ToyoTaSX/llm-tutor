"""Регистрация, вход, выход, профиль (spec user-auth)."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, normalize_login
from ..models import User
from .deps import CurrentUser, current_user, get_db, get_settings
from .security import clear_session_cookie, create_token, hash_password, set_session_cookie, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_RE = re.compile(r"^[a-z0-9_.\-]{3,32}$")
MIN_PASSWORD = 6
MAX_PASSWORD = 128
BAD_CREDENTIALS = "Неверный логин или пароль"


class Credentials(BaseModel):
    login: str = ""
    password: str = ""


def _field_error(field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"field": field, "message": message})


def _user_out(user: User, settings: Settings) -> dict:
    return {"id": user.id, "login": user.login, "role": settings.role_for(user.login)}


def _start_session(response: Response, user: User, settings: Settings) -> None:
    token = create_token(user.id, settings.jwt_secret, settings.jwt_ttl_hours)
    set_session_cookie(response, token, settings.jwt_ttl_hours, settings.cookie_secure)


@router.post("/register")
def register(
    body: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    login = normalize_login(body.login)
    if not LOGIN_RE.match(login):
        raise _field_error("login", "Логин: 3–32 символа, латиница, цифры, «_», «.», «-»")
    if not (MIN_PASSWORD <= len(body.password) <= MAX_PASSWORD):
        raise _field_error("password", f"Пароль: от {MIN_PASSWORD} до {MAX_PASSWORD} символов")
    if db.scalar(select(User.id).where(User.login == login)) is not None:
        raise _field_error("login", "Логин уже занят")

    user = User(login=login, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # гонка двух одновременных регистраций
        db.rollback()
        raise _field_error("login", "Логин уже занят") from None
    _start_session(response, user, settings)
    return _user_out(user, settings)


@router.post("/login")
def login(
    body: Credentials,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = db.scalar(select(User).where(User.login == normalize_login(body.login)))
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise HTTPException(status_code=401, detail=BAD_CREDENTIALS)
    _start_session(response, user, settings)
    return _user_out(user, settings)


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return {"id": user.id, "login": user.login, "role": user.role}
