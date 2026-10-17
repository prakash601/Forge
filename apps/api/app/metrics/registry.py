"""Prometheus metrics for the Forge API (Phase 4, Issue #019).

Thin bridge over ``prometheus_client``:

* HTTP request counts + run lifecycle counters live here and are
  incremented at the call sites (API endpoints, orchestrator).
* The pre-existing in-process LLM counters (``app.llm.metrics``) are
  exported as gauges at scrape time — no dual-write drift.
* ``runs by state`` is a scrape-time DB gauge (best-effort: skipped
  when the database is unreachable so ``/metrics`` still serves).

Label discipline: only low-cardinality labels (event names, actors,
states, providers, models). Never run ids, user ids, or paths with
ids (the middleware uses route templates).
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "forge_http_requests_total",
    "HTTP requests by method, route template, and status.",
    ["method", "route", "status"],
    registry=REGISTRY,
)

RUNS_CREATED_TOTAL = Counter(
    "forge_runs_created_total",
    "Runs created via the API.",
    registry=REGISTRY,
)

RUN_EVENTS_TOTAL = Counter(
    "forge_run_events_total",
    "Run events applied, by event and approval actor.",
    ["event", "approved_by"],
    registry=REGISTRY,
)

RUN_DURATION_SECONDS = Histogram(
    "forge_run_duration_seconds",
    "Wall-clock seconds from run creation to a terminal state.",
    registry=REGISTRY,
)

PR_PUBLICATIONS_TOTAL = Counter(
    "forge_pr_publications_total",
    "PR publication attempts by outcome (published/skipped/failed).",
    ["outcome"],
    registry=REGISTRY,
)

RUNS_BY_STATE = Gauge(
    "forge_runs_current_by_state",
    "Current runs by state (scrape-time DB read; absent when DB is down).",
    ["state"],
    registry=REGISTRY,
)

LLM_CALLS_TOTAL = Gauge(
    "forge_llm_calls_total",
    "LLM calls by provider, model, and outcome (bridge over app.llm.metrics).",
    ["provider", "model", "outcome"],
    registry=REGISTRY,
)

LLM_TOKENS_TOTAL = Gauge(
    "forge_llm_tokens_total",
    "LLM tokens by provider, model, and direction (bridge over app.llm.metrics).",
    ["provider", "model", "direction"],
    registry=REGISTRY,
)


def record_http_request(*, method: str, route: str, status: int) -> None:
    """Increment the HTTP request counter."""
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=str(status)).inc()


def record_run_created() -> None:
    """Increment the run-creation counter."""
    RUNS_CREATED_TOTAL.inc()


def record_run_event(*, event: str, approved_by: str | None) -> None:
    """Increment the run-event counter (actor ``human``/``policy``/``none``)."""
    RUN_EVENTS_TOTAL.labels(event=event, approved_by=approved_by or "none").inc()


def observe_run_duration(seconds: float) -> None:
    """Observe a terminal run's wall-clock duration."""
    RUN_DURATION_SECONDS.observe(max(0.0, seconds))


def record_pr_publication(*, outcome: str) -> None:
    """Count a PR publication outcome (published/skipped/failed)."""
    PR_PUBLICATIONS_TOTAL.labels(outcome=outcome).inc()


def render_latest() -> tuple[bytes, str]:
    """Render the Prometheus exposition (refreshing bridge gauges first)."""
    from app.llm import metrics as llm_metrics

    snapshot = llm_metrics.get_counters()
    for key, value in snapshot.items():
        if not key:
            continue
        name = key[0]
        if name == llm_metrics.CALLS_TOTAL and len(key) == 4:
            _, provider, model, outcome = key
            LLM_CALLS_TOTAL.labels(provider=provider, model=model, outcome=outcome).set(value)
        elif name == llm_metrics.INPUT_TOKENS_TOTAL and len(key) == 3:
            _, provider, model = key
            LLM_TOKENS_TOTAL.labels(provider=provider, model=model, direction="input").set(value)
        elif name == llm_metrics.OUTPUT_TOKENS_TOTAL and len(key) == 3:
            _, provider, model = key
            LLM_TOKENS_TOTAL.labels(provider=provider, model=model, direction="output").set(value)
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "HTTP_REQUESTS_TOTAL",
    "LLM_CALLS_TOTAL",
    "LLM_TOKENS_TOTAL",
    "PR_PUBLICATIONS_TOTAL",
    "RUNS_BY_STATE",
    "RUNS_CREATED_TOTAL",
    "RUN_DURATION_SECONDS",
    "RUN_EVENTS_TOTAL",
    "observe_run_duration",
    "record_http_request",
    "record_pr_publication",
    "record_run_created",
    "record_run_event",
    "render_latest",
]
