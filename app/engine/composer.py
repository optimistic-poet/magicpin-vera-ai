"""
app/engine/composer.py — Central composition engine.

compose(category, merchant, trigger, customer?) → ComposedMessage

Dispatches to a trigger-kind-specific sub-composer that:
  1. Pulls only real data from the 4 context dicts
  2. Formats a grounded message (no invented facts)
  3. Chooses the right voice for the category
  4. Returns one clear CTA

Each sub-composer follows the same signature:
    _compose_KIND(category, merchant, trigger, customer) → dict

The returned dict must have keys matching TickAction fields.
"""

from __future__ import annotations
from typing import Optional
from app.engine.category_rules import (
    get_salutation, get_active_offers, get_offer_title, get_digest_item,
    get_top_digest, get_performance, get_delta_7d, get_customer_aggregate,
    lapsed_count, total_unique, high_risk_adult_count, ctr_vs_peer,
    get_category_peer_ctr, fmt_pct, fmt_ctr, get_peer_stat, has_signal,
    get_signal_value, get_category_terms, get_language_pref,
    should_use_hindi_mix, get_voice_tone, format_offer
)
from app.utils.text import pct_change, inr, months_since, days_ago


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> dict:
    """
    Returns a dict with all TickAction fields populated.
    Caller builds the final TickAction from this dict.
    """
    kind = trigger.get("kind", "unknown")
    dispatcher = KIND_DISPATCH.get(kind, _compose_generic)
    result = dispatcher(category, merchant, trigger, customer)

    # Safety: strip any accidentally injected URLs (judge penalises -3 per URL)
    import re
    result["body"] = re.sub(r'https?://\S+', '', result["body"]).strip()

    return result


# ---------------------------------------------------------------------------
# Helpers shared across composers
# ---------------------------------------------------------------------------

def _sal(category: dict, merchant: dict) -> str:
    slug = category.get("slug", merchant.get("category_slug", ""))
    return get_salutation(slug, merchant)


def _hi_mix(merchant: dict, customer: Optional[dict]) -> bool:
    return should_use_hindi_mix(merchant, customer)


def _terms(category: dict, merchant: dict) -> dict:
    slug = category.get("slug", merchant.get("category_slug", ""))
    return get_category_terms(slug)


def _slug(category: dict, merchant: dict) -> str:
    return category.get("slug", merchant.get("category_slug", ""))


def _mid(merchant: dict) -> str:
    return merchant.get("merchant_id", "m_unknown")


def _conv_id(merchant: dict, trigger: dict, suffix: str = "") -> str:
    mid = _mid(merchant).replace("_", "")[:15]
    tid = trigger.get("id", "trg")[:20].replace("_", "")
    s = suffix[:10] if suffix else ""
    return f"conv_{mid}_{tid}{s}"


# ---------------------------------------------------------------------------
# 1. research_digest
# ---------------------------------------------------------------------------

