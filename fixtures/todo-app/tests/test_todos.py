"""Todo-app fixture tests.

Deterministic, offline (httpx ASGI transport via TestClient — no live
network), and fast (<30s). Each test gets a fresh in-memory store via
the autouse ``clean_store`` fixture.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import _reset_store, app


@pytest.fixture(autouse=True)
def clean_store() -> Iterator[None]:
    _reset_store()
    yield
    _reset_store()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_todo(client: TestClient) -> None:
    response = client.post("/todos", json={"title": "Write tests"})
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["title"] == "Write tests"
    assert body["done"] is False


def test_create_todo_requires_title(client: TestClient) -> None:
    response = client.post("/todos", json={})
    assert response.status_code == 422


def test_create_todo_rejects_blank_title(client: TestClient) -> None:
    response = client.post("/todos", json={"title": "   "})
    assert response.status_code == 422


def test_list_todos_empty(client: TestClient) -> None:
    assert client.get("/todos").json() == []


def test_list_todos_returns_creation_order(client: TestClient) -> None:
    client.post("/todos", json={"title": "first"})
    client.post("/todos", json={"title": "second"})
    client.post("/todos", json={"title": "third"})
    titles = [todo["title"] for todo in client.get("/todos").json()]
    assert titles == ["first", "second", "third"]


def test_get_todo(client: TestClient) -> None:
    created = client.post("/todos", json={"title": "Read me"}).json()
    response = client.get(f"/todos/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_todo_is_404(client: TestClient) -> None:
    response = client.get("/todos/999")
    assert response.status_code == 404


def test_update_todo_title_and_done(client: TestClient) -> None:
    created = client.post("/todos", json={"title": "Draft"}).json()
    response = client.patch(
        f"/todos/{created['id']}", json={"title": "Final", "done": True}
    )
    assert response.status_code == 200
    assert response.json() == {"id": created["id"], "title": "Final", "done": True}


def test_update_missing_todo_is_404(client: TestClient) -> None:
    response = client.patch("/todos/999", json={"done": True})
    assert response.status_code == 404


def test_delete_todo(client: TestClient) -> None:
    created = client.post("/todos", json={"title": "Temporary"}).json()
    response = client.delete(f"/todos/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/todos/{created['id']}").status_code == 404
    assert client.get("/todos").json() == []


def test_delete_missing_todo_is_404(client: TestClient) -> None:
    response = client.delete("/todos/999")
    assert response.status_code == 404


def test_ids_are_stable_and_unique(client: TestClient) -> None:
    first = client.post("/todos", json={"title": "one"}).json()
    second = client.post("/todos", json={"title": "two"}).json()
    assert first["id"] != second["id"]
    client.delete(f"/todos/{first['id']}")
    third = client.post("/todos", json={"title": "three"}).json()
    assert third["id"] not in (first["id"], second["id"])
