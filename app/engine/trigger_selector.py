"""
app/engine/trigger_selector.py — Selects and prioritizes actionable triggers for a tick.

Pipeline:
  1. Filter triggers: only those in available_triggers list
  2. Filter expired triggers
  3. Filter suppressed triggers (suppression_key already used)
  4. Filter suppressed merchants
  5. Deduplicate by merchant (one action per merchant per tick per the API spec)
  6. Sort by urgency (desc), then by scope (merchant first, then customer)
  7. Return top N triggers
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from app.state import context_store, conversation_store
from app.engine.suppression import is_suppressed, is_merchant_suppressed


MAX_ACTIONS_PER_TICK = 20   # per judge spec
MAX_PER_MERCHANT = 1        # one action per merchant per tick (FAQ in testing-brief)


def select_triggers(
    available_trigger_ids: list[str],
    now: str,
) -> list[tuple[dict, dict, dict, Optional[dict]]]:
    """
    Returns list of (trigger, merchant, category, customer?) tuples
    ready for composition.
    """
    now_dt = _parse_dt(now)
    results = []
    seen_merchants: set[str] = set()

    # Sort available triggers by urgency desc first
    candidates = []
    for tid in available_trigger_ids:
        trg = context_store.get("trigger", tid)
        if not trg:
            continue
        candidates.append(trg)

    # Sort by urgency descending
    candidates.sort(key=lambda t: t.get("urgency", 1), reverse=True)

    for trg in candidates:
        # Check expiry
        expires = trg.get("expires_at", "")
        if expires and _parse_dt(expires) < now_dt:
            continue

        # Check suppression key
        sup_key = trg.get("suppression_key", "")
        if sup_key and is_suppressed(sup_key):
            continue

        merchant_id = trg.get("merchant_id")
        if not merchant_id:
            continue

        # One action per merchant per tick
        if merchant_id in seen_merchants:
            continue

        # Check merchant-level suppression (hostile opt-out)
        if is_merchant_suppressed(merchant_id):
            continue

        # Load merchant context
        merchant = context_store.get("merchant", merchant_id)
        if not merchant:
            continue

        # Load category context
        category_slug = merchant.get("category_slug", "")
        category = context_store.get("category", category_slug) or {}

        # Load customer context (if trigger is customer-scoped)
        customer = None
        customer_id = trg.get("customer_id")
        if customer_id:
            customer = context_store.get("customer", customer_id)

        results.append((trg, merchant, category, customer))
        seen_merchants.add(merchant_id)

        if len(results) >= MAX_ACTIONS_PER_TICK:
            break

    return results


def _parse_dt(dt_str: str) -> datetime:
    """Parse ISO datetime string, return UTC datetime."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        # Handle Z suffix
        s = dt_str.replace("Z", "+00:00")
        # Strip microseconds if needed for Python 3.10 compat
        if "." in s:
            s = s[:s.index(".") + 7] + s[s.index("+"):]
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)
