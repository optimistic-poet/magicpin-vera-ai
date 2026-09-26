"""tests/test_context.py — /v1/context versioning and idempotency tests"""
import pytest
from tests.conftest import *


def test_context_push_accepted(client):
    r = client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists",
        "version": 1, "payload": {"slug": "dentists"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["accepted"] is True
    assert "ack_id" in data
    assert "stored_at" in data


def test_context_ack_id_format(client):
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001",
        "version": 3, "payload": {}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.json()["ack_id"] == "ack_m_001_v3"


def test_context_same_version_rejected(client):
    """Same (context_id, version) → 409 stale_version (idempotent)."""
    payload = {"scope": "merchant", "context_id": "m_001", "version": 1,
               "payload": {}, "delivered_at": "2026-04-26T10:00:00Z"}
    client.post("/v1/context", json=payload)   # first push OK
    r = client.post("/v1/context", json=payload)  # same version → 409
    assert r.status_code == 409
    data = r.json()
    assert data["accepted"] is False
    assert data["reason"] == "stale_version"
    assert data["current_version"] == 1


def test_context_lower_version_rejected(client):
    """Lower version → 409 stale_version."""
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001", "version": 5,
        "payload": {"name": "v5"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001", "version": 3,
        "payload": {"name": "v3"}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.status_code == 409
    data = r.json()
    assert data["current_version"] == 5


def test_context_higher_version_accepted(client):
    """Higher version → 200 accepted, replaces atomically."""
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001", "version": 1,
        "payload": {"v": 1}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001", "version": 2,
        "payload": {"v": 2}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True


def test_context_invalid_scope(client):
    """Invalid scope → validation error."""
    r = client.post("/v1/context", json={
        "scope": "invalid_scope", "context_id": "test", "version": 1,
        "payload": {}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.status_code == 422  # Pydantic validation error


def test_context_scopes_are_independent(client):
    """Same context_id but different scopes are independent keys."""
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {"v": 1}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    # Push same ID as merchant scope → should be accepted
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "dentists", "version": 1,
        "payload": {"v": 1}, "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True
