"""Prometheus metrics registry for Shermos Bot."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Outbound events sent: labels by channel (telegram/whatsapp) and status (sent/failed/dead)
outbound_events_total = Counter(
    "shermos_outbound_events_total",
    "Outbound events processed by dispatcher.",
    ["channel", "status"],
)

# LLM call duration: histogram by status (success/timeout/error)
llm_call_duration_seconds = Histogram(
    "shermos_llm_call_duration_seconds",
    "Time spent in LLM calls.",
    ["status"],
    buckets=(0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120),
)

# Worker jobs in flight (decremented on completion/failure)
worker_jobs_in_flight = Gauge(
    "shermos_worker_jobs_in_flight",
    "Number of jobs currently being processed by the worker.",
    ["queue"],
)

# Manager notification failures
manager_notify_failures_total = Counter(
    "shermos_manager_notify_failures_total",
    "Failures when notifying managers (Telegram or WhatsApp).",
    ["channel"],
)


def render_metrics() -> tuple[bytes, str]:
    """Return (body, content_type) for a Prometheus scrape response."""
    return generate_latest(), CONTENT_TYPE_LATEST
