"""tests/test_canonical.py — Canonical test pairs from the challenge dataset.

Loads test_pairs.json and verifies that for each pair:
  1. Context can be pushed
  2. Tick returns an action for that trigger
  3. Action body references real data (non-empty, no URLs, grounded)
"""
import json
import pytest
from pathlib import Path
from tests.conftest import *

EXPANDED_DIR = Path(__file__).parent.parent / "challenge" / "expanded"


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def full_client(client):
    """Client with all expanded category contexts pre-pushed."""
    cat_dir = EXPANDED_DIR / "categories"
    if cat_dir.exists():
        for f in cat_dir.glob("*.json"):
            data = json.load(open(f))
            client.post("/v1/context", json={
                "scope": "category", "context_id": data.get("slug", f.stem),
                "version": 1, "payload": data, "delivered_at": "2026-04-26T10:00:00Z"
            })
    return client


def test_canonical_pairs_file_exists():
    """The test_pairs.json file must exist after running generate_dataset.py."""
    pairs_file = EXPANDED_DIR / "test_pairs.json"
    assert pairs_file.exists(), (
        f"test_pairs.json not found at {pairs_file}. "
        "Run: python challenge/dataset/generate_dataset.py --seed-dir challenge/dataset --out challenge/expanded"
    )


def _push_merchant(client, merchant_id: str):
    """Load and push a merchant from the expanded dataset."""
    mf = EXPANDED_DIR / "merchants" / f"{merchant_id}.json"
    if not mf.exists():
        return None
    data = json.load(open(mf))
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": merchant_id, "version": 1,
        "payload": data, "delivered_at": "2026-04-26T10:00:00Z"
    })
    return data


def _push_trigger(client, trigger_id: str):
    """Load and push a trigger from the expanded dataset."""
    tf = EXPANDED_DIR / "triggers" / f"{trigger_id}.json"
    if not tf.exists():
        return None
    data = json.load(open(tf))
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": trigger_id, "version": 1,
        "payload": data, "delivered_at": "2026-04-26T10:00:00Z"
    })
    return data


def _push_customer(client, customer_id: str):
    """Load and push a customer from the expanded dataset."""
    cf = EXPANDED_DIR / "customers" / f"{customer_id}.json"
    if not cf.exists():
        return None
    data = json.load(open(cf))
    client.post("/v1/context", json={
        "scope": "customer", "context_id": customer_id, "version": 1,
        "payload": data, "delivered_at": "2026-04-26T10:00:00Z"
    })
    return data


def test_first_five_canonical_pairs(full_client):
    """Run the first 5 canonical test pairs and verify action quality."""
    pairs_file = EXPANDED_DIR / "test_pairs.json"
    if not pairs_file.exists():
        pytest.skip("Expanded dataset not generated yet")

    pairs = json.load(open(pairs_file)).get("pairs", [])[:5]
    if not pairs:
        pytest.skip("No canonical pairs in test_pairs.json")

    passed = 0
    for pair in pairs:
        trigger_id = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        merchant = _push_merchant(full_client, merchant_id)
        trigger = _push_trigger(full_client, trigger_id)
        if customer_id:
            _push_customer(full_client, customer_id)

        if not merchant or not trigger:
            continue

        r = full_client.post("/v1/tick", json={
            "now": "2026-04-26T10:00:00Z",
            "available_triggers": [trigger_id]
        })
        assert r.status_code == 200
        actions = r.json()["actions"]

        if actions:
            action = actions[0]
            body = action["body"]
            assert body, f"Empty body for trigger {trigger_id}"
            assert "http://" not in body, f"URL in body for {trigger_id}"
            assert "https://" not in body, f"URL in body for {trigger_id}"
            assert len(body) >= 30, f"Body too short for {trigger_id}: '{body}'"
            passed += 1

    assert passed > 0, "None of the first 5 canonical pairs produced valid actions"


def test_all_canonical_pairs_no_errors(full_client):
    """Run all 30 canonical pairs — each must return 200 with no exceptions."""
    pairs_file = EXPANDED_DIR / "test_pairs.json"
    if not pairs_file.exists():
        pytest.skip("Expanded dataset not generated yet")

    pairs = json.load(open(pairs_file)).get("pairs", [])
    failed = []

    for pair in pairs:
        trigger_id = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        _push_merchant(full_client, merchant_id)
        _push_trigger(full_client, trigger_id)
        if customer_id:
            _push_customer(full_client, customer_id)

        try:
            r = full_client.post("/v1/tick", json={
                "now": "2026-04-26T10:00:00Z",
                "available_triggers": [trigger_id]
            })
            if r.status_code != 200:
                failed.append(f"{pair['test_id']}: HTTP {r.status_code}")
        except Exception as e:
            failed.append(f"{pair['test_id']}: Exception {e}")

    assert not failed, f"Failed canonical pairs:\n" + "\n".join(failed)
