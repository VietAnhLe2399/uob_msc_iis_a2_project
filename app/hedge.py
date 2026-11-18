"""Hedge wording from fixed templates (SPEC §6). The LLM never writes the hedge."""
from app.checker import HoldingResult

BADGE = {"look_again": "Look again", "review": "Review", "checked": "Checked"}


def hedge_text(hr: HoldingResult) -> str:
    if hr.level == "look_again":
        main = [r for r in hr.reasons if r.scope == "holding"][0]
        return f"I'm not confident this suits you: {main.evidence}."
    if hr.level == "review":
        main = hr.reasons[0]
        more = len(hr.reasons) - 1
        tail = f" (and {more} more check{'s' if more > 1 else ''}, see Why?)" if more else ""
        return f"I'm unsure about this part of the plan: {main.evidence}{tail}."
    if not hr.passes:
        return "No problems found by the checks."
    text = "; ".join(hr.passes[:2])
    return text[0].upper() + text[1:] + "."


def not_checked_text(claims: list) -> str:
    labels = sorted({c.replace('_', ' ') for c in claims})
    return f"Not checked: {', '.join(labels)} claims. Nobody can verify forecasts."
