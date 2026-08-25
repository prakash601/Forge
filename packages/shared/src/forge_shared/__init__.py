"""Forge shared package.

This package is a Phase 0 placeholder. It will eventually hold:

- Shared Pydantic models used by the API and worker (e.g. Run, Task,
  AgentExecution, ToolCall).
- Cross-cutting constants and enums (state machine values, memory types,
  tool names).
- Shared logging or correlation helpers if they need to be re-used.

We intentionally do not introduce a meaningful surface area in Phase 0
because that would force design decisions that belong to later phases.
"""

__version__ = "0.1.0"
