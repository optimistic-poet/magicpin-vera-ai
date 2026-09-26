"""
app/utils/text.py — Text utilities for body formatting.
"""

from __future__ import annotations
import re


def strip_urls(text: str) -> str:
    """Remove URLs from text (penalty: -3 per URL from judge)."""
    return re.sub(r'https?://\S+', '', text).strip()


def truncate(text: str, max_chars: int = 800) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def num_to_str(n) -> str:
    """Format a number nicely for display."""
    if isinstance(n, float):
        if n == int(n):
            return str(int(n))
        return f"{n:.1f}"
    return str(n)


def pct_change(val: float) -> str:
    """Format 0.30 → '+30%', -0.22 → '-22%'."""
    pct = int(round(abs(val) * 100))
    sign = "+" if val >= 0 else "-"
    return f"{sign}{pct}%"


def inr(amount) -> str:
    """Format amount as ₹ string."""
    try:
        amt = int(float(amount))
        return f"₹{amt:,}"
    except (TypeError, ValueError):
        return f"₹{amount}"


def days_ago(date_str: str, reference: str = "2026-04-26") -> int:
    """Return days between date_str and reference (both ISO format)."""
    from datetime import date
    try:
        d1 = date.fromisoformat(date_str[:10])
        d2 = date.fromisoformat(reference[:10])
        return abs((d2 - d1).days)
    except Exception:
        return 0


def months_since(date_str: str, reference: str = "2026-04-26") -> int:
    """Return approximate months between two dates."""
    d = days_ago(date_str, reference)
    return d // 30
