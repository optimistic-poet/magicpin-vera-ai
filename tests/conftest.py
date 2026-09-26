"""
Shared test fixtures for all test modules.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.state import context_store, conversation_store


@pytest.fixture(autouse=True)
def reset_stores():
    """Clear all state before each test."""
    context_store.clear()
    # Reset conversation store
    conversation_store._convs.clear()
    conversation_store._suppressed_keys.clear()
    conversation_store._suppressed_merchants.clear()
    conversation_store._merchant_auto_replies.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Sample payloads matching the challenge dataset schemas
# ---------------------------------------------------------------------------

SAMPLE_CATEGORY = {
    "slug": "dentists",
    "display_name": "Dentists",
    "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"]},
    "offer_catalog": [
        {"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "audience": "new_user"},
    ],
    "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030, "avg_reviews": 62},
    "digest": [
        {
            "id": "d_2026W17_jida_fluoride",
            "kind": "research",
            "title": "3-month fluoride varnish recall outperforms 6-month for high-risk adult caries",
            "source": "JIDA Oct 2026, p.14",
            "trial_n": 2100,
            "patient_segment": "high_risk_adults",
            "summary": "38% lower caries recurrence with 3-month vs 6-month recall.",
            "actionable": "Reassess recall interval for high-risk adults",
        }
    ],
    "patient_content_library": [],
    "seasonal_beats": [{"month_range": "Nov-Feb", "note": "exam-stress bruxism spike"}],
    "trend_signals": [{"query": "clear aligners delhi", "delta_yoy": 0.62}],
}

SAMPLE_MERCHANT = {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
        "name": "Dr. Meera's Dental Clinic",
        "city": "Delhi",
        "locality": "Lajpat Nagar",
        "place_id": "ChIJ_TEST",
        "verified": True,
        "languages": ["en", "hi"],
        "owner_first_name": "Meera",
        "established_year": 2018,
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
    "performance": {
        "window_days": 30,
        "views": 2410, "calls": 18, "directions": 45,
        "ctr": 0.021, "leads": 9,
        "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05},
    },
    "offers": [
        {"id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active", "started": "2026-03-01"},
    ],
    "conversation_history": [],
    "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78,
                           "retention_6mo_pct": 0.38, "high_risk_adult_count": 124},
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort"],
    "review_themes": [],
}

SAMPLE_TRIGGER_RESEARCH = {
    "id": "trg_001_research_digest_dentists",
    "scope": "merchant",
    "kind": "research_digest",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": None,
    "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
    "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2027-05-03T00:00:00Z",
}

SAMPLE_CUSTOMER = {
    "customer_id": "c_001_priya_for_m001",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {"name": "Priya", "phone_redacted": "<phone>", "language_pref": "hi-en mix", "age_band": "25-35"},
    "relationship": {"first_visit": "2025-11-04", "last_visit": "2026-05-12", "visits_total": 4,
                     "services_received": ["cleaning", "whitening", "cleaning"],
                     "lifetime_value": 1696},
    "state": "lapsed_soft",
    "preferences": {"preferred_slots": "weekday_evening", "channel": "whatsapp", "reminder_opt_in": True},
    "consent": {"opted_in_at": "2025-11-04", "scope": ["recall_reminders", "appointment_reminders"]},
}

SAMPLE_TRIGGER_RECALL = {
    "id": "trg_003_recall_due_priya",
    "scope": "customer",
    "kind": "recall_due",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {
        "service_due": "6_month_cleaning",
        "last_service_date": "2026-05-12",
        "due_date": "2026-11-12",
        "available_slots": [
            {"iso": "2026-11-05T18:00:00+05:30", "label": "Wed 5 Nov, 6pm"},
            {"iso": "2026-11-06T17:00:00+05:30", "label": "Thu 6 Nov, 5pm"},
        ],
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo",
    "expires_at": "2027-11-30T00:00:00Z",
}
