"""Typed application settings loaded from the environment (docs/42_ENVIRONMENT_VARIABLES.md)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
# Repo root in a checkout (apps/api → ../..). In the production image the app lives at /app with
# no repo around it; env then comes only from the process environment.
REPO_ROOT = API_ROOT.parents[1] if len(API_ROOT.parents) > 1 else API_ROOT

EXAMPLE_SECRET_MARKERS = ("CHANGE_ME",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    APP_URL: str = "http://localhost:3000"
    APP_VERSION: str = "dev"
    LOG_LEVEL: str = "info"
    LOG_FORMAT: Literal["json", "console"] = "json"
    API_PROXY_SHARED_SECRET: SecretStr
    AUTH_SECRET: SecretStr
    AUTH_SECRET_PREVIOUS: SecretStr | None = None
    COOKIE_DOMAIN: str | None = None
    SESSION_TTL_DAYS: int = 30
    SESSION_IDLE_TIMEOUT_DAYS: int = 7
    ADMIN_BOOTSTRAP_EMAIL: str | None = None
    RATE_LIMIT_FALLBACK_DIVISOR: int = 4
    RATE_LIMIT_GLOBAL_IP_PER_MIN: int = 300  # raise only in load-test environments

    # Database / Redis
    DATABASE_URL: str = "postgresql+asyncpg://nova:nova@localhost:5432/nova"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5
    DATABASE_POOL_TIMEOUT: int = 10
    DATABASE_USE_PGBOUNCER: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"

    # Groq (sole LLM provider)
    # "user": each conversation uses the key its owner supplied (BYOK, app/ai/groq/keys.py).
    # "server": one server-held key for everyone.
    GROQ_KEY_MODE: Literal["user", "server"] = "user"
    GROQ_USER_KEY_TTL_HOURS: float = 720.0  # 30 days of inactivity; each use extends it
    GROQ_API_KEY: SecretStr | None = None
    GROQ_DEFAULT_MODEL: str | None = None
    GROQ_FAST_MODEL: str | None = None
    GROQ_VISION_MODEL: str | None = None
    GROQ_TIMEOUT_SECONDS: float = 60.0
    GROQ_MAX_RETRIES: int = 2
    GROQ_MAX_CONCURRENCY_PER_PROCESS: int = 64
    GROQ_BASE_URL: str | None = None
    MODEL_REGISTRY_PATH: str = "config/models.yaml"

    GROQ_STT_MODEL: str | None = None
    GROQ_TTS_MODEL: str | None = None
    GROQ_TTS_VOICES: str = ""
    GROQ_TTS_DEFAULT_VOICE: str | None = None
    VOICE_STT_PROVIDER: str | None = None
    VOICE_TTS_PROVIDER: str | None = None

    # Object storage / scanning (docs/18)
    S3_ENDPOINT: str | None = None
    S3_PUBLIC_ENDPOINT: str | None = None
    S3_REGION: str = "us-east-1"
    S3_BUCKET: str = "nova-dev"
    S3_ACCESS_KEY: SecretStr | None = None
    S3_SECRET_KEY: SecretStr | None = None
    S3_FORCE_PATH_STYLE: bool = True
    CLAMAV_ENABLED: bool = False
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    # Embeddings / RAG (docs/19–21)
    EMBEDDING_PROVIDER: str = "tei"
    EMBEDDING_ENDPOINT: str | None = None
    EMBEDDING_MODEL: str | None = None
    EMBEDDING_DIMENSIONS: int | None = None
    EMBEDDING_API_KEY: SecretStr | None = None
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_QUERY_PREFIX: str = ""
    EMBEDDING_DOCUMENT_PREFIX: str = ""
    RAG_SIM_THRESHOLD: float = 0.25
    RAG_TOP_K_VECTOR: int = 40
    RAG_TOP_K_FTS: int = 40
    RAG_FINAL_MAX_CHUNKS: int = 8
    RAG_MMR_LAMBDA: float = 0.7
    WORKER_EXTRACT_PROCESSES: int = 2

    # Tools (docs/22–24)
    WEB_SEARCH_PROVIDER: str = "none"
    SEARXNG_URL: str | None = None
    BRAVE_SEARCH_API_KEY: SecretStr | None = None
    WEB_SEARCH_GLOBAL_RPS: int = 10
    SANDBOX_RUNNER_URL: str | None = None
    SANDBOX_RUNNER_TOKEN: SecretStr | None = None

    # Payments (docs/31 §12)
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: SecretStr | None = None
    RAZORPAY_WEBHOOK_SECRET: SecretStr | None = None

    # Email
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_FROM: str = "NOVA AI <no-reply@localhost>"
    SMTP_USE_TLS: bool = False

    # Observability
    SENTRY_DSN: str | None = None
    SENTRY_ENVIRONMENT: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _blank_is_unset(cls, data: object) -> object:
        """`KEY=` in .env means "not set": drop blank values so defaults apply."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and v.strip() == "")}
        return data

    @model_validator(mode="after")
    def _validate_for_env(self) -> Settings:
        secure_env = self.APP_ENV in ("staging", "production")
        for name in ("AUTH_SECRET", "API_PROXY_SHARED_SECRET"):
            value: str = getattr(self, name).get_secret_value()
            if len(value) < 32 or any(m in value for m in EXAMPLE_SECRET_MARKERS):
                raise ValueError(f"{name} must be at least 32 random characters (not the example)")
        if secure_env:
            if not self.APP_URL.startswith("https://"):
                raise ValueError("APP_URL must be https in staging/production")
            if self.GROQ_BASE_URL:
                raise ValueError(
                    "GROQ_BASE_URL is test-only and must be unset in staging/production"
                )
            if self.GROQ_KEY_MODE == "server" and self.GROQ_API_KEY is None:
                raise ValueError("GROQ_API_KEY is required when GROQ_KEY_MODE=server")
        return self

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def cookie_secure(self) -> bool:
        return not (self.is_dev and self.APP_URL.startswith("http://localhost")) and (
            self.APP_ENV != "test"
        )

    @property
    def redis_prefix(self) -> str:
        return f"nova:{self.APP_ENV}:"

    @property
    def app_origin(self) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(self.APP_URL)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def groq_base_url(self) -> str:
        # Always explicit: the SDK would otherwise read GROQ_BASE_URL from os.environ itself.
        return self.GROQ_BASE_URL or "https://api.groq.com"

    model_registry_file: Path = Field(default=API_ROOT / "config" / "models.yaml", exclude=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    path = Path(s.MODEL_REGISTRY_PATH)
    s.model_registry_file = path if path.is_absolute() else API_ROOT / path
    return s
