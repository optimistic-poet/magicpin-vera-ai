"""
app/engine/conversation.py — Conversation state machine + reply handler.

Given an incoming merchant/customer reply, decide:
  - send (with new body + cta)
  - wait (with wait_seconds)
  - end (with rationale)

State machine transitions:
  NEW → OUTREACH_SENT
  OUTREACH_SENT + positive    → ACTION_CONFIRMED → respond with action
  OUTREACH_SENT + negative    → CLOSED
  OUTREACH_SENT + auto_reply  → AUTO_REPLY_DETECTED (wait, then end after 2x)
  OUTREACH_SENT + question    → INFORMATION
  OUTREACH_SENT + hostile     → CLOSED (suppress merchant 30d)
  OUTREACH_SENT + later       → DEFERRED (wait 30min)
  OUTREACH_SENT + curveball   → stay in OUTREACH_SENT (decline, redirect)
  AUTO_REPLY_DETECTED again   → end after 3x auto-replies total
"""

from __future__ import annotations
from typing import Optional
from app.state import conversation_store, context_store, ConversationRecord
from app.utils.detection import classify_intent, is_auto_reply, is_out_of_scope
from app.engine.suppression import suppress_merchant_30d


def handle_reply(
    conversation_id: str,
    merchant_id: str,
    message: str,
    turn_number: int,
    customer_id: Optional[str] = None,
) -> dict:
    """
    Main reply handler. Returns a dict matching ReplyResponse fields.
    """
    rec = conversation_store.get(conversation_id)

    # If conversation_id not tracked yet, find active conversation for merchant or create one
    if rec is None:
        active_convs = conversation_store.get_active_for_merchant(merchant_id)
        if active_convs:
            rec = active_convs[-1]
        else:
            rec = conversation_store.create(
                conv_id=conversation_id,
                merchant_id=merchant_id,
                customer_id=customer_id,
                trigger_id="",
                suppression_key=f"direct:{merchant_id}:{conversation_id}",
            )

    intent = classify_intent(message)

    if rec.is_closed:
        if intent not in ("positive", "question"):
            return {"action": "end", "rationale": "Conversation already closed."}
        # If merchant has renewed interest or questions, re-open conversation
        rec.state = ConversationRecord.STATE_OUTREACH_SENT
    rec.add_turn("merchant", message)

    # Route by intent
    if intent == "auto_reply":
        return _handle_auto_reply(rec, merchant_id)
    elif intent == "hostile":
        return _handle_hostile(rec, merchant_id)
    elif intent == "positive":
        return _handle_positive(rec, merchant_id)
    elif intent == "negative":
        return _handle_negative(rec, merchant_id)
    elif intent == "later":
        return _handle_later(rec, merchant_id)
    elif intent == "question":
        return _handle_question(rec, merchant_id, message)
    else:
        # unknown / curveball
        if is_out_of_scope(message):
            return _handle_out_of_scope(rec, merchant_id, message)
        return _handle_unknown_intent(rec, merchant_id, message)


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

def _handle_auto_reply(rec: ConversationRecord, merchant_id: str) -> dict:
    rec.auto_reply_count += 1
    merchant_auto_count = conversation_store.record_merchant_auto_reply(merchant_id)
    count = max(rec.auto_reply_count, merchant_auto_count)

    if count == 1:
        # First auto-reply: try once more with a note
        body = (
            "Looks like an auto-reply 😊 "
            "When the owner sees this, just reply 'Yes' to continue. "
            "No action needed right now."
        )
        rec.state = ConversationRecord.STATE_AUTO_REPLY_DETECTED
        rec.add_turn("bot", body)
        return {
            "action": "send",
            "body": body,
            "cta": "binary_yes_no",
            "rationale": "Detected auto-reply (turn 1); one nudge sent to flag for owner.",
        }
    elif count == 2:
        # Second auto-reply: back off
        return {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Same auto-reply twice in a row → owner not at phone. Wait 24h.",
        }
    else:
        # Third+ auto-reply: end conversation
        rec.state = ConversationRecord.STATE_CLOSED
        conversation_store.close_conversation(rec.conversation_id)
        return {
            "action": "end",
            "rationale": (
                f"Auto-reply {count}x in a row. "
                "No real engagement signal. Closing conversation."
            ),
        }


def _handle_hostile(rec: ConversationRecord, merchant_id: str) -> dict:
    rec.state = ConversationRecord.STATE_CLOSED
    conversation_store.close_conversation(rec.conversation_id)
    suppress_merchant_30d(merchant_id)
    return {
        "action": "end",
        "rationale": (
            "Merchant expressed frustration/opt-out. "
            "Closing conversation and suppressing all triggers for 30 days."
        ),
    }


