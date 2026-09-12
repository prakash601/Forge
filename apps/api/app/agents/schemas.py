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


__all__ = ["ArchaeologistFindings"]
