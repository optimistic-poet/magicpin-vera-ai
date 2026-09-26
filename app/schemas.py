"""
app/schemas.py — Exact Pydantic models matching the judge API contract.
Reference: challenge-testing-brief.md §2 and api-call-examples.md
"""

from __future__ import annotations
from typing import Any, Optional, List
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# /v1/context
# ---------------------------------------------------------------------------

class ContextRequest(BaseModel):
    scope: str          # "category" | "merchant" | "customer" | "trigger"
    context_id: str     # slug, merchant_id, customer_id, trigger_id
    version: int
    payload: dict[str, Any]
    delivered_at: str

    @field_validator("scope")
    @classmethod
    def valid_scope(cls, v: str) -> str:
        allowed = {"category", "merchant", "customer", "trigger"}
        if v not in allowed:
            raise ValueError(f"scope must be one of {allowed}")
        return v


class ContextAccepted(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str


class ContextRejected(BaseModel):
    accepted: bool = False
    reason: str
    current_version: Optional[int] = None
    details: Optional[str] = None


# ---------------------------------------------------------------------------
# /v1/tick
# ---------------------------------------------------------------------------

class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = []


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: str                    # "vera" | "merchant_on_behalf"
    trigger_id: str
    template_name: str
    template_params: List[str]
    body: str
    cta: str                        # "open_ended" | "binary_yes_no" | "multi_choice_slot" | "none"
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[TickAction] = []


# ---------------------------------------------------------------------------
# /v1/reply
# ---------------------------------------------------------------------------

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str                  # "merchant" | "customer"
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: str                     # "send" | "wait" | "end"
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


# ---------------------------------------------------------------------------
# /v1/healthz
# ---------------------------------------------------------------------------

class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


# ---------------------------------------------------------------------------
# /v1/metadata
# ---------------------------------------------------------------------------

class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
