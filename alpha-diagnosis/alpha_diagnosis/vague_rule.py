from __future__ import annotations

import re

_ACTION_PHRASES: tuple[tuple[str, str], ...] = (
    ("more-cool", "increasing cooling effort"),
    ("more_cool", "increasing cooling effort"),
    ("more-cooling", "increasing cooling effort"),
    ("pre_cool", "proactive cooling"),
    ("pre-cool", "proactive cooling"),
    ("defer", "deferring flexible workloads"),
    ("execute", "executing queued workloads"),
    ("discharge", "using battery discharge"),
    ("idle", "keeping the battery idle"),
)

_SITUATION_REWRITES: tuple[tuple[str, str], ...] = (
    (r"high carbon[- ]intensity", "carbon intensity is high"),
    (r"warm outdoor[- ]temp(?:erature)?", "outdoor temperature is warm"),
    (r"hot outdoor[- ]temp(?:erature)?", "outdoor temperature is hot"),
    (r"load[- ]shifting queue fill(?: ratio)?(?: is)? high", "the load-shifting queue is crowded"),
    (r"queue fill(?: ratio)?(?: is)? high", "the load-shifting queue is crowded"),
    (r"battery soc(?: is)? high", "battery state of charge is high"),
    (r"future carbon intensity(?: mean)?(?: is)? high", "expected future carbon intensity is high"),
    (r"future outdoor temperature(?: is)? high", "expected future outdoor temperature is high"),
    (r"outdoor temperature(?: \(normalized\))?(?: is)? high", "outdoor temperature is high"),
)


def _extract_behavior(description: str, name: str) -> str:
    combined = f"{description} {name}".lower()
    for token, phrase in _ACTION_PHRASES:
        if token in combined:
            return phrase
    return name.replace("_", " ")


def _extract_situation(description: str) -> str:
    text = description.strip()
    lower = text.lower()
    if "accounts for" in lower:
        text = text[: lower.index("accounts for")].strip()

    if lower.startswith("overall"):
        return "In general operation"

    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"^On\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+steps\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"agent_\w+\s+", "", text, flags=re.IGNORECASE)

    for pattern, replacement in _SITUATION_REWRITES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = re.sub(
        r",?\s*(defer|execute|discharge|idle|more[- ]cool(?:ing)?|pre[- ]cool)\s*(?:\(\d+\))?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" ,.")

    if not text:
        return "In relevant operating conditions"

    if text.lower().startswith(("when ", "in ", "under ", "during ")):
        return text[0].upper() + text[1:]
    return f"When {text.lower()}"


def vagueify_rule_description(name: str, description: str) -> str:
    """Turn a discovery rule description into natural-language guidance without fractions."""
    situation = _extract_situation(description)
    behavior = _extract_behavior(description, name)
    return f"{situation}, {behavior} tends to be important for higher scores."
