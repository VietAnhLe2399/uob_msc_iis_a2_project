"""Hedge wording from fixed templates (SPEC §6). The LLM never writes the hedge."""
from app.checker import HoldingResult

BADGE = {"look_again": "Look again", "review": "Review", "checked": "Checked"}


def hedge_text(hr: HoldingResult) -> str:
    if hr.level == "look_again":
        main = [r for r in hr.reasons if r.scope == "holding"][0]
        return f"I'm not confident this suits you: {main.evidence}." + _more(hr, main)
    if hr.level == "review":
        main = hr.reasons[0]
        if main.scope == "description":
            return f"The model's description doesn't match the fund data: {main.evidence}." + _more(hr, main)
        return f"I'm unsure about this part of the plan: {main.evidence}." + _more(hr, main)
    if not hr.passes:
        return "No problems found by the checks."
    text = "; ".join(hr.passes[:2])
    return text[0].upper() + text[1:] + "."


def _more(hr: HoldingResult, main) -> str:
    more = len(hr.reasons) - 1
    return f" (+{more} more, see Why?)" if more else ""


def not_checked_text(claims: list) -> str:
    labels = sorted({c.replace('_', ' ') for c in claims})
    return f"Not checked: {', '.join(labels)} claims. Nobody can verify forecasts."
