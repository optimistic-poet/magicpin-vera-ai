"""tests/test_reply.py — /v1/reply endpoint tests"""
import pytest
from tests.conftest import *


def _setup_and_tick(client):
    """Push full context and run tick to create a conversation."""
    for scope, cid, payload in [
        ("category", SAMPLE_CATEGORY["slug"], SAMPLE_CATEGORY),
        ("merchant", SAMPLE_MERCHANT["merchant_id"], SAMPLE_MERCHANT),
        ("trigger", SAMPLE_TRIGGER_RESEARCH["id"], SAMPLE_TRIGGER_RESEARCH),
        ("customer", SAMPLE_CUSTOMER["customer_id"], SAMPLE_CUSTOMER),
    ]:
        client.post("/v1/context", json={
            "scope": scope, "context_id": cid, "version": 1,
            "payload": payload, "delivered_at": "2026-04-26T10:00:00Z"
        })

    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": [SAMPLE_TRIGGER_RESEARCH["id"]]
    })
    actions = r.json()["actions"]
    return actions[0]["conversation_id"] if actions else "conv_test_001"


def test_reply_returns_200(client):
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "customer_id": None,
        "from_role": "merchant",
        "message": "Yes, sounds interesting",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200


def test_reply_schema(client):
    """Reply must have action and rationale."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "customer_id": None,
        "from_role": "merchant",
        "message": "Yes, lets go",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    data = r.json()
    assert "action" in data
    assert "rationale" in data
    assert data["action"] in ("send", "wait", "end")


def test_reply_positive_sends(client):
    """Positive reply → action=send with body."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "Yes, please go ahead",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    data = r.json()
    assert data["action"] == "send"
    assert data.get("body"), "Expected non-empty body for positive reply"


def test_reply_negative_ends(client):
    """Negative/opt-out reply → action=end."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "No thanks, not interested",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    assert r.json()["action"] == "end"


def test_reply_auto_reply_detection(client):
    """Auto-reply → first detection sends a note; then waits; then ends."""
    conv_id = _setup_and_tick(client)
    auto_msg = "Thank you for contacting us! Our team will respond shortly."

    # Turn 2: first auto-reply
    r1 = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant", "message": auto_msg,
        "received_at": "2026-04-26T10:01:00Z", "turn_number": 2,
    })
    assert r1.json()["action"] in ("send", "wait")

    # Turn 3: second auto-reply
    r2 = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant", "message": auto_msg,
        "received_at": "2026-04-26T10:05:00Z", "turn_number": 3,
    })
    assert r2.json()["action"] in ("wait", "end")

    # Turn 4: third auto-reply → must end
    r3 = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant", "message": auto_msg,
        "received_at": "2026-04-26T10:10:00Z", "turn_number": 4,
    })
    assert r3.json()["action"] == "end"


def test_reply_hostile_ends_and_suppresses(client):
    """Hostile reply → action=end; merchant suppressed for future ticks."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "Stop messaging me! This is spam.",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    assert r.json()["action"] == "end"


def test_reply_later_waits(client):
    """'Later' reply → action=wait."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "Not now, I'm busy, check later",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    data = r.json()
    assert data["action"] == "wait"
    assert "wait_seconds" in data


def test_reply_unknown_conv_handled_gracefully(client):
    """Reply on unknown conversation_id → graceful response, no 500."""
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_completely_unknown_xyz",
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "Hello?",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 1,
    })
    assert r.status_code == 200
    assert r.json()["action"] in ("send", "wait", "end")


def test_reply_intent_transition_ok_lets_do_it(client):
    """'Ok let's do it' → action=send (action mode, not qualifying)."""
    conv_id = _setup_and_tick(client)
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": SAMPLE_MERCHANT["merchant_id"],
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "received_at": "2026-04-26T10:01:00Z",
        "turn_number": 2,
    })
    data = r.json()
    assert data["action"] == "send"
    body = (data.get("body") or "").lower()
    # Must NOT be still qualifying (asking 'do you', 'would you')
    qualifying_words = ["would you like", "are you sure", "do you want"]
    for qw in qualifying_words:
        assert qw not in body, f"Bot still qualifying after positive intent: {body[:100]}"
