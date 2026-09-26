"""
app/engine/category_rules.py — Per-category voice, offer, and tone rules.

Loaded from actual category context payloads pushed to /v1/context.
Also contains hardcoded fallbacks that match the challenge dataset categories.
"""

from __future__ import annotations
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Salutation helpers (derived from category + merchant context)
# ---------------------------------------------------------------------------

def get_salutation(category_slug: str, merchant: dict) -> str:
    """
    Return the right salutation for this merchant.
    E.g. "Dr. Meera" for dentists, "Lakshmi" for salons.
    """
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    name = merchant.get("identity", {}).get("name", "")

    if category_slug == "dentists":
        if owner:
            return f"Dr. {owner}"
        # Try to extract from clinic name
        if "Dr." in name:
            parts = name.split()
            try:
                idx = parts.index("Dr.")
                return f"Dr. {parts[idx + 1]}"
            except (ValueError, IndexError):
                pass
        return "Doctor"
    else:
        return owner if owner else name.split()[0] if name else "there"


def get_voice_tone(category_slug: str, category: dict) -> str:
    """Return voice tone string for this category."""
    voice = category.get("voice", {})
    return voice.get("tone", CATEGORY_DEFAULTS.get(category_slug, {}).get("tone", "friendly"))


def get_taboos(category_slug: str, category: dict) -> list[str]:
    """Return list of forbidden words/phrases."""
    voice = category.get("voice", {})
    return voice.get("vocab_taboo", CATEGORY_DEFAULTS.get(category_slug, {}).get("taboos", []))


def get_peer_stat(category: dict, stat: str, fallback=None):
    """Safely pull a peer stat."""
    return category.get("peer_stats", {}).get(stat, fallback)


# ---------------------------------------------------------------------------
# Category defaults (fallback when context not yet pushed)
# ---------------------------------------------------------------------------

CATEGORY_DEFAULTS: dict[str, dict] = {
    "dentists": {
        "tone": "peer_clinical",
        "taboos": ["guaranteed", "100% safe", "completely cure", "miracle"],
        "salutation": "Dr.",
        "peer_ctr": 0.030,
        "currency": "₹",
        "terms": {
            "visits": "appointments",
            "customers": "patients",
            "service": "treatment",
            "store": "clinic",
        },
        "seasonal": "Oct-Dec wedding whitening peak; Nov-Feb bruxism spike",
    },
    "salons": {
        "tone": "warm_practical",
        "taboos": [],
        "salutation": "",
        "peer_ctr": 0.040,
        "currency": "₹",
        "terms": {
            "visits": "appointments",
            "customers": "clients",
            "service": "service",
            "store": "salon",
        },
        "seasonal": "Oct-Nov bridal/festive surge; Jan-Feb Valentine season",
    },
    "restaurants": {
        "tone": "operator_peer",
        "taboos": ["AMAZING DEAL", "BEST IN CITY"],
        "salutation": "",
        "peer_ctr": 0.035,
        "currency": "₹",
        "terms": {
            "visits": "orders",
            "customers": "customers",
            "service": "dish",
            "store": "restaurant",
        },
        "seasonal": "IPL season (Apr-Jun) dinner rush; Diwali/Holi festive orders",
    },
    "gyms": {
        "tone": "coaching_peer",
        "taboos": ["guilt", "lazy"],
        "salutation": "",
        "peer_ctr": 0.045,
        "currency": "₹",
        "terms": {
            "visits": "sessions",
            "customers": "members",
            "service": "program",
            "store": "gym",
        },
        "seasonal": "Jan resolution surge; Apr-Jun seasonal dip; Sept-Oct renewal rush",
    },
    "pharmacies": {
        "tone": "trustworthy_precise",
        "taboos": ["cure", "guaranteed", "100% effective"],
        "salutation": "",
        "peer_ctr": 0.042,
        "currency": "₹",
        "terms": {
            "visits": "visits",
            "customers": "customers",
            "service": "medicine",
            "store": "pharmacy",
        },
        "seasonal": "Summer ORS/antifungal demand; Monsoon cold/cough; Winter respiratory",
    },
}


