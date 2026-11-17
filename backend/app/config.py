"""Настройки приложения из переменных окружения (.env)."""
from functools import cached_property
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_login(login: str) -> str:
    """Логины сравниваются без учёта регистра и пробелов по краям."""
    return (login or "").strip().lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # --- пользователи и сессии ---
    jwt_secret: str
    jwt_ttl_hours: int = 24
    lecturer_logins: str = ""
    cookie_secure: bool = False

    # --- пути ---
    data_dir: Path = Path("./data")
    models_path: Path = Path("./models")
    seed_file: Path | None = None

    # --- модели ---
    llm_file: str = "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
    emb_model_dir: str = "bge-m3"
    emb_device: str = "cuda"
    emb_batch: int = 16

    # --- сервисы ---
    llm_url: str = "http://localhost:8080"
    qdrant_url: str = "http://localhost:6333"
    collection: str = "lectures"

    # --- RAG ---
    top_k: int = 6
    candidates: int = 20
    rrf_k: int = 60
    chunk_chars: int = 1000
    overlap_chars: int = 200
    temperature: float = 0.2
    max_tokens: int = 1024

    # --- веб-поиск через MCP ---
    mcp_url: str = "https://mcp.tavily.com/mcp/"
    mcp_timeout_s: float = 10.0
    mcp_max_results: int = 3
    mcp_snippet_chars: int = 800
    mcp_search_tool: str = ""
    mcp_inject_test: bool = False
    tavily_api_key: SecretStr | None = None

    # --- ограничения ---
    max_question_chars: int = 2000
    max_upload_mb: int = 10

    @field_validator("jwt_secret")
    @classmethod
    def _secret_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("JWT_SECRET не задан: укажите длинную случайную строку в .env")
        return v

    @field_validator("tavily_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @property
    def mcp_api_key(self) -> str | None:
        return self.tavily_api_key.get_secret_value().strip() if self.tavily_api_key else None

    @cached_property
    def lecturer_set(self) -> frozenset[str]:
        return frozenset(normalize_login(x) for x in self.lecturer_logins.split(",") if x.strip())

    @property
    def emb_model_path(self) -> Path:
        return self.models_path / self.emb_model_dir

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    def role_for(self, login: str) -> str:
        return "lecturer" if normalize_login(login) in self.lecturer_set else "student"


def load_settings() -> Settings:
    """Создаёт настройки; при ошибке конфигурации завершает процесс с понятным сообщением."""
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as e:
        lines = [f"  {'.'.join(map(str, err['loc'])).upper()}: {err['msg']}" for err in e.errors()]
        raise SystemExit("Ошибка конфигурации (.env):\n" + "\n".join(lines)) from None
