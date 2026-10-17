"""Worker configuration.

The Phase 0 worker does not connect to a database or pull jobs from a queue.
It only needs to know its own identity, the log level, and the environment
so that structured logs are useful in development and production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
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
        populate_by_name=True,
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

    # ----- Sandbox (Phase 4, Issue #017, decided in #58) -----
    sandbox_backend: Literal["local", "docker"] = Field(
        default="local",
        validation_alias=AliasChoices("sandbox_backend", "FORGE_SANDBOX_BACKEND"),
        description="Executor backend: local (host subprocess) or docker (ephemeral containers).",
    )
    sandbox_image: str = Field(
        default="forge-sandbox:0.1.0",
        validation_alias=AliasChoices("sandbox_image", "FORGE_SANDBOX_IMAGE"),
        description="Sandbox image (infra/docker/sandbox.Dockerfile, digest-pinned in prod).",
    )
    sandbox_cpus: float = Field(
        default=1.0,
        gt=0,
        validation_alias=AliasChoices("sandbox_cpus", "FORGE_SANDBOX_CPUS"),
        description="CPU limit per command container.",
    )
    sandbox_memory_mb: int = Field(
        default=512,
        gt=0,
        validation_alias=AliasChoices("sandbox_memory_mb", "FORGE_SANDBOX_MEMORY_MB"),
        description="RAM limit (no swap) per command container.",
    )
    sandbox_pids_limit: int = Field(
        default=128,
        gt=0,
        validation_alias=AliasChoices("sandbox_pids_limit", "FORGE_SANDBOX_PIDS_LIMIT"),
        description="PID limit per command container.",
    )
    sandbox_workspace_quota_mb: int = Field(
        default=512,
        gt=0,
        validation_alias=AliasChoices(
            "sandbox_workspace_quota_mb", "FORGE_SANDBOX_WORKSPACE_QUOTA_MB"
        ),
        description="Host-side workspace disk quota (MB) checked before each command.",
    )
    sandbox_network: str = Field(
        default="none",
        validation_alias=AliasChoices("sandbox_network", "FORGE_SANDBOX_NETWORK"),
        description="Container network mode (default-deny).",
    )
    sandbox_pull_policy: Literal["never", "missing", "always"] = Field(
        default="never",
        validation_alias=AliasChoices("sandbox_pull_policy", "FORGE_SANDBOX_PULL_POLICY"),
        description="Image pull policy: 'never' (prod), 'missing', or 'always'.",
    )
    run_max_seconds: float = Field(
        default=1800.0,
        gt=0,
        validation_alias=AliasChoices("run_max_seconds", "FORGE_RUN_MAX_SECONDS"),
        description="Wall-clock budget per run (enforced by the Phase 5 worker loop).",
    )
    run_max_commands: int = Field(
        default=100,
        gt=0,
        validation_alias=AliasChoices("run_max_commands", "FORGE_RUN_MAX_COMMANDS"),
        description="Command budget per run (enforced by the Phase 5 worker loop).",
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
