"""In-memory Todo API fixture for the Forge execution worker.

Single-process, no database, deterministic integer IDs. Used as the
reference repo that ``LocalWorkspaceExecutor`` copies per run; the
agent loop's Tester runs its pytest suite through the executor.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="Forge Todo Fixture")


def _clean_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("title must not be blank")
    return cleaned


class Todo(BaseModel):
    id: int
    title: str
    done: bool = False


class TodoCreate(BaseModel):
    title: str = Field(min_length=1)
    done: bool = False

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, title: str) -> str:
        return _clean_title(title)


class TodoUpdate(BaseModel):
    title: str | None = None
    done: bool | None = None

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, title: str | None) -> str | None:
        return None if title is None else _clean_title(title)


_store: dict[int, Todo] = {}
_next_id: int = 1


def _reset_store() -> None:
    """Clear all todos. Used by tests to guarantee isolation."""
    global _next_id
    _store.clear()
    _next_id = 1


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/todos", status_code=201)
def create_todo(payload: TodoCreate) -> Todo:
    global _next_id
    todo = Todo(id=_next_id, title=payload.title, done=payload.done)
    _store[todo.id] = todo
    _next_id += 1
    return todo


@app.get("/todos")
def list_todos() -> list[Todo]:
    return [_store[key] for key in sorted(_store)]


@app.get("/todos/{todo_id}")
def get_todo(todo_id: int) -> Todo:
    try:
        return _store[todo_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="todo not found") from None


@app.patch("/todos/{todo_id}")
def update_todo(todo_id: int, payload: TodoUpdate) -> Todo:
    try:
        current = _store[todo_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="todo not found") from None
    updated = current.model_copy(
        update=payload.model_dump(exclude_unset=True, exclude_none=False)
    )
    _store[todo_id] = updated
    return updated


@app.delete("/todos/{todo_id}", status_code=204, response_class=Response)
def delete_todo(todo_id: int) -> Response:
    try:
        del _store[todo_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="todo not found") from None
    return Response(status_code=204)