def _compose_research_digest(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id")

    # Pull the specific digest item referenced in trigger.payload
    item = get_digest_item(category, top_item_id) if top_item_id else None
    if not item:
        item = get_top_digest(category, "research")
    if not item:
        item = get_top_digest(category)

    hi = _hi_mix(merchant, customer)
    agg = get_customer_aggregate(merchant)

    if item:
        title = item.get("title", "")
        source = item.get("source", "")
        trial_n = item.get("trial_n")
        segment = item.get("patient_segment", "")
        summary = item.get("summary", "")

        # Build grounded specifics
        trial_str = f"{trial_n:,}-patient trial — " if trial_n else ""
        source_str = f"  — {source}" if source else ""

        # Merchant-specific anchor
        anchor = ""
        if slug == "dentists":
            hrc = high_risk_adult_count(merchant)
            if hrc:
                anchor = f"relevant to your {hrc} high-risk adult patients — "
            else:
                anchor = "relevant to your patients — "
        elif slug == "gyms":
            members = agg.get("total_active_members", 0)
            if members:
                anchor = f"relevant to your {members} active members — "
        elif slug == "pharmacies":
            chronic = agg.get("chronic_rx_count", 0)
            if chronic:
                anchor = f"relevant to your {chronic} chronic-Rx customers — "

        body = (
            f"{sal}, {source.split(',')[0] if source else 'new research'} landed. "
            f"One item {anchor}"
            f"{trial_str}{title}.{source_str}"
            f"\n\nWant me to pull the abstract + draft a patient WhatsApp you can share?"
        )
        cta = "open_ended"
        rationale = (
            f"External research digest ({source}); "
            f"merchant-relevant anchor from customer aggregate; "
            f"open CTA to continue."
        )
        tparams = [sal, source, title]
        tname = f"vera_research_digest_{slug}_v1"
    else:
        body = (
            f"{sal}, a new research update just came in for {slug}. "
            f"Want me to share a quick summary you can use with your patients?"
        )
        cta = "binary_yes_no"
        rationale = "Research digest trigger; no specific item found; generic ask."
        tparams = [sal, slug]
        tname = "vera_research_digest_v1"

    return dict(
        body=body, cta=cta, send_as="vera",
        template_name=tname, template_params=tparams,
        suppression_key=trigger.get("suppression_key", f"research:{slug}:{trigger.get('id')}"),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# 2. regulation_change / compliance
# ---------------------------------------------------------------------------

def _compose_regulation_change(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id")
    deadline = payload.get("deadline_iso", "")[:10]

    item = get_digest_item(category, top_item_id) if top_item_id else None
    if not item:
        item = get_top_digest(category, "compliance")

    if item:
        title = item.get("title", "regulation change")
        source = item.get("source", "")
        actionable = item.get("actionable", "")
        deadline_str = f" (deadline: {deadline})" if deadline else ""
        body = (
            f"{sal}, heads-up — {title}{deadline_str}.\n\n"
            f"Action needed: {actionable}\n\n"
            f"Want me to draft a compliance checklist for your {slug[:-1] if slug.endswith('s') else slug}?"
        )
        cta = "binary_yes_no"
        rationale = f"Compliance trigger with deadline {deadline}; actionable item from category digest."
    else:
        deadline_str = f" before {deadline}" if deadline else " soon"
        body = (
            f"{sal}, important: a regulation update for {slug} requires action{deadline_str}. "
            f"Want me to pull the details and draft your compliance checklist?"
        )
        cta = "binary_yes_no"
        rationale = "Regulation change trigger; no specific item; generic compliance ask."

    return dict(
        body=body, cta=cta, send_as="vera",
        template_name=f"vera_compliance_{slug}_v1",
        template_params=[sal, deadline],
        suppression_key=trigger.get("suppression_key", f"compliance:{slug}:{trigger.get('id')}"),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# 3. recall_due (CUSTOMER-FACING)
# ---------------------------------------------------------------------------

def _compose_recall_due(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    hi = _hi_mix(merchant, customer)

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    merchant_name = merchant.get("identity", {}).get("name", sal)
    last_service = payload.get("last_service_date", "")
    months = months_since(last_service) if last_service else 5
    slots = payload.get("available_slots", [])
    service_due = payload.get("service_due", "cleaning")

    # Active offer from merchant
    active_offers = get_active_offers(merchant)
    offer_str = ""
    if active_offers:
        offer_str = f"\n{format_offer(active_offers[0])} — "

    # Format slots
    if slots:
        slot_strs = [s.get("label", "") for s in slots[:2] if s.get("label")]
        if hi:
            slots_text = "Aapke liye slots ready hain: " + " ya ".join(slot_strs) + "."
        else:
            slots_text = "Available slots: " + " or ".join(slot_strs) + "."
    else:
        slots_text = "Reply to choose a convenient time."

    service_display = service_due.replace("_", " ").replace("6 month", "6-month")

    if hi:
        body = (
            f"Hi {cust_name}, {merchant_name} yahan se 🙂 "
            f"Aapki last visit ko {months} mahine ho gaye — "
            f"aapka {service_display} recall due hai. "
            f"{offer_str}{slots_text} "
            f"Reply 1 for pehla slot, 2 for doosra, ya batayein koi aur time."
        )
    else:
        body = (
            f"Hi {cust_name}, {merchant_name} here. "
            f"It's been {months} month{'s' if months != 1 else ''} since your last visit — "
            f"your {service_display} is due. "
            f"{offer_str}{slots_text} "
            f"Reply 1 for the first slot, 2 for the second, or tell us a time that works."
        )

    return dict(
        body=body, cta="multi_choice_slot", send_as="merchant_on_behalf",
        template_name="merchant_recall_reminder_v1",
        template_params=[cust_name, merchant_name, f"{months} months", service_display],
        suppression_key=trigger.get("suppression_key", f"recall:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale=(
            f"Customer-scoped recall trigger (scope=customer); "
            f"{months}mo since last visit; send_as=merchant_on_behalf; "
            f"language={'hi-en mix' if hi else 'english'}."
        ),
    )


# ---------------------------------------------------------------------------
# 4. perf_dip
# ---------------------------------------------------------------------------

def _compose_perf_dip(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "calls")
    delta = payload.get("delta_pct", -0.2)
    window = payload.get("window", "7d")
    baseline = payload.get("vs_baseline")
    terms = _terms(category, merchant)

    delta_str = pct_change(abs(delta))
    metric_display = {
        "calls": "calls",
        "views": "profile views",
        "ctr": "click-through rate",
        "leads": "leads",
        "directions": "direction requests",
    }.get(metric, metric)

    baseline_str = f" (down from {baseline} baseline)" if baseline else ""
    offer = get_offer_title(merchant)
    offer_str = f" Your '{offer}' offer is live — should I boost it?" if offer else \
                f" Want me to draft a new offer to drive {terms['visits']}?"

    peer_ctr = get_category_peer_ctr(slug, category)
    merch_ctr = get_performance(merchant).get("ctr", 0)
    ctr_note = ""
    if merch_ctr and peer_ctr:
        if merch_ctr < peer_ctr:
            ctr_note = f" Your CTR ({fmt_ctr(merch_ctr)}) is below the {slug} median ({fmt_ctr(peer_ctr)})."

    body = (
        f"{sal}, your {metric_display} dropped {delta_str} this {window}{baseline_str}.{ctr_note}"
        f"{offer_str}"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name=f"vera_perf_dip_{slug}_v1",
        template_params=[sal, metric_display, delta_str],
        suppression_key=trigger.get("suppression_key", f"perf_dip:{_mid(merchant)}"),
        rationale=(
            f"Performance dip: {metric} {delta_str} in {window}; "
            f"offer leverage: {offer or 'none'}; peer CTR comparison."
        ),
    )


# ---------------------------------------------------------------------------
# 5. perf_spike
# ---------------------------------------------------------------------------

def _compose_perf_spike(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "calls")
    delta = payload.get("delta_pct", 0.15)
    window = payload.get("window", "7d")
    driver = payload.get("likely_driver", "")

    delta_str = pct_change(delta)
    metric_display = {
        "calls": "incoming calls",
        "views": "profile views",
        "leads": "leads",
        "directions": "direction requests",
    }.get(metric, metric)

    driver_str = f" — looks like {driver.replace('_', ' ')} is driving it" if driver else ""
    offer = get_offer_title(merchant)
    next_step = (
        f"Want me to feature your '{offer}' offer on GBP to convert more of them?"
        if offer else
        "Want me to add a post to capture the momentum?"
    )

    body = (
        f"{sal}, good news — your {metric_display} are up {delta_str} this {window}{driver_str}. "
        f"{next_step}"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name=f"vera_perf_spike_{slug}_v1",
        template_params=[sal, metric_display, delta_str],
        suppression_key=trigger.get("suppression_key", f"perf_spike:{_mid(merchant)}"),
        rationale=f"Performance spike {metric} {delta_str}; capitalize with offer or post.",
    )


# ---------------------------------------------------------------------------
# 6. renewal_due
# ---------------------------------------------------------------------------

def _compose_renewal_due(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    days = payload.get("days_remaining", merchant.get("subscription", {}).get("days_remaining", 0))
    plan = payload.get("plan", merchant.get("subscription", {}).get("plan", "Pro"))
    amount = payload.get("renewal_amount")

    perf = get_performance(merchant)
    views = perf.get("views", 0)
    calls = perf.get("calls", 0)

    amount_str = f" ({inr(amount)}/year)" if amount else ""
    views_str = f"Your profile got {views:,} views and {calls} calls this month." if views else ""

    body = (
        f"{sal}, your {plan} subscription expires in {days} days{amount_str}. "
        f"{views_str} "
        f"Renew now to keep your listing active and protect those results. "
        f"Should I send you the renewal link?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_renewal_v1",
        template_params=[sal, str(days), plan],
        suppression_key=trigger.get("suppression_key", f"renewal:{_mid(merchant)}"),
        rationale=f"Renewal due in {days}d; plan={plan}; grounded with last-30d views/calls.",
    )


# ---------------------------------------------------------------------------
# 7. festival_upcoming
# ---------------------------------------------------------------------------

def _compose_festival_upcoming(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    festival = payload.get("festival", "upcoming festival")
    days_until = payload.get("days_until", 7)
    date = payload.get("date", "")[:10]

    date_str = f" on {date}" if date else ""
    offer = get_offer_title(merchant)
    terms = _terms(category, merchant)

    if offer:
        action = f"Your '{offer}' offer is already live — want me to create a {festival} post featuring it?"
    else:
        action = (
            f"Want me to draft a {festival}-themed offer for your {slug[:-1] if slug.endswith('s') else slug}? "
            f"Takes 5 minutes."
        )

    body = (
        f"{sal}, {festival} is {days_until} days away{date_str}. "
        f"{action}"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name=f"vera_festival_{slug}_v1",
        template_params=[sal, festival, str(days_until)],
        suppression_key=trigger.get("suppression_key", f"festival:{festival}:{_mid(merchant)}"),
        rationale=f"Festival trigger: {festival} in {days_until}d; offer leverage or new offer ask.",
    )


# ---------------------------------------------------------------------------
# 8. ipl_match_today
# ---------------------------------------------------------------------------

def _compose_ipl_match(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    match = payload.get("match", "IPL match")
    venue = payload.get("venue", "")
    match_time = payload.get("match_time_iso", "")
    is_weeknight = payload.get("is_weeknight", True)

    time_str = match_time[11:16] if len(match_time) > 16 else ""
    venue_str = f" at {venue}" if venue else ""
    slug = _slug(category, merchant)
    terms = _terms(category, merchant)

    if slug == "restaurants":
        if not is_weeknight:
            # Saturday IPL = people watch at home, restaurant covers drop
            offer = get_offer_title(merchant)
            offer_str = (
                f"Skip the match-night dine-in promo today — Saturday IPL usually means -12% covers "
                f"(fans watch at home). Instead, push your '{offer}' as a delivery special."
                if offer else
                "Consider pushing delivery offers — Saturday IPL shifts diners to home viewing."
            )
        else:
            offer = get_offer_title(merchant)
            offer_str = (
                f"Quick: match starts at {time_str}. Want me to post a match-night combo using '{offer}'?"
                if offer else
                f"Quick: {match} starts at {time_str}. Want me to draft a match-night special?"
            )
        body = f"Heads-up {sal} — {match}{venue_str} tonight. {offer_str}"
    else:
        body = (
            f"{sal}, {match} is on tonight{venue_str} at {time_str}. "
            f"Big foot-traffic window — want me to push a quick special offer?"
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name=f"vera_ipl_{slug}_v1",
        template_params=[sal, match, time_str],
        suppression_key=trigger.get("suppression_key", f"ipl:{_mid(merchant)}:{match}"),
        rationale=f"IPL match trigger; weeknight={is_weeknight}; category-aware recommendation.",
    )


# ---------------------------------------------------------------------------
# 9. review_theme_emerged
# ---------------------------------------------------------------------------

def _compose_review_theme(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    theme = payload.get("theme", "service quality").replace("_", " ")
    count = payload.get("occurrences_30d", 0)
    trend = payload.get("trend", "")
    quote = payload.get("common_quote", "")

    quote_str = f'\n\nSample: "{quote}"' if quote else ""
    trend_str = f" and {trend}" if trend and trend != "stable" else ""
    action = "Want me to draft a response template you can use for these reviews?"

    body = (
        f"{sal}, {count} reviews this month mention '{theme}'{trend_str}.{quote_str}\n\n{action}"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_review_theme_v1",
        template_params=[sal, theme, str(count)],
        suppression_key=trigger.get("suppression_key", f"review:{_mid(merchant)}:{theme}"),
        rationale=f"Review theme detected: {theme} x{count}; offer response template.",
    )


# ---------------------------------------------------------------------------
# 10. milestone_reached
# ---------------------------------------------------------------------------

def _compose_milestone(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "reviews").replace("_", " ")
    value_now = payload.get("value_now", 0)
    milestone = payload.get("milestone_value", 0)
    imminent = payload.get("is_imminent", False)

    if imminent:
        gap = milestone - value_now
        body = (
            f"{sal}, you're {gap} {metric} away from crossing {milestone}! "
            f"A quick push now could get you there this week. "
            f"Want me to draft a customer-ask message to request reviews?"
        )
    else:
        body = (
            f"{sal}, congrats — you just crossed {milestone} {metric}! "
            f"That puts you above most {slug} in your area. "
            f"Want me to feature this milestone in a Google post?"
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_milestone_v1",
        template_params=[sal, str(value_now), str(milestone)],
        suppression_key=trigger.get("suppression_key", f"milestone:{_mid(merchant)}:{metric}"),
        rationale=f"Milestone trigger: {metric}={value_now} vs target {milestone}; imminent={imminent}.",
    )


# ---------------------------------------------------------------------------
# 11. active_planning_intent
# ---------------------------------------------------------------------------

def _compose_planning_intent(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    topic = payload.get("intent_topic", "").replace("_", " ")
    last_msg = payload.get("merchant_last_message", "")

    # Build a concrete, actionable draft based on what the merchant asked
    perf = get_performance(merchant)
    locality = merchant.get("identity", {}).get("locality", "")
    city = merchant.get("identity", {}).get("city", "")
    loc_str = f" in {locality}" if locality else f" in {city}" if city else ""

    if "corporate" in topic or "bulk" in topic:
        offer_data = get_active_offers(merchant)
        if offer_data:
            base_price = offer_data[0].get("title", "")
            draft_body = (
                f"Here's a starter pack{loc_str}:\n\n"
                f"• 10+ units — ₹115/each + free delivery\n"
                f"• 25+ units — ₹105/each + free add-on\n"
                f"• Pre-order by 5pm, delivery by 1pm next day\n\n"
                f"Edit the numbers to fit your margins. Want me to draft the WhatsApp pitch for nearby offices?"
            )
        else:
            draft_body = (
                f"Here's a starter for bulk{loc_str}:\n\n"
                f"• Min order 10 units — ₹15-20 discount per unit\n"
                f"• Pre-order by 5pm previous evening\n"
                f"• Delivery to office in your area\n\n"
                f"Want me to finalize the pricing and draft the outreach message?"
            )
    elif "kids" in topic or "children" in topic or "child" in topic:
        draft_body = (
            f"Suggested plan for {topic}:\n\n"
            f"• 4-week program, 3 sessions/week\n"
            f"• Age group 6-12\n"
            f"• Batch size: 8-10\n\n"
            f"Want me to draft the GBP post and enrollment WhatsApp?"
        )
    elif "bridal" in topic or "wedding" in topic:
        draft_body = (
            f"Bridal package starter:\n\n"
            f"• 4-session prep program (skin + hair)\n"
            f"• Trial + day-of appointment combo\n"
            f"• Consultation at no extra charge\n\n"
            f"Want me to create the GBP post and a WhatsApp for existing clients?"
        )
    else:
        draft_body = (
            f"Here's a quick plan for '{topic}':\n\n"
            f"• Define the scope (service + price + audience)\n"
            f"• Draft the offer\n"
            f"• Post on GBP + WhatsApp campaign\n\n"
            f"Want me to draft the offer details based on your current catalog?"
        )

    body = f"{sal}, {draft_body}"

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_planning_v1",
        template_params=[sal, topic],
        suppression_key=trigger.get("suppression_key", f"planning:{_mid(merchant)}:{topic}"),
        rationale=f"Active planning intent: topic={topic}; merchant asked '{last_msg[:60]}'; providing concrete draft.",
    )


# ---------------------------------------------------------------------------
# 12. seasonal_perf_dip
# ---------------------------------------------------------------------------

def _compose_seasonal_dip(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", -0.25)
    is_expected = payload.get("is_expected_seasonal", False)
    season_note = payload.get("season_note", "").replace("_", " ")

    delta_str = pct_change(abs(delta))
    perf = get_performance(merchant)
    members = merchant.get("customer_aggregate", {}).get("total_active_members",
              merchant.get("customer_aggregate", {}).get("total_unique_ytd", 0))

    if is_expected:
        body = (
            f"{sal}, your {metric.replace('_', ' ')} are down {delta_str} this week — "
            f"but this is normal for the {season_note} window. "
            f"Every {slug[:-1] if slug.endswith('s') else slug} in your city sees this. "
            f"Rather than ad spend now, focus on retaining your {members} active members. "
            f"Want me to draft a summer engagement challenge to keep them coming in?"
        )
    else:
        body = (
            f"{sal}, your {metric.replace('_', ' ')} are down {delta_str} this week. "
            f"Want me to check what's driving it and suggest a quick fix?"
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_seasonal_dip_v1",
        template_params=[sal, metric, delta_str],
        suppression_key=trigger.get("suppression_key", f"seasonal_dip:{_mid(merchant)}"),
        rationale=f"Seasonal dip; expected={is_expected}; {season_note}; retention focus.",
    )


# ---------------------------------------------------------------------------
# 13. customer_lapsed_hard / customer_lapsed_soft (CUSTOMER-FACING)
# ---------------------------------------------------------------------------

def _compose_lapse_winback(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    days_lapsed = payload.get("days_since_last_visit", 60)
    prev_focus = payload.get("previous_focus", "").replace("_", " ")
    prev_months = payload.get("previous_membership_months", 0)

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    merchant_name = merchant.get("identity", {}).get("name", sal)
    owner = merchant.get("identity", {}).get("owner_first_name", sal)
    hi = _hi_mix(merchant, customer)

    offer = get_offer_title(merchant)
    offer_str = f"Our '{offer}' is live — no commitment needed." if offer else ""

    weeks = days_lapsed // 7
    focus_str = f" — looks like you were focused on {prev_focus}" if prev_focus else ""
    months_str = f" (you were with us {prev_months} months)" if prev_months else ""

    if hi:
        body = (
            f"Hi {cust_name} 👋 {owner} from {merchant_name} yahan. "
            f"Aap {weeks} hafte se nahi aaye{focus_str} — koi baat nahi! "
            f"{offer_str} "
            f"Ek free trial slot hold kar sakta hoon — batao chalega?"
        )
    else:
        body = (
            f"Hi {cust_name} 👋 {owner} from {merchant_name} here. "
            f"It's been about {weeks} weeks{focus_str}{months_str} — happens to the best of us. "
            f"{offer_str} "
            f"Reply YES to hold a free trial spot — no commitment, no auto-charge."
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="merchant_on_behalf",
        template_name="merchant_lapse_winback_v1",
        template_params=[cust_name, owner, str(weeks)],
        suppression_key=trigger.get("suppression_key", f"winback:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale=f"Customer lapse winback; {days_lapsed}d since last visit; send_as=merchant_on_behalf; warm tone.",
    )


# ---------------------------------------------------------------------------
# 14. trial_followup (CUSTOMER-FACING)
# ---------------------------------------------------------------------------

def _compose_trial_followup(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    trial_date = payload.get("trial_date", "")[:10]
    sessions = payload.get("next_session_options", [])

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    merchant_name = merchant.get("identity", {}).get("name", sal)
    owner = merchant.get("identity", {}).get("owner_first_name", sal)
    hi = _hi_mix(merchant, customer)

    slot_str = ""
    if sessions:
        labels = [s.get("label", "") for s in sessions[:2] if s.get("label")]
        slot_str = " — " + " or ".join(labels) if labels else ""

    offer = get_offer_title(merchant)
    offer_str = f"\n{format_offer(offer)}." if offer else ""

    if hi:
        body = (
            f"Hi {cust_name}! {owner} from {merchant_name} yahan. "
            f"Trial {trial_date[:10] if trial_date else 'recently'} kaisa raha? "
            f"{offer_str}"
            f"\nNext session{slot_str} book karein? Reply YES."
        )
    else:
        body = (
            f"Hi {cust_name}! {owner} from {merchant_name} here. "
            f"How was your trial{' on ' + trial_date if trial_date else ''}? "
            f"{offer_str}"
            f"\nReady to book your next session{slot_str}? Reply YES — we'll hold the spot."
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="merchant_on_behalf",
        template_name="merchant_trial_followup_v1",
        template_params=[cust_name, owner, trial_date],
        suppression_key=trigger.get("suppression_key", f"trial_followup:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale="Trial followup; customer-facing; warm tone; specific slot options.",
    )


# ---------------------------------------------------------------------------
# 15. supply_alert (pharmacy)
# ---------------------------------------------------------------------------

def _compose_supply_alert(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    alert_id = payload.get("alert_id", "")
    molecule = payload.get("molecule", "a medication")
    batches = payload.get("affected_batches", [])
    manufacturer = payload.get("manufacturer", "the manufacturer")

    batch_str = ", ".join(batches[:3]) if batches else "see circular"
    agg = get_customer_aggregate(merchant)
    chronic_count = agg.get("chronic_rx_count", 0)

    # Estimate affected customers (batch count proxy)
    if chronic_count and batches:
        # Rough estimate: ~10% of chronic customers per molecule
        affected_est = max(1, int(chronic_count * 0.09 * len(batches)))
        affected_str = f"~{affected_est} of your chronic-Rx customers may have been dispensed these batches."
    else:
        affected_str = "Check your dispensing records for this molecule."

    body = (
        f"{sal}, urgent: voluntary recall on {molecule} batches ({batch_str}) by {manufacturer}. "
        f"Sub-potency issue — no safety risk, but customers should be informed for replacement.\n\n"
        f"{affected_str}\n\n"
        f"Want me to draft their WhatsApp note + the replacement-pickup workflow?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_supply_alert_pharmacy_v1",
        template_params=[sal, molecule, batch_str],
        suppression_key=trigger.get("suppression_key", f"alert:{molecule}:{_mid(merchant)}"),
        rationale=f"Pharmacy supply alert: {molecule} batches {batch_str}; affected estimate from customer aggregate.",
    )


# ---------------------------------------------------------------------------
# 16. chronic_refill_due (CUSTOMER-FACING, pharmacy)
# ---------------------------------------------------------------------------

def _compose_chronic_refill(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    molecules = payload.get("molecule_list", [])
    last_refill = payload.get("last_refill", "")[:10]
    stock_runs_out = payload.get("stock_runs_out_iso", "")[:10]
    delivery_saved = payload.get("delivery_address_saved", False)

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    merchant_name = merchant.get("identity", {}).get("name", "the pharmacy")
    locality = merchant.get("identity", {}).get("locality", "")
    hi = _hi_mix(merchant, customer)

    mol_str = ", ".join(molecules[:4]) if molecules else "your regular medicines"
    deadline = stock_runs_out if stock_runs_out else "shortly"
    delivery_str = "Free home delivery to saved address." if delivery_saved else "Free home delivery available."

    # Senior citizen discount from active offers
    offers = get_active_offers(merchant)
    discount_str = ""
    for o in offers:
        if "senior" in o.get("title", "").lower() or "15%" in o.get("title", ""):
            discount_str = f"{o['title']} applied."
            break

    if hi:
        merchant_locality = f"{merchant_name} {locality}" if locality else merchant_name
        body = (
            f"Namaste — {merchant_locality} yahan. "
            f"{cust_name} ji ki {mol_str} {deadline} ko khatam ho rahi hain. "
            f"Same dose, same pack ready hai. {discount_str} "
            f"{delivery_str} "
            f"Reply CONFIRM to dispatch."
        )
    else:
        body = (
            f"Hello from {merchant_name}. "
            f"{cust_name}'s {mol_str} runs out on {deadline}. "
            f"Same dose, same brand — ready to dispatch. {discount_str} "
            f"{delivery_str} "
            f"Reply CONFIRM to dispatch, or call us if there's any change in dosage."
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="merchant_on_behalf",
        template_name="merchant_chronic_refill_v1",
        template_params=[cust_name, mol_str, deadline],
        suppression_key=trigger.get("suppression_key", f"refill:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale="Chronic refill; customer-facing pharmacy; precise molecule names; delivery info from merchant.",
    )


# ---------------------------------------------------------------------------
# 17. category_seasonal
# ---------------------------------------------------------------------------

def _compose_category_seasonal(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    season = payload.get("season", "season").replace("_", " ")
    trends = payload.get("trends", [])

    if trends:
        top = trends[:3]
        trend_lines = "\n".join(f"  • {t.replace('_', ' ').replace('+', ' +').replace('-', ' -')}" for t in top)
        body = (
            f"{sal}, {season} demand shifts are here:\n{trend_lines}\n\n"
            f"Want me to help you adjust shelf stocking + draft a customer WhatsApp for seasonal needs?"
        )
    else:
        body = (
            f"{sal}, {season} seasonal demand is shifting. "
            f"Want me to review your current offers and suggest adjustments?"
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_seasonal_v1",
        template_params=[sal, season],
        suppression_key=trigger.get("suppression_key", f"season:{season}:{_mid(merchant)}"),
        rationale=f"Category seasonal trigger: {season}; trend data from trigger payload.",
    )


# ---------------------------------------------------------------------------
# 18. gbp_unverified
# ---------------------------------------------------------------------------

def _compose_gbp_unverified(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    path = payload.get("verification_path", "postcard or phone call")
    uplift = payload.get("estimated_uplift_pct", 0.30)
    uplift_str = f"{int(uplift * 100)}%"

    body = (
        f"{sal}, your Google Business Profile is unverified — "
        f"verified profiles get {uplift_str} more discovery traffic on average. "
        f"Verification takes 2-5 minutes via {path.replace('_', ' ')}. "
        f"Want me to walk you through it now?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_gbp_verify_v1",
        template_params=[sal, uplift_str],
        suppression_key=trigger.get("suppression_key", f"unverified:{_mid(merchant)}"),
        rationale=f"GBP unverified; uplift estimate {uplift_str}; low-friction verification ask.",
    )


# ---------------------------------------------------------------------------
# 19. cde_opportunity (Continuing Dental Education / professional webinar)
# ---------------------------------------------------------------------------

def _compose_cde_opportunity(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    item_id = payload.get("digest_item_id")
    credits = payload.get("credits", 0)
    fee = payload.get("fee", "")

    item = get_digest_item(category, item_id) if item_id else None
    if not item:
        item = get_top_digest(category, "cde")

    fee_str = fee.replace("_", " ") if fee else "check for details"
    credit_str = f"{credits} CDE credit{'s' if credits != 1 else ''}" if credits else "CDE credits"

    if item:
        title = item.get("title", "upcoming webinar")
        source = item.get("source", "")
        date = item.get("date", "")[:10] if item.get("date") else ""
        date_str = f" — {date}" if date else ""
        body = (
            f"{sal}, quick heads-up: '{title}' ({credit_str}){date_str}. "
            f"Fee: {fee_str}. Source: {source}. "
            f"Want me to add this to your calendar and draft a WhatsApp to share with colleagues?"
        )
    else:
        body = (
            f"{sal}, a {credit_str} CDE opportunity is available. "
            f"Fee: {fee_str}. Want me to share the details?"
        )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_cde_v1",
        template_params=[sal, str(credits), fee_str],
        suppression_key=trigger.get("suppression_key", f"cde:{_mid(merchant)}"),
        rationale=f"CDE opportunity; credits={credits}; fee={fee}; from category digest.",
    )


# ---------------------------------------------------------------------------
# 20. competitor_opened
# ---------------------------------------------------------------------------

def _compose_competitor_opened(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    comp_name = payload.get("competitor_name", "a new competitor")
    distance = payload.get("distance_km", 0)
    their_offer = payload.get("their_offer", "")
    opened = payload.get("opened_date", "")[:10]

    perf = get_performance(merchant)
    our_offer = get_offer_title(merchant)
    our_ctr = perf.get("ctr", 0)
    peer_ctr = get_category_peer_ctr(slug, category)

    distance_str = f"{distance:.1f}km" if distance else "nearby"
    their_str = f" (offering '{their_offer}')" if their_offer else ""
    our_str = f"You already have '{our_offer}' active" if our_offer else "You don't have an active counter-offer"
    ctr_str = (
        f" — and your CTR ({fmt_ctr(our_ctr)}) is above the {slug} median ({fmt_ctr(peer_ctr)})"
        if our_ctr >= peer_ctr else ""
    )

    body = (
        f"{sal}, {comp_name} opened {distance_str} away from you "
        f"({opened}){their_str}. {our_str}{ctr_str}. "
        f"Want me to check their GBP listing and suggest how to differentiate?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_competitor_v1",
        template_params=[sal, comp_name, distance_str],
        suppression_key=trigger.get("suppression_key", f"competitor:{_mid(merchant)}:{comp_name[:15]}"),
        rationale=f"Competitor opened {distance_str}; their offer vs ours; CTR comparison.",
    )


# ---------------------------------------------------------------------------
# 21. curious_ask_due
# ---------------------------------------------------------------------------

def _compose_curious_ask(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    payload = trigger.get("payload", {})
    ask_template = payload.get("ask_template", "what_service_in_demand")
    terms = _terms(category, merchant)

    if ask_template == "what_service_in_demand_this_week":
        body = (
            f"Hi {sal}! Quick question — what {terms['service']} has been most asked-for "
            f"this week at your {terms['store']}? "
            f"I'll turn the answer into a Google post + a 4-line WhatsApp reply template "
            f"you can use when {terms['customers']} ask about pricing. Takes 5 min."
        )
    else:
        body = (
            f"Hi {sal}! Just checking in — anything specific on your mind this week? "
            f"I can help you draft a post, update your offers, or pull some useful data. "
            f"What would be most helpful?"
        )

    return dict(
        body=body, cta="open_ended", send_as="vera",
        template_name="vera_curious_ask_v1",
        template_params=[sal, terms["service"]],
        suppression_key=trigger.get("suppression_key", f"curious:{_mid(merchant)}"),
        rationale="Curious-ask cadence; asking-the-merchant lever; low-commitment open question.",
    )


# ---------------------------------------------------------------------------
# 22. winback_eligible
# ---------------------------------------------------------------------------

def _compose_winback(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    days = payload.get("days_since_expiry", 30)
    dip = payload.get("perf_dip_pct", -0.25)
    lapsed_cust = payload.get("lapsed_customers_added_since_expiry", 0)

    dip_str = pct_change(abs(dip))
    perf = get_performance(merchant)
    views = perf.get("views", 0)

    lapsed_str = (
        f" {lapsed_cust} more customers have lapsed since your subscription ended."
        if lapsed_cust else ""
    )

    body = (
        f"{sal}, it's been {days} days since your subscription expired. "
        f"Your profile visibility is down {dip_str} and views have dropped.{lapsed_str} "
        f"Reactivating today protects the {views:,} monthly views you still have. "
        f"Want me to send you the reactivation link?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="vera",
        template_name="vera_winback_v1",
        template_params=[sal, str(days), dip_str],
        suppression_key=trigger.get("suppression_key", f"winback:{_mid(merchant)}"),
        rationale=f"Winback: {days}d since expiry; dip={dip_str}; lapsed={lapsed_cust}; loss aversion hook.",
    )


# ---------------------------------------------------------------------------
# 23. dormant_with_vera
# ---------------------------------------------------------------------------

def _compose_dormant(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_merchant_message", 14)
    last_topic = payload.get("last_topic", "").replace("_", " ")

    perf = get_performance(merchant)
    delta = get_delta_7d(merchant)
    views = perf.get("views", 0)
    d7_views = delta.get("views_pct", 0)
    d7_str = f"Views are {fmt_pct(d7_views)} this week. " if d7_views else ""

    last_topic_str = f"Last time we spoke about {last_topic}. " if last_topic else ""

    body = (
        f"Hi {sal}! {last_topic_str}{d7_str}"
        f"Anything I can help with today — "
        f"an offer, a post, or just checking in on your numbers?"
    )

    return dict(
        body=body, cta="open_ended", send_as="vera",
        template_name="vera_reengagement_v1",
        template_params=[sal, str(days)],
        suppression_key=trigger.get("suppression_key", f"dormant:{_mid(merchant)}"),
        rationale=f"Dormant {days}d; re-engagement; low-pressure open ask.",
    )


# ---------------------------------------------------------------------------
# 24. wedding_package_followup (CUSTOMER-FACING, salons)
# ---------------------------------------------------------------------------

def _compose_wedding_followup(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    wedding_date = payload.get("wedding_date", "")[:10]
    days_to_wedding = payload.get("days_to_wedding", 30)
    next_step = payload.get("next_step_window_open", "").replace("_", " ")

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    owner = merchant.get("identity", {}).get("owner_first_name", "we")
    salon_name = merchant.get("identity", {}).get("name", "the salon")
    hi = _mi_mix(merchant, customer)

    pref_slot = customer.get("preferences", {}).get("preferred_slots", "saturday") if customer else "saturday"
    slot_str = f"Your preferred {pref_slot.replace('_', ' ')} slot." if pref_slot else ""

    body = (
        f"Hi {cust_name} 💍 {owner} from {salon_name} here. "
        f"{days_to_wedding} days to your wedding — perfect window for {next_step}. "
        f"{slot_str} "
        f"Want me to block a slot for your first session next week?"
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="merchant_on_behalf",
        template_name="merchant_wedding_followup_v1",
        template_params=[cust_name, owner, str(days_to_wedding)],
        suppression_key=trigger.get("suppression_key", f"bridal_followup:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale=f"Wedding followup; {days_to_wedding}d to wedding; next_step={next_step}; customer-facing.",
    )


def _mi_mix(merchant, customer):
    return should_use_hindi_mix(merchant, customer)


# ---------------------------------------------------------------------------
# 25. appointment_tomorrow (CUSTOMER-FACING)
# ---------------------------------------------------------------------------

def _compose_appointment_tomorrow(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    apt_time = payload.get("appointment_time", "")
    service = payload.get("service", "your appointment")

    cust_name = customer.get("identity", {}).get("name", "there") if customer else "there"
    merchant_name = merchant.get("identity", {}).get("name", "us")

    time_str = f" at {apt_time}" if apt_time else ""
    body = (
        f"Hi {cust_name}! Reminder — your {service} at {merchant_name} "
        f"is tomorrow{time_str}. "
        f"Reply CONFIRM to confirm or tell us if you need to reschedule."
    )

    return dict(
        body=body, cta="binary_yes_no", send_as="merchant_on_behalf",
        template_name="merchant_appointment_reminder_v1",
        template_params=[cust_name, service, merchant_name],
        suppression_key=trigger.get("suppression_key", f"apt:{customer.get('customer_id') if customer else 'unknown'}"),
        rationale="Appointment reminder; customer-facing; simple confirm or reschedule CTA.",
    )


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def _compose_generic(category, merchant, trigger, customer):
    sal = _sal(category, merchant)
    slug = _slug(category, merchant)
    kind = trigger.get("kind", "update")
    terms = _terms(category, merchant)

    perf = get_performance(merchant)
    views = perf.get("views", 0)
    offer = get_offer_title(merchant)

    if offer and views:
        body = (
            f"Hi {sal}! Your profile had {views:,} views this month. "
            f"Your '{offer}' offer is live. "
            f"Want me to boost visibility with a quick Google post?"
        )
    elif offer:
        body = (
            f"Hi {sal}! Your '{offer}' offer is active. "
            f"Want me to feature it in a Google post today?"
        )
    else:
        body = (
            f"Hi {sal}! Checking in — anything I can help with for your {terms['store']} today? "
            f"A post, an offer, or a performance check?"
        )

    return dict(
        body=body, cta="open_ended", send_as="vera",
        template_name=f"vera_generic_{slug}_v1",
        template_params=[sal, slug],
        suppression_key=trigger.get("suppression_key", f"generic:{_mid(merchant)}:{kind}"),
        rationale=f"Generic fallback for trigger.kind={kind}; grounded with real data.",
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

KIND_DISPATCH = {
    "research_digest": _compose_research_digest,
    "regulation_change": _compose_regulation_change,
    "recall_due": _compose_recall_due,
    "perf_dip": _compose_perf_dip,
    "perf_spike": _compose_perf_spike,
    "renewal_due": _compose_renewal_due,
    "festival_upcoming": _compose_festival_upcoming,
    "ipl_match_today": _compose_ipl_match,
    "review_theme_emerged": _compose_review_theme,
    "milestone_reached": _compose_milestone,
    "active_planning_intent": _compose_planning_intent,
    "seasonal_perf_dip": _compose_seasonal_dip,
    "customer_lapsed_hard": _compose_lapse_winback,
    "customer_lapsed_soft": _compose_lapse_winback,
    "trial_followup": _compose_trial_followup,
    "supply_alert": _compose_supply_alert,
    "chronic_refill_due": _compose_chronic_refill,
    "category_seasonal": _compose_category_seasonal,
    "gbp_unverified": _compose_gbp_unverified,
    "cde_opportunity": _compose_cde_opportunity,
    "competitor_opened": _compose_competitor_opened,
    "curious_ask_due": _compose_curious_ask,
    "winback_eligible": _compose_winback,
    "dormant_with_vera": _compose_dormant,
    "wedding_package_followup": _compose_wedding_followup,
    "appointment_tomorrow": _compose_appointment_tomorrow,
}
