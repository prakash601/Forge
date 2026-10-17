# Todo fixture app

Reference repo for the Forge execution worker (`workers/execution`).
A tiny FastAPI Todo CRUD API with an in-memory store — no database,
no network, deterministic integer IDs.

## Layout

```text
fixtures/todo-app/
├── app/main.py        # FastAPI app (CRUD + /health)
├── tests/test_todos.py# deterministic pytest suite (<30s, offline)
├── requirements.txt   # pinned: fastapi / httpx / pytest only
└── .python-version    # pinned Python 3.11
```

Tests use `fastapi.testclient.TestClient` (httpx ASGI transport), so no
live server or network is involved.

## Shared venv (no pip during the loop)

The executor never installs packages at run time. Build the shared
venv **once** from the pinned requirements, then pass its path to the
executor as `ExecutorConfig.venv_path`:

```bash
python3.11 -m venv workers/execution/.venvs/todo-app
workers/execution/.venvs/todo-app/bin/pip install -r fixtures/todo-app/requirements.txt
```

Faster equivalent with `uv` (same result):

```bash
uv venv workers/execution/.venvs/todo-app --python 3.11
uv pip install --python workers/execution/.venvs/todo-app/bin/python \
  -r fixtures/todo-app/requirements.txt
```

`run_command` then uses this venv (its `bin/` is prepended to `PATH`)
to run `pytest`; per-run workspaces stay free of install side effects.
The worker test-suite builds/reuses this venv automatically via a
session-scoped fixture (see `workers/execution/tests/conftest.py`).
