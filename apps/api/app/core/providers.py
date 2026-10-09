"""Shared provider-factory helper (Issue #85).

The LLM and embedding registries had the same normalize/dispatch/
reject shape; both now funnel through :func:`pick_provider` so the
``ValueError`` contract lives in one place.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

T = TypeVar("T")


def pick_provider(provider_name: str, kind: str, builders: Mapping[str, Callable[[], T]]) -> T:
    """Return the provider built for ``provider_name`` (case-insensitive).

    Raises:
        ValueError: unknown provider name (``unknown <kind> provider``).
    """
    normalized = provider_name.strip().lower()
    try:
        build = builders[normalized]
    except KeyError:
        raise ValueError(f"unknown {kind} provider: {provider_name!r}") from None
    return build()


__all__ = ["pick_provider"]
