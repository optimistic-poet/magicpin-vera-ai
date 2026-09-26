"""tests/test_tick.py — /v1/tick endpoint tests"""
import pytest
from tests.conftest import *


def _push_all(client, category=None, merchant=None, trigger=None, customer=None):
    """Helper: push all 4 context types."""
    cat = category or SAMPLE_CATEGORY
    merch = merchant or SAMPLE_MERCHANT
    trg = trigger or SAMPLE_TRIGGER_RESEARCH
    cust = customer or SAMPLE_CUSTOMER

    client.post("/v1/context", json={
        "scope": "category", "context_id": cat["slug"], "version": 1,
        "payload": cat, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": merch["merchant_id"], "version": 1,
        "payload": merch, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": trg["id"], "version": 1,
        "payload": trg, "delivered_at": "2026-04-26T10:00:00Z"
    })
    if cust:
        client.post("/v1/context", json={
            "scope": "customer", "context_id": cust["customer_id"], "version": 1,
            "payload": cust, "delivered_at": "2026-04-26T10:00:00Z"
        })
    return trg["id"]


def test_tick_empty_triggers(client):
    """Tick with no triggers should return empty actions."""
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:00:00Z", "available_triggers": []})
    assert r.status_code == 200
    assert r.json()["actions"] == []


def test_tick_unknown_trigger_ignored(client):
    """Trigger IDs with no pushed context should be silently ignored."""
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["non_existent_trigger_abc"]
    })
    assert r.status_code == 200
    assert r.json()["actions"] == []


def test_tick_returns_actions(client):
    """With full context pushed, tick should return at least one action."""
    tid = _push_all(client)
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    assert r.status_code == 200
    data = r.json()
    assert "actions" in data
    assert len(data["actions"]) >= 1


def test_tick_action_schema(client):
    """Every action must have all required fields."""
    tid = _push_all(client)
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    actions = r.json()["actions"]
    assert len(actions) >= 1
    action = actions[0]
    required = [
        "conversation_id", "merchant_id", "send_as",
        "trigger_id", "template_name", "template_params",
        "body", "cta", "suppression_key", "rationale"
    ]
    for field in required:
        assert field in action, f"Missing field: {field}"


def test_tick_no_urls_in_body(client):
    """Body must not contain URLs (penalty -3 per URL from judge)."""
    tid = _push_all(client)
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    for action in r.json()["actions"]:
        body = action["body"]
        assert "http://" not in body, f"URL found in body: {body[:80]}"
        assert "https://" not in body, f"URL found in body: {body[:80]}"


def test_tick_send_as_valid(client):
    """send_as must be 'vera' or 'merchant_on_behalf'."""
    tid = _push_all(client)
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    for action in r.json()["actions"]:
        assert action["send_as"] in ("vera", "merchant_on_behalf"), \
            f"Invalid send_as: {action['send_as']}"


def test_tick_cta_valid(client):
    """CTA must be a valid enum value."""
    valid_ctas = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
    tid = _push_all(client)
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    for action in r.json()["actions"]:
        assert action["cta"] in valid_ctas, f"Invalid CTA: {action['cta']}"


def test_tick_customer_trigger_merchant_on_behalf(client):
    """Customer-scoped trigger must produce send_as=merchant_on_behalf."""
    _push_all(client)  # sets up category, merchant, customer
    # Push recall trigger
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": SAMPLE_TRIGGER_RECALL["id"], "version": 1,
        "payload": SAMPLE_TRIGGER_RECALL, "delivered_at": "2026-04-26T10:00:00Z"
    })
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [SAMPLE_TRIGGER_RECALL["id"]]
    })
    actions = r.json()["actions"]
    if actions:
        assert actions[0]["send_as"] == "merchant_on_behalf"


def test_tick_suppression_after_first_send(client):
    """Same suppression_key should not produce a second action."""
    tid = _push_all(client)
    # First tick
    r1 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [tid]
    })
    acts1 = r1.json()["actions"]
    assert len(acts1) >= 1

    # Second tick with same trigger
    r2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:01Z",
        "available_triggers": [tid]
    })
    # Should be suppressed → empty
    assert r2.json()["actions"] == []


def test_tick_expired_trigger_ignored(client):
    """Expired trigger should not produce any action."""
    expired_trg = dict(SAMPLE_TRIGGER_RESEARCH)
    expired_trg["id"] = "trg_expired_001"
    expired_trg["expires_at"] = "2024-01-01T00:00:00Z"  # past date
    expired_trg["suppression_key"] = "expired_key_001"

    client.post("/v1/context", json={
        "scope": "category", "context_id": SAMPLE_CATEGORY["slug"], "version": 1,
        "payload": SAMPLE_CATEGORY, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": SAMPLE_MERCHANT["merchant_id"], "version": 1,
        "payload": SAMPLE_MERCHANT, "delivered_at": "2026-04-26T10:00:00Z"
    })
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": expired_trg["id"], "version": 1,
        "payload": expired_trg, "delivered_at": "2026-04-26T10:00:00Z"
    })

    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [expired_trg["id"]]
    })
    assert r.json()["actions"] == []
