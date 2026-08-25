"""Worker configuration.

The Phase 0 worker does not connect to a database or pull jobs from a queue.
It only needs to know its own identity, the log level, and the environment
so that structured logs are useful in development and production.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = str
Environment = str


class Settings(BaseSettings):
    """Worker settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Field(
        default="development",
        description="Runtime environment. Affects logging verbosity.",
    )
    log_level: LogLevel = Field(
        default="INFO",
        description="Minimum log level. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    worker_name: str = Field(
        default="forge-worker",
        description="Identifier for this worker instance. Used in log context.",
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
