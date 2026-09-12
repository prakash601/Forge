"""Archaeologist output schema (AGENT_CONTRACTS §6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArchaeologistFindings(BaseModel):
    """Validated Archaeologist structured output.

    Field names follow AGENT_CONTRACTS §6 verbatim, with ``findings``
    kept as an alias for ``architecture_findings`` so both the issue
    text and the contract validate.
    """

    summary: str = Field(min_length=1)
    relevant_files: list[str] = Field(default_factory=list)
    architecture_findings: list[str] = Field(default_factory=list)
    findings: list[str] | None = None
    conventions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_focus: list[str] = Field(default_factory=list)

    def findings_list(self) -> list[str]:
        if self.findings is not None:
            return self.findings
        return self.architecture_findings


__all__ = [
    "ArchaeologistFindings",
    "DeveloperProposal",
    "DeveloperResult",
    "FileEdit",
    "Plan",
    "PlanStep",
]


class PlanStep(BaseModel):
    """One step of an implementation plan (AGENT_CONTRACTS §7)."""

    title: str = Field(min_length=1)
    detail: str = ""


class Plan(BaseModel):
    """Validated implementation plan (AGENT_CONTRACTS §7)."""

    goal: str = Field(min_length=1)
    approach: str = Field(min_length=1)
    steps: list[PlanStep] = Field(default_factory=list)
    files_to_change: list[str] = Field(default_factory=list)
    files_to_add: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rollback_strategy: str = ""


class FileEdit(BaseModel):
    """One workspace-local edit proposed by the Developer.

    ``mode="write"`` replaces the whole file with ``content``;
    ``mode="edit"`` replaces the first occurrence of ``old_text``
    with ``new_text``. Paths are workspace-relative.
    """

    path: str = Field(min_length=1)
    mode: str = Field(default="edit")
    content: str | None = None
    old_text: str | None = None
    new_text: str | None = None


class DeveloperProposal(BaseModel):
    """LLM output driving the Developer: edits plus §8 result fields."""

    edits: list[FileEdit] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    implementation_notes: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)


class DeveloperResult(BaseModel):
    """Persisted Developer output (AGENT_CONTRACTS §8)."""

    summary: str = Field(min_length=1)
    files_changed: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)
