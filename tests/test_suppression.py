"""tests/test_suppression.py — Suppression and dedup tests"""
import pytest
from tests.conftest import *


def _push_context(client, category, merchant, trigger):
    client.post("/v1/context", json={
        "scope": "category", "context_id": category["slug"], "version": 1,
        "payload": category, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": merchant["merchant_id"], "version": 1,
        "payload": merchant, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": trigger["id"], "version": 1,
        "payload": trigger, "delivered_at": "2026-04-26T10:00:00Z"
    })


def test_same_suppression_key_not_duplicated(client):
    """Sending the same trigger twice → second tick should produce no actions."""
    _push_context(client, SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER_RESEARCH)

    r1 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [SAMPLE_TRIGGER_RESEARCH["id"]]
    })
    assert len(r1.json()["actions"]) >= 1

    r2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:01Z",
        "available_triggers": [SAMPLE_TRIGGER_RESEARCH["id"]]
    })
    assert r2.json()["actions"] == []


def test_hostile_merchant_suppressed_from_future_ticks(client):
    """After hostile reply, merchant should be suppressed for future ticks."""
    _push_context(client, SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER_RESEARCH)

    # First tick → get conversation ID
    r1 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [SAMPLE_TRIGGER_RESEARCH["id"]]
    })
    actions = r1.json()["actions"]
    assert actions

    conv_id = actions[0]["conversation_id"]
    mid = actions[0]["merchant_id"]

    # Hostile reply
    client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": mid,
        "from_role": "merchant",
        "message": "Stop messaging me this is spam!!",
        "received_at": "2026-04-26T10:01:00Z", "turn_number": 2,
    })

    # Push a new trigger for same merchant
    new_trg = dict(SAMPLE_TRIGGER_RESEARCH)
    new_trg["id"] = "trg_002_different_trigger"
    new_trg["suppression_key"] = "research:dentists:2026-W18"
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": new_trg["id"], "version": 1,
        "payload": new_trg, "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Second tick → should produce no actions (merchant suppressed)
    r2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:05:00Z",
        "available_triggers": [new_trg["id"]]
    })
    assert r2.json()["actions"] == []


def test_one_action_per_merchant_per_tick(client):
    """Multiple triggers for same merchant in one tick → only one action."""
    _push_context(client, SAMPLE_CATEGORY, SAMPLE_MERCHANT, SAMPLE_TRIGGER_RESEARCH)

    # Add a second trigger for the same merchant
    trg2 = dict(SAMPLE_TRIGGER_RESEARCH)
    trg2["id"] = "trg_002_perf_dip"
    trg2["kind"] = "perf_dip"
    trg2["suppression_key"] = "perf_dip:m_001:2026"
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": trg2["id"], "version": 1,
        "payload": trg2, "delivered_at": "2026-04-26T10:00:00Z"
    })

    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [SAMPLE_TRIGGER_RESEARCH["id"], trg2["id"]]
    })
    merchant_ids = [a["merchant_id"] for a in r.json()["actions"]]
    # One merchant → should appear at most once
    assert merchant_ids.count(SAMPLE_MERCHANT["merchant_id"]) <= 1
