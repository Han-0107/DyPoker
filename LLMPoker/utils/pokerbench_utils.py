"""Utility helpers for PokerBench data normalization.

These helpers are lightweight (regex + json only) so they can be reused by
training scripts or quick sanity tests without pulling heavy ML deps.
"""

from __future__ import annotations

import json
import re
from typing import Optional, Tuple

__all__ = ["parse_pokerbench_label", "build_action_json"]


def parse_pokerbench_label(label: str) -> Tuple[str, Optional[float]]:
    """Normalize a PokerBench label string to (action, raise_amount).

    Args:
        label: Raw label text from dataset (e.g. "Check", "Bet 5", "All in").

    Returns:
        action: fold/check/call/raise/all_in (lower-case)
        amount: numeric raise amount if action is raise, otherwise None
    """
    if label is None:
        return "check", None

    text = label.strip().lower()
    amount = None

    # Extract numeric amount if present (bet/raise strings)
    m = re.search(r"(bet|raise)\s*([0-9]+(\.[0-9]+)?)", text)
    if m:
        amount = float(m.group(2))
        action = "raise"
    elif "all" in text and "in" in text:
        action = "all_in"
    elif "fold" in text:
        action = "fold"
    elif "call" in text:
        action = "call"
    elif "check" in text:
        action = "check"
    else:
        # fallback: keep safest action
        action = "check"

    return action, amount


def build_action_json(action: str, amount: Optional[float], reasoning: str = "Optimal solver action") -> str:
    """Build a compact JSON string for training/inference supervision."""
    payload = {
        "reasoning": reasoning,
        "action": action,
    }
    if action == "raise" and amount is not None:
        payload["raise_amount"] = amount
    return json.dumps(payload, ensure_ascii=False)
