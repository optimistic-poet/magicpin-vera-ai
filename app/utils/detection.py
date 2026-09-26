"""
app/utils/detection.py — Intent + auto-reply classification.

All classification is deterministic (keyword-based), no LLM required.
"""

from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Auto-reply patterns
# ---------------------------------------------------------------------------

AUTO_REPLY_PATTERNS = [
    r"thank you for (contacting|reaching|messaging)",
    r"our team will (respond|get back|reply)",
    r"we will (respond|get back|reply)",
    r"this is an? (automated|auto) (reply|response|message)",
    r"main ek automated",
    r"i am an automated",
    r"currently (unavailable|away|out of office)",
    r"will respond (shortly|soon|within)",
    r"team tak pahuncha",  # Hindi auto-reply pattern
    r"aapki madad ke liye.*automated",
]

_AUTO_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in AUTO_REPLY_PATTERNS]


def is_auto_reply(message: str) -> bool:
    """Return True if the message looks like a WhatsApp Business auto-reply."""
    msg = message.strip()
    for pattern in _AUTO_RE:
        if pattern.search(msg):
            return True
    return False


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

POSITIVE_PHRASES = [
    "yes", "sure", "ok", "okay", "haan", "ha ", "ha!", "let's do it",
    "lets do it", "do it", "go ahead", "proceed", "send it", "confirm",
    "sounds good", "great", "perfect", "chalega", "theek hai", "bilkul",
    "please do", "please send", "go for it", "done", "agreed", "absolutely",
    "of course", "ready", "let's go", "yep", "yup", "right", "start",
]

NEGATIVE_PHRASES = [
    "no", "nahi", "nope", "not interested", "don't", "dont", "stop",
    "later", "not now", "skip", "pass", "cancel", "no thanks", "no need",
    "not required", "nahin", "nahi chahiye", "band karo", "rehne do",
    "mat bhejo", "stop messaging", "unsubscribe", "opt out", "remove me",
    "don't message", "dont message",
]

QUESTION_PHRASES = [
    "how much", "kitna", "what is", "kya hai", "when", "kab", "who",
    "which", "where", "explain", "tell me", "bata", "details", "more info",
    "what does", "what will", "what would", "how does", "how will",
    "how many", "cost", "price", "charges", "fee", "amount",
    "include", "cover", "duration", "time", "slot", "available",
    "?",  # any question mark
]

LATER_PHRASES = [
    "later", "baad mein", "not now", "abhi nahi", "some other time",
    "tomorrow", "kal", "next week", "agle hafte", "remind me",
    "busy", "will check", "let me think", "thinking", "sochta hoon",
    "discuss with", "team ke saath", "get back to you",
]

HOSTILE_PHRASES = [
    "stop messaging", "stop sending", "spam", "useless", "waste",
    "bothering", "irritating", "annoying", "disturbing", "abuse",
    "band karo", "mat karo", "chodo", "bekar", "faltu",
    "why are you", "please stop", "do not contact",
]


def classify_intent(message: str) -> str:
    """
    Returns one of: "positive", "negative", "question", "later",
                    "hostile", "auto_reply", "curveball", "unknown"

    Priority: auto_reply > hostile > positive (strong) > later > question > negative > unknown
    Positive is checked BEFORE question so "Ok let's do it. What's next?" resolves to positive.
    """
    msg = message.strip().lower()

    if is_auto_reply(message):
        return "auto_reply"

    # Check hostile first (subset of negative)
    if any(p in msg for p in HOSTILE_PHRASES):
        return "hostile"

    # Strong positive check BEFORE question: "ok lets do it" beats "whats next"
    pos_score = sum(1 for p in POSITIVE_PHRASES if p in msg)
    neg_score = sum(1 for p in NEGATIVE_PHRASES if p in msg)

    if pos_score > 0 and pos_score >= neg_score:
        return "positive"

    # Later: must check before generic negative — "not now busy check later" is later not negative
    later_hit = any(p in msg for p in LATER_PHRASES)
    if later_hit:
        return "later"

    # Check for questions
    if any(p in msg for p in QUESTION_PHRASES):
        return "question"

    if neg_score > 0:
        return "negative"

    return "unknown"


# ---------------------------------------------------------------------------
# GST / out-of-scope detection
# ---------------------------------------------------------------------------

OUT_OF_SCOPE_PATTERNS = [
    r"\bgst\b", r"\btax\b", r"\bloan\b", r"\binsurance\b", r"\blegal\b",
    r"\blawyer\b", r"\bdoctor.*refer\b", r"\bca\b", r"\bchartered",
    r"\baccounting\b", r"\bcompliance.*other\b",
]
_SCOPE_RE = [re.compile(p, re.IGNORECASE) for p in OUT_OF_SCOPE_PATTERNS]


def is_out_of_scope(message: str) -> bool:
    """Return True if merchant is asking about something Vera can't help with."""
    for pattern in _SCOPE_RE:
        if pattern.search(message):
            return True
    return False
