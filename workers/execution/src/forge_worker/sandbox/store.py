"""In-memory ToolCall store for tests and single-process runs."""

from __future__ import annotations

from forge_worker.sandbox.protocols import ToolCallRecord


class InMemoryToolCallStore:
    """Append-only in-memory store. Not durable; the API persists ToolCalls."""

    def __init__(self) -> None:
        self._records: list[ToolCallRecord] = []

    def save(self, record: ToolCallRecord) -> None:
        self._records.append(record)

    def list_for_run(self, run_id: str) -> list[ToolCallRecord]:
        return [r for r in self._records if r.run_id == run_id]


__all__ = ["InMemoryToolCallStore"]
