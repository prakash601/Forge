"""Application configuration.

Configuration is loaded from environment variables (and optionally a `.env`
file in development). The application fails fast on startup if a required
variable is missing — see `Settings` for the contract.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "test", "production"]

# The canonical `.env` lives at the repository root, but processes are often
# started with their working directory set to `apps/api/` (e.g. via
# `uv run --directory`). Resolve the path relative to this file so the
# environment loads consistently regardless of the caller's cwd. Real
# environment variables still take precedence over `.env` values.
_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from environment variables (and a local `.env` file
    when present). All fields are required unless they declare a default.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Runtime -----
    environment: Environment = Field(
        default="development",
        description="Runtime environment. Affects logging verbosity and CORS.",
    )
    log_level: LogLevel = Field(
        default="INFO",
        description="Minimum log level. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )

    # ----- API -----
    api_host: str = Field(default="0.0.0.0", description="HTTP listen host.")
    api_port: int = Field(default=8000, ge=1, le=65535, description="HTTP listen port.")
    cors_allow_origins: str = Field(
        default="http://localhost:3000",
        description=(
            "Comma-separated list of origins allowed by CORS. "
            "Use the property `cors_allow_origins_list` to read the parsed list."
        ),
    )

    # ----- Database -----
    database_url: str | None = Field(
        default=None,
        description=(
            "Database DSN. Required in production; optional in development "
            "and test, in which case callers must provide their own DSN "
            "before connecting."
        ),
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _coerce_cors(cls, value: object) -> object:
        # pydantic-settings can hand us either a string (from .env) or a
        # list (when the env var is JSON-decoded). Always return a string
        # so we can split it ourselves.
        if isinstance(value, list):
            return ",".join(str(v) for v in value)
        return value

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings instance.

    The result is cached so that environment loading and validation happen
    exactly once. Tests can clear the cache via `get_settings.cache_clear()`
    to force a re-read after mutating the environment.
    """
    return Settings()