def get_category_terms(category_slug: str) -> dict:
    return CATEGORY_DEFAULTS.get(category_slug, CATEGORY_DEFAULTS["restaurants"])["terms"]


def get_category_peer_ctr(category_slug: str, category: dict) -> float:
    pushed = get_peer_stat(category, "avg_ctr")
    if pushed:
        return float(pushed)
    return CATEGORY_DEFAULTS.get(category_slug, {}).get("peer_ctr", 0.030)


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

def should_use_hindi_mix(merchant: dict, customer: dict | None = None) -> bool:
    """
    Return True if the merchant/customer prefers Hindi-English code-mix.
    """
    if customer:
        lang = customer.get("identity", {}).get("language_pref", "")
        return "hi" in lang.lower()

    langs = merchant.get("identity", {}).get("languages", [])
    return "hi" in langs


def get_language_pref(merchant: dict, customer: dict | None = None) -> str:
    if customer:
        return customer.get("identity", {}).get("language_pref", "en")
    langs = merchant.get("identity", {}).get("languages", ["en"])
    if "hi" in langs:
        return "hi-en mix"
    return langs[0] if langs else "en"


# ---------------------------------------------------------------------------
# Active offer helpers
# ---------------------------------------------------------------------------

def get_active_offers(merchant: dict) -> list[dict]:
    return [o for o in merchant.get("offers", []) if o.get("status") == "active"]


def get_offer_title(merchant: dict) -> Optional[str]:
    active = get_active_offers(merchant)
    return active[0]["title"] if active else None


def format_offer(offer: dict) -> str:
    return offer.get("title", "")


# ---------------------------------------------------------------------------
# Performance helpers
# ---------------------------------------------------------------------------

def get_performance(merchant: dict) -> dict:
    return merchant.get("performance", {})


def get_delta_7d(merchant: dict) -> dict:
    return get_performance(merchant).get("delta_7d", {})


def ctr_vs_peer(merchant: dict, category: dict, category_slug: str) -> str:
    """Return 'above', 'at', or 'below' peer median."""
    merchant_ctr = get_performance(merchant).get("ctr", 0)
    peer_ctr = get_category_peer_ctr(category_slug, category)
    if merchant_ctr >= peer_ctr * 1.05:
        return "above"
    elif merchant_ctr <= peer_ctr * 0.85:
        return "below"
    return "at"


def fmt_pct(val: float) -> str:
    """Format 0.18 → '+18%', -0.22 → '-22%'."""
    pct = int(round(val * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def fmt_ctr(ctr: float) -> str:
    return f"{ctr * 100:.1f}%"


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

def has_signal(merchant: dict, signal_prefix: str) -> bool:
    signals = merchant.get("signals", [])
    return any(s.startswith(signal_prefix) for s in signals)


def get_signal_value(merchant: dict, signal_prefix: str) -> Optional[str]:
    for s in merchant.get("signals", []):
        if s.startswith(signal_prefix):
            # e.g. "stale_posts:22d" → "22d"
            parts = s.split(":", 1)
            return parts[1] if len(parts) > 1 else None
    return None


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------

def get_digest_item(category: dict, item_id: str) -> Optional[dict]:
    for item in category.get("digest", []):
        if item.get("id") == item_id:
            return item
    return None


def get_top_digest(category: dict, kind: str | None = None) -> Optional[dict]:
    for item in category.get("digest", []):
        if kind is None or item.get("kind") == kind:
            return item
    return None


# ---------------------------------------------------------------------------
# Customer aggregate helpers
# ---------------------------------------------------------------------------

def get_customer_aggregate(merchant: dict) -> dict:
    return merchant.get("customer_aggregate", {})


def lapsed_count(merchant: dict) -> int:
    agg = get_customer_aggregate(merchant)
    return agg.get("lapsed_180d_plus", agg.get("lapsed_90d_plus", 0))


def total_unique(merchant: dict) -> int:
    agg = get_customer_aggregate(merchant)
    return agg.get("total_unique_ytd", 0)


def high_risk_adult_count(merchant: dict) -> int:
    return get_customer_aggregate(merchant).get("high_risk_adult_count", 0)