def _handle_positive(rec: ConversationRecord, merchant_id: str) -> dict:
    rec.state = ConversationRecord.STATE_ACTION_CONFIRMED

    # Look up merchant + trigger context to compose a specific action message
    merchant = context_store.get("merchant", merchant_id) or {}
    trigger_id = rec.trigger_id
    trigger = context_store.get("trigger", trigger_id) or {}
    category_slug = merchant.get("category_slug", "")
    category = context_store.get("category", category_slug) or {}
    customer = context_store.get("customer", rec.customer_id) if rec.customer_id else None

    body = _compose_action_response(merchant, trigger, category, customer, rec)
    rec.add_turn("bot", body)

    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": (
            "Merchant confirmed intent; switching to action-execution mode. "
            "Providing concrete next step."
        ),
    }


def _handle_negative(rec: ConversationRecord, merchant_id: str) -> dict:
    rec.state = ConversationRecord.STATE_CLOSED
    conversation_store.close_conversation(rec.conversation_id)
    return {
        "action": "end",
        "rationale": "Merchant declined. Closing conversation gracefully.",
    }


def _handle_later(rec: ConversationRecord, merchant_id: str) -> dict:
    rec.state = ConversationRecord.STATE_DEFERRED
    return {
        "action": "wait",
        "wait_seconds": 1800,   # 30 minutes
        "rationale": "Merchant asked to connect later. Backing off 30 minutes.",
    }


def _handle_question(rec: ConversationRecord, merchant_id: str, message: str) -> dict:
    rec.state = ConversationRecord.STATE_INFORMATION

    merchant = context_store.get("merchant", merchant_id) or {}
    trigger_id = rec.trigger_id
    trigger = context_store.get("trigger", trigger_id) or {}
    category_slug = merchant.get("category_slug", "")
    category = context_store.get("category", category_slug) or {}

    body = _compose_information_response(merchant, trigger, category, message)
    rec.add_turn("bot", body)

    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Merchant asked for information; answering from context without fabricating.",
    }


def _handle_out_of_scope(rec: ConversationRecord, merchant_id: str, message: str) -> dict:
    merchant = context_store.get("merchant", merchant_id) or {}
    name = merchant.get("identity", {}).get("owner_first_name", "")

    # Politely decline and redirect to original topic
    trigger_id = rec.trigger_id
    trigger = context_store.get("trigger", trigger_id) or {}
    kind = trigger.get("kind", "our earlier topic")

    body = (
        "That's outside what I can help with directly — "
        "you'd need your CA / professional for that. "
        f"Coming back to {kind.replace('_', ' ')} — want me to proceed, or shall I check in later?"
    )
    rec.add_turn("bot", body)

    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Out-of-scope request politely declined; redirected to original trigger.",
    }


def _handle_unknown_intent(rec: ConversationRecord, merchant_id: str, message: str) -> dict:
    """Ambiguous reply — ask minimal clarification."""
    body = "Got it! Just to confirm — would you like me to go ahead with this, or skip for now?"
    rec.add_turn("bot", body)
    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Ambiguous reply; asking minimal binary clarification.",
    }


def _handle_unknown_conversation(merchant_id: str, message: str) -> dict:
    """Reply on a conversation we don't have context for."""
    intent = classify_intent(message)
    if intent in ("positive", "unknown"):
        return {
            "action": "send",
            "body": "Got it — let me check your account and pick up from where we left off. Reply YES to continue.",
            "cta": "binary_yes_no",
            "rationale": "Unknown conversation ID; graceful recovery.",
        }
    elif intent == "hostile":
        return {"action": "end", "rationale": "Merchant hostile; closing."}
    else:
        return {
            "action": "send",
            "body": "Sure! What would you like help with today?",
            "cta": "open_ended",
            "rationale": "Unknown conversation; open question to re-engage.",
        }


# ---------------------------------------------------------------------------
# Action / information response composers
# ---------------------------------------------------------------------------

