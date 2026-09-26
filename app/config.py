"""
app/config.py — Bot identity and static metadata.
Edit these before submission.
"""

TEAM_NAME = "Vera-AI"
TEAM_MEMBERS = ["Yashika"]
MODEL = "deterministic-composer-v1"
APPROACH = (
    "Deterministic rule-based composer. Dispatches by trigger.kind; "
    "grounds every claim in pushed context; category-aware voice; "
    "state-machine conversation handling with auto-reply detection."
)
CONTACT_EMAIL = "yashika@example.com"
VERSION = "1.0.0"
SUBMITTED_AT = "2026-09-26T18:00:00Z"

# Server port (used in run scripts)
PORT = 8000
