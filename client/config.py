"""Centralized configuration for bridge-client."""
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CLIENT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    """All settings loaded from .env (with sensible defaults)."""

    bridge_server_url: str = Field(
        default="http://host.zerotier.my.id:9877",
        alias="BRIDGE_SERVER_URL",
    )
    port: int = Field(default=8000, alias="PORT")
    host: str = Field(default="0.0.0.0", alias="HOST")
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")
    session_ttl_hours: int = Field(default=24, alias="SESSION_TTL_HOURS")
    session_refresh_interval_min: int = Field(default=60, alias="SESSION_REFRESH_INTERVAL_MIN")
    model_cache_ttl_min: int = Field(default=60, alias="MODEL_CACHE_TTL_MIN")
    api_key: Optional[str] = Field(default=None, alias="API_KEY")
    concurrency_limit: int = Field(default=2, alias="CONCURRENCY_LIMIT")
    request_timeout: int = Field(default=120, alias="REQUEST_TIMEOUT")
    max_prompt_chars: int = Field(default=10000, alias="MAX_PROMPT_CHARS")
    rate_limit_per_min: int = Field(default=60, alias="RATE_LIMIT_PER_MIN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    headless: bool = Field(default=True, alias="HEADLESS")
    debug: bool = Field(default=False, alias="DEBUG")
    session_dir: str = Field(default="sessions", alias="SESSION_DIR")
    model_cache_file: str = Field(default="model.json", alias="MODEL_CACHE_FILE")

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "ENCRYPTION_KEY is required. Generate a valid Fernet key with:\n"
                "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                "Then add it to your .env file."
            )
        try:
            Fernet(v.encode())
        except Exception as exc:
            raise ValueError(
                "ENCRYPTION_KEY is not a valid Fernet key. "
                "A valid key is 32 url-safe base64-encoded bytes."
            ) from exc
        return v

    model_config = ConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


settings = Settings()

SESSION_DIR = ROOT_DIR / settings.session_dir
MODEL_CACHE_FILE = ROOT_DIR / settings.model_cache_file
