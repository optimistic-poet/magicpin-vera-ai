"""
app/state.py — In-memory stores for context + conversation state.

ContextStore  : persists pushed (scope, context_id) → {version, payload}
ConversationStore : tracks conversation turns, state, suppression
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional
import threading


class ContextStore:
    """Thread-safe in-memory context store with version tracking."""

    def __init__(self):
        self._data: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ read

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        """Return payload dict or None."""
        with self._lock:
            entry = self._data.get((scope, context_id))
            return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        with self._lock:
            entry = self._data.get((scope, context_id))
            return entry["version"] if entry else None

    def all_of_scope(self, scope: str) -> dict[str, dict]:
        """Return {context_id: payload} for every entry with this scope."""
        with self._lock:
            return {
                cid: entry["payload"]
                for (s, cid), entry in self._data.items()
                if s == scope
            }

    def count(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {"category": 0, "merchant": 0,
                                       "customer": 0, "trigger": 0}
            for (scope, _) in self._data:
                counts[scope] = counts.get(scope, 0) + 1
            return counts

    # ----------------------------------------------------------------- write

    def upsert(self, scope: str, context_id: str, version: int,
               payload: dict) -> tuple[bool, Optional[int]]:
        """
        Try to store payload at (scope, context_id, version).

        Returns (accepted, current_version):
          accepted=True  → stored successfully
          accepted=False → current_version is >= incoming version (stale)
        """
        with self._lock:
            key = (scope, context_id)
            existing = self._data.get(key)
            if existing and existing["version"] >= version:
                return False, existing["version"]
            self._data[key] = {"version": version, "payload": payload}
            return True, version

    def clear(self):
        with self._lock:
            self._data.clear()


class ConversationRecord:
    """Tracks the full state of one conversation."""

    # Conversation states
    STATE_NEW = "new"
    STATE_OUTREACH_SENT = "outreach_sent"
    STATE_ACTION_CONFIRMED = "action_confirmed"
    STATE_INFORMATION = "information"
    STATE_DEFERRED = "deferred"
    STATE_AUTO_REPLY_DETECTED = "auto_reply_detected"
    STATE_CLOSED = "closed"

    def __init__(self, conversation_id: str, merchant_id: str,
                 customer_id: Optional[str], trigger_id: str,
                 suppression_key: str):
        self.conversation_id = conversation_id
        self.merchant_id = merchant_id
        self.customer_id = customer_id
        self.trigger_id = trigger_id
        self.suppression_key = suppression_key
        self.state = self.STATE_OUTREACH_SENT
        self.turns: list[dict] = []               # [{role, body, ts}]
        self.auto_reply_count = 0
        self.sent_bodies: list[str] = []          # dedup
        self.created_at = datetime.now(timezone.utc)
        self.last_bot_body: Optional[str] = None

    def add_turn(self, role: str, body: str):
        self.turns.append({
            "role": role,
            "body": body,
            "ts": datetime.now(timezone.utc).isoformat()
        })
        if role == "bot":
            self.sent_bodies.append(body)
            self.last_bot_body = body

    @property
    def is_closed(self) -> bool:
        return self.state == self.STATE_CLOSED

    @property
    def turn_count(self) -> int:
        return len(self.turns)


class ConversationStore:
    """Thread-safe store for all ongoing conversations."""

    def __init__(self):
        self._convs: dict[str, ConversationRecord] = {}
        self._suppressed_keys: set[str] = set()   # suppression_key → skip
        self._suppressed_merchants: dict[str, float] = {}  # mid → suppress_until_ts
        self._merchant_auto_replies: dict[str, int] = {}
        self._lock = threading.Lock()

    def get_merchant_auto_reply_count(self, merchant_id: str) -> int:
        with self._lock:
            return self._merchant_auto_replies.get(merchant_id, 0)

    def record_merchant_auto_reply(self, merchant_id: str) -> int:
        with self._lock:
            count = self._merchant_auto_replies.get(merchant_id, 0) + 1
            self._merchant_auto_replies[merchant_id] = count
            return count

    def create(self, conv_id: str, merchant_id: str,
               customer_id: Optional[str], trigger_id: str,
               suppression_key: str) -> ConversationRecord:
        with self._lock:
            rec = ConversationRecord(
                conv_id, merchant_id, customer_id, trigger_id, suppression_key
            )
            self._convs[conv_id] = rec
            self._suppressed_keys.add(suppression_key)
            return rec

    def get(self, conv_id: str) -> Optional[ConversationRecord]:
        with self._lock:
            return self._convs.get(conv_id)

    def is_suppressed(self, suppression_key: str) -> bool:
        with self._lock:
            return suppression_key in self._suppressed_keys

    def is_merchant_suppressed(self, merchant_id: str) -> bool:
        """Check if merchant was suppressed (e.g. hostile reply)."""
        import time
        with self._lock:
            until = self._suppressed_merchants.get(merchant_id, 0)
            return time.time() < until

    def suppress_merchant(self, merchant_id: str, seconds: int = 86400 * 30):
        """Suppress all triggers for a merchant for N seconds."""
        import time
        with self._lock:
            self._suppressed_merchants[merchant_id] = time.time() + seconds

    def close_conversation(self, conv_id: str):
        with self._lock:
            rec = self._convs.get(conv_id)
            if rec:
                rec.state = ConversationRecord.STATE_CLOSED

    def get_active_for_merchant(self, merchant_id: str) -> list[ConversationRecord]:
        with self._lock:
            return [
                r for r in self._convs.values()
                if r.merchant_id == merchant_id and not r.is_closed
            ]

    def clear(self):
        with self._lock:
            self._convs.clear()
            self._suppressed_keys.clear()
            self._suppressed_merchants.clear()
            self._merchant_auto_replies.clear()


# Module-level singletons (shared across request handlers)
context_store = ContextStore()
conversation_store = ConversationStore()
