"""SANDBOX_* settings. The runner holds no application secrets (docs/24 §8)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    SANDBOX_RUNNER_TOKEN: SecretStr
    SANDBOX_RUNTIME: Literal["runc", "runsc"] = "runsc"
    SANDBOX_IMAGE: str = "nova-sandbox-python:dev"
    SANDBOX_MAX_CONCURRENCY: int = 8
    SANDBOX_DOCKER_HOST: str = "unix:///var/run/docker.sock"

    @model_validator(mode="after")
    def _prod_requires_gvisor(self) -> Settings:
        if self.APP_ENV in ("staging", "production") and self.SANDBOX_RUNTIME != "runsc":
            raise ValueError("SANDBOX_RUNTIME must be 'runsc' (gVisor) in staging/production")
        if len(self.SANDBOX_RUNNER_TOKEN.get_secret_value()) < 32:
            raise ValueError("SANDBOX_RUNNER_TOKEN must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
