"""
app/main.py — FastAPI application with all 5 required endpoints.

Endpoints:
  GET  /v1/healthz    → liveness probe
  GET  /v1/metadata   → bot identity
  POST /v1/context    → receive context push
  POST /v1/tick       → proactive message send
  POST /v1/reply      → handle merchant/customer reply
"""

from __future__ import annotations
import time
import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.schemas import (
    ContextRequest, ContextAccepted, ContextRejected,
    TickRequest, TickAction, TickResponse,
    ReplyRequest, ReplyResponse,
    HealthzResponse, MetadataResponse,
)
from app.state import context_store, conversation_store
from app.engine.trigger_selector import select_triggers
from app.engine.composer import compose
from app.engine.conversation import handle_reply

app = FastAPI(title="Vera AI Bot", version=config.VERSION)

START_TIME = time.time()


# =============================================================================
# GET /v1/healthz
# =============================================================================

@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz():
    """Liveness probe. Judge polls every 60s; 3 consecutive failures = disqualified."""
    counts = context_store.count()
    return HealthzResponse(
        status="ok",
        uptime_seconds=int(time.time() - START_TIME),
        contexts_loaded=counts,
    )


# =============================================================================
# GET /v1/metadata
# =============================================================================

@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata():
    """Bot identity. Judge calls this once during warmup."""
    return MetadataResponse(
        team_name=config.TEAM_NAME,
        team_members=config.TEAM_MEMBERS,
        model=config.MODEL,
        approach=config.APPROACH,
        contact_email=config.CONTACT_EMAIL,
        version=config.VERSION,
        submitted_at=config.SUBMITTED_AT,
    )


# =============================================================================
# POST /v1/context
# =============================================================================

@app.post("/v1/context")
async def push_context(body: ContextRequest):
    """
    Receive a context push from the judge.

    Versioning rules (from testing-brief §2.1):
    - Same (context_id, version) → 409 stale_version (idempotent)
    - Higher version → 200 accepted (replaces atomically)
    - Lower version  → 409 stale_version
    """
    accepted, current_version = context_store.upsert(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
    )

    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if not accepted:
        # Already have same or higher version
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": current_version,
            },
        )

    ack_id = f"ack_{body.context_id}_v{body.version}"
    return ContextAccepted(accepted=True, ack_id=ack_id, stored_at=now_str)


# =============================================================================
# POST /v1/tick
# =============================================================================

@app.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest):
    """
    Periodic wake-up. Bot inspects available triggers, decides what to send.

    Returns up to MAX_ACTIONS_PER_TICK actions (empty list is valid).
    """
    if not body.available_triggers:
        return TickResponse(actions=[])

    # Select best trigger/context combinations
    candidates = select_triggers(body.available_triggers, body.now)

    actions: list[TickAction] = []

    for (trigger, merchant, category, customer) in candidates:
        try:
            composed = compose(category, merchant, trigger, customer)
        except Exception as e:
            # Never let a composition error kill the whole tick
            continue

        # Build deterministic conversation_id
        merchant_id = merchant.get("merchant_id", "m_unknown")
        trigger_id = trigger.get("id", "trg_unknown")
        customer_id = customer.get("customer_id") if customer else None

        # Make a stable, readable conversation_id
        conv_id = _make_conv_id(merchant_id, trigger_id)

        # Register this conversation for reply tracking
        sup_key = composed.get("suppression_key", "")
        conversation_store.create(
            conv_id=conv_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=trigger_id,
            suppression_key=sup_key,
        )

        action = TickAction(
            conversation_id=conv_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            send_as=composed.get("send_as", "vera"),
            trigger_id=trigger_id,
            template_name=composed.get("template_name", "vera_generic_v1"),
            template_params=composed.get("template_params", []),
            body=composed.get("body", ""),
            cta=composed.get("cta", "open_ended"),
            suppression_key=sup_key,
            rationale=composed.get("rationale", ""),
        )

        # Record the sent body for anti-repetition tracking
        conv_rec = conversation_store.get(conv_id)
        if conv_rec:
            conv_rec.add_turn("bot", action.body)

        actions.append(action)

    return TickResponse(actions=actions)


# =============================================================================
# POST /v1/reply
# =============================================================================

@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest):
    """
    Handle a reply from the simulated merchant/customer.

    Returns one of:
      {action: "send", body, cta, rationale}
      {action: "wait", wait_seconds, rationale}
      {action: "end", rationale}
    """
    result = handle_reply(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id or "",
        message=body.message,
        turn_number=body.turn_number,
        customer_id=body.customer_id,
    )

    return ReplyResponse(**result)


# =============================================================================
# Optional: POST /v1/teardown (judge may call at end of test)
# =============================================================================

@app.post("/v1/teardown")
async def teardown():
    """Wipe all state after test ends."""
    context_store.clear()
    conversation_store.clear()
    return {"wiped": True}


# =============================================================================
# Helpers
# =============================================================================

def _make_conv_id(merchant_id: str, trigger_id: str) -> str:
    """
    Generate a stable, readable conversation ID.
    Format: conv_{mid_short}_{trg_short}
    """
    mid_short = merchant_id.replace("_", "")[:12]
    trg_short = trigger_id.replace("_", "")[:14]
    return f"conv_{mid_short}_{trg_short}"
