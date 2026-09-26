"""tests/test_health.py — /v1/healthz tests"""
import pytest
from tests.conftest import *


def test_healthz_returns_200(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200


def test_healthz_schema(client):
    r = client.get("/v1/healthz")
    data = r.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert "contexts_loaded" in data
    counts = data["contexts_loaded"]
    for scope in ("category", "merchant", "customer", "trigger"):
        assert scope in counts


def test_healthz_counts_after_push(client):
    # Initially zero
    r = client.get("/v1/healthz")
    assert r.json()["contexts_loaded"]["category"] == 0

    # Push one category
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists",
        "version": 1, "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
    })

    r = client.get("/v1/healthz")
    assert r.json()["contexts_loaded"]["category"] == 1


def test_healthz_fast(client):
    import time
    start = time.time()
    client.get("/v1/healthz")
    assert (time.time() - start) < 0.5  # must be very fast
