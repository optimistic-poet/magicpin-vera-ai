"""
app/engine/suppression.py — Suppression and deduplication logic.

Prevents the bot from:
  - Sending the same suppression_key twice
  - Replying on closed conversations
  - Sending the same body verbatim (anti-repetition penalty)
  - Spamming a merchant that sent hostility
"""

from __future__ import annotations
from app.state import conversation_store


def is_suppressed(suppression_key: str) -> bool:
    """Return True if this suppression_key was already used."""
    return conversation_store.is_suppressed(suppression_key)


def is_merchant_suppressed(merchant_id: str) -> bool:
    """Return True if the merchant was temporarily suppressed (hostile/opt-out)."""
    return conversation_store.is_merchant_suppressed(merchant_id)


def is_conversation_closed(conversation_id: str) -> bool:
    rec = conversation_store.get(conversation_id)
    return rec is not None and rec.is_closed


def would_repeat_body(conversation_id: str, new_body: str) -> bool:
    """Return True if new_body was already sent in this conversation (exact match)."""
    rec = conversation_store.get(conversation_id)
    if not rec:
        return False
    return new_body in rec.sent_bodies


def suppress_merchant_30d(merchant_id: str):
    """Suppress all future triggers for this merchant for 30 days."""
    conversation_store.suppress_merchant(merchant_id, seconds=86400 * 30)