def _compose_action_response(merchant, trigger, category, customer, rec) -> str:
    """Compose a concrete action body when merchant says YES."""
    kind = trigger.get("kind", "")
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    name_str = owner if owner else merchant.get("identity", {}).get("name", "")
    sal = name_str if name_str else "there"

    from app.engine.category_rules import get_active_offers, get_customer_aggregate

    if kind == "research_digest":
        hrc = get_customer_aggregate(merchant).get("high_risk_adult_count", 0)
        patient_str = f" to your {hrc} high-risk adult patients" if hrc else ""
        return (
            f"Sending the abstract now (2 pages). "
            f"Also drafting a patient-ed WhatsApp you can share{patient_str} — "
            f"give me 2 minutes. Reply CONFIRM to send the draft to your patient list."
        )
    elif kind in ("recall_due", "chronic_refill_due"):
        return (
            "Booking confirmed. I'll send the reminder to the patient right away. "
            "Reply if you want to adjust the slot or offer."
        )
    elif kind == "perf_dip":
        offers = get_active_offers(merchant)
        offer_str = f"Boosting '{offers[0]['title']}' now." if offers else "Drafting a new offer."
        return f"{offer_str} GBP post goes live in ~10 minutes. Reply STOP to cancel."
    elif kind in ("festival_upcoming", "ipl_match_today"):
        return (
            "Draft is ready — posting to GBP now. "
            "Also prepping the WhatsApp version. Reply CONFIRM to send."
        )
    elif kind == "active_planning_intent":
        return (
            "Great! I'm finalizing the draft now. "
            "I'll have the complete offer copy + GBP post ready in 2 minutes. "
            "Reply CONFIRM to go live."
        )
    elif kind in ("customer_lapsed_hard", "customer_lapsed_soft"):
        cust_name = customer.get("identity", {}).get("name", "the customer") if customer else "the customer"
        return (
            f"Sending the winback message to {cust_name} now. "
            f"I'll notify you as soon as they respond. Reply STOP to cancel."
        )
    elif kind == "supply_alert":
        return (
            "Drafting the WhatsApp note for affected customers now. "
            "I'll also outline the replacement-pickup workflow. Reply CONFIRM to review before sending."
        )
    elif kind == "renewal_due":
        return (
            "Sending you the renewal link now. "
            "Your listing will stay active — no disruption to your profile or campaigns."
        )
    else:
        return (
            "On it! Drafting the action now — should be ready in 2-3 minutes. "
            "Reply CONFIRM to proceed or STOP to cancel."
        )


def _compose_information_response(merchant, trigger, category, message) -> str:
    """Answer a merchant question using only context data."""
    msg_lower = message.lower()

    from app.engine.category_rules import get_active_offers, get_performance, get_peer_stat

    # Price / how much question
    if any(w in msg_lower for w in ["how much", "price", "cost", "kitna", "charges", "fee", "amount"]):
        offers = get_active_offers(merchant)
        if offers:
            prices = ", ".join(o.get("title", "") for o in offers[:3] if o.get("status") == "active")
            return (
                f"Your current active offers: {prices}. "
                f"These are the live prices on your magicpin listing right now. "
                f"Want me to adjust any of them?"
            )
        else:
            cat_slug = merchant.get("category_slug", "")
            cat_offers = [o.get("title") for o in category.get("offer_catalog", [])[:3] if o.get("title")]
            if cat_offers:
                return (
                    f"You don't have active offers listed right now. "
                    f"Common offers for {cat_slug}: {', '.join(cat_offers[:2])}. "
                    f"Want me to set one up?"
                )
            return "You don't have active offers listed. Want me to suggest one based on your category?"

    # Who / target audience
    if any(w in msg_lower for w in ["who", "which customer", "target", "audience", "segment"]):
        agg = merchant.get("customer_aggregate", {})
        total = agg.get("total_unique_ytd", 0)
        lapsed = agg.get("lapsed_180d_plus", agg.get("lapsed_90d_plus", 0))
        if total:
            return (
                f"Your current roster: {total} unique customers this year. "
                f"{lapsed} haven't visited in 6+ months — they'd be the primary audience. "
                f"Want me to target them specifically?"
            )
        return "I'll target your existing customer list. Want me to proceed?"

    # When / timing
    if any(w in msg_lower for w in ["when", "kab", "time", "duration", "how long", "quickly"]):
        return (
            "This takes about 5-10 minutes to set up. "
            "Once confirmed, it goes live on your GBP listing immediately. "
            "Want to proceed?"
        )

    # What does it include
    if any(w in msg_lower for w in ["include", "cover", "what is", "kya hai", "details"]):
        kind = trigger.get("kind", "")
        payload = trigger.get("payload", {})
        if kind == "research_digest":
            item_id = payload.get("top_item_id", "")
            item = None
            for d in category.get("digest", []):
                if d.get("id") == item_id:
                    item = d
                    break
            if item:
                return (
                    f"The research item: '{item.get('title', '')}'. "
                    f"Source: {item.get('source', '')}. "
                    f"Summary: {item.get('summary', '')} "
                    f"Want me to draft a patient-friendly version?"
                )
        return "Here are the details based on your current context: " + \
               str({k: v for k, v in trigger.get("payload", {}).items() if not isinstance(v, dict)})[1:-1] + \
               ". Want me to proceed?"

    # Generic
    perf = get_performance(merchant)
    views = perf.get("views", 0)
    ctr = perf.get("ctr", 0)
    return (
        f"Sure! Your current numbers: {views:,} views this month, CTR {ctr*100:.1f}%. "
        f"What specifically would you like to know more about?"
    )
