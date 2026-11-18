"""V-rules: check the SHAPE of the LLM output, not its truth (SPEC §4, L09)."""
import json
from typing import List, Optional, Tuple

from pydantic import ValidationError

from app.models import Plan


def validate(raw: str, funds: dict) -> Tuple[Optional[Plan], List[str]]:
    """Return (plan, errors). plan is None when any V-rule fails."""
    # V1: parses against the schema
    try:
        plan = Plan.model_validate(json.loads(_strip_fences(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        return None, [f"V1 schema: {_short(exc)}"]

    errors = []
    # An empty holdings list is the model's decline turn (out-of-scope question): allowed.
    if not plan.holdings:
        return plan, []
    # V2: closed universe
    unknown = [h.fund_id for h in plan.holdings if h.fund_id not in funds]
    if unknown:
        errors.append(f"V2 unknown fund(s): {', '.join(unknown)}. Use only fund IDs from the list.")
    # V3: weights sum to 100 (±1)
    total = sum(h.weight_pct for h in plan.holdings)
    if abs(total - 100) > 1:
        errors.append(f"V3 weights sum to {total}, must be 100.")
    # V5: each fund at most once
    ids = [h.fund_id for h in plan.holdings]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        errors.append(f"V5 fund(s) listed more than once: {', '.join(dups)}. Combine them into one holding.")
    # V4: 1-6 holdings
    if len(plan.holdings) > 6:
        errors.append(f"V4 {len(plan.holdings)} holdings, maximum is 6.")
    return (None, errors) if errors else (plan, [])


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return f"{loc}: {first['msg']}"
    return str(exc).splitlines()[0][:200] if str(exc) else exc.__class__.__name__
