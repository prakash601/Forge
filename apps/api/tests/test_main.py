"""App-startup security tests (Issue #82).

Fail-fast boot (agent wiring, prod example secrets) and the narrowed
CORS surface. Lifespan tests use a real test database; CORS needs only
the app.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


async def test_lifespan_fails_fast_on_agent_wiring_error(
    postgres_engine_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import Settings
    from app.db import session as db_session
    from app.main import create_app

    class _Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("wiring kaboom")

    monkeypatch.setattr("app.agents.archaeologist.ArchaeologistAgent", _Boom)
    db_session.init_engine(Settings(database_url=postgres_engine_url))
    try:
        app = create_app(Settings(database_url=postgres_engine_url))
        with pytest.raises(RuntimeError, match="refusing to boot"):
            async with app.router.lifespan_context(app):
                pass  # pragma: no cover — startup must raise first
    finally:
        await db_session.dispose_engine()


async def test_lifespan_refuses_prod_example_secrets() -> None:
    from app.config import Settings
    from app.main import _DEV_JWT_PLACEHOLDER, create_app

    settings = Settings(
        environment="production",
        jwt_secret=_DEV_JWT_PLACEHOLDER,
        database_url="postgresql+asyncpg://forge:forge@localhost:5432/forge",
    )
    app = create_app(settings)
    with pytest.raises(RuntimeError, match="dev-only example secrets"):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover — startup must raise first


def test_production_requires_database_url() -> None:
    import pytest

    from app.config import Settings

    with pytest.raises(Exception, match="DATABASE_URL is required in production"):
        Settings(environment="production", database_url=None, jwt_secret="x" * 32)
    assert Settings(environment="production", database_url="postgresql://x").database_url


def test_unknown_forge_env_vars_flags_typos() -> None:
    from app.config import unknown_forge_env_vars

    assert unknown_forge_env_vars({}) == []
    assert unknown_forge_env_vars({"FORGE_LLM_PROVIDER": "fake"}) == []
    assert unknown_forge_env_vars({"FORGE_LLM_PROVIDR": "fake"}) == ["FORGE_LLM_PROVIDR"]
    assert unknown_forge_env_vars({"PATH": "/bin", "HOME": "/root"}) == []


async def test_cors_preflight_has_no_wildcards() -> None:
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/users",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "*" not in response.headers["access-control-allow-methods"]
    assert "*" not in response.headers["access-control-allow-headers"]
