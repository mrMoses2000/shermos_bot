"""Tests for /metrics endpoint and Prometheus instrumentation (step 5.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.utils.metrics import outbound_events_total, render_metrics


class FakePool:
    async def fetchrow(self, query, *args):
        return None

    async def fetchval(self, query, *args):
        return 1

    async def execute(self, query, *args):
        return "OK"


@pytest.fixture()
def api_client():
    app = create_app()
    app.state.pg_pool = FakePool()
    return TestClient(app, raise_server_exceptions=False)


def test_metrics_endpoint_status(api_client):
    """GET /metrics returns 200."""
    response = api_client.get("/metrics")
    assert response.status_code == 200


def test_metrics_content_type(api_client):
    """GET /metrics returns Prometheus text/plain content type."""
    response = api_client.get("/metrics")
    ct = response.headers.get("content-type", "")
    assert "text/plain" in ct


def test_metrics_contains_shermos_names(api_client):
    """/metrics output contains all shermos_ metric names."""
    response = api_client.get("/metrics")
    body = response.text
    assert "shermos_outbound_events_total" in body
    assert "shermos_llm_call_duration_seconds" in body
    assert "shermos_worker_jobs_in_flight" in body
    assert "shermos_manager_notify_failures_total" in body


def test_metrics_not_in_openapi_schema(api_client):
    """The /metrics route must not appear in OpenAPI docs."""
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert "/metrics" not in paths


def test_outbound_counter_increments():
    """outbound_events_total counter increments correctly."""
    body_before, _ = render_metrics()
    # Trigger a counter increment
    outbound_events_total.labels(channel="telegram", status="sent").inc()
    body_after, _ = render_metrics()
    # The 'sent' label for telegram must now appear in output
    assert b"shermos_outbound_events_total" in body_after
    assert b'channel="telegram"' in body_after
    assert b'status="sent"' in body_after


def test_render_metrics_returns_bytes_and_str():
    """render_metrics() returns (bytes, str) tuple."""
    body, ct = render_metrics()
    assert isinstance(body, bytes)
    assert isinstance(ct, str)
    assert "text/plain" in ct
