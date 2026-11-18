"""Prompt for the main model call (SPEC §7).

INSTRUCTION is the designer's text, versioned like code. Everything in
build_user_message() is information assembled per call (L09: keep them apart).

Design note: the instruction does NOT include the checker's thresholds. The model
plays a general adviser; the checker stays an independent second look. Failed
rules are only passed back on an explicit "Suggest again" request.
"""
import json

from app.funds import funds_as_text
from app.models import Profile

PROMPT_VERSION = "v1 (2026-11-17)"

INSTRUCTION = """You suggest simple investment plans for beginner private investors in the UK.

Task: propose 1 to 6 holdings for the user's confirmed profile, using ONLY funds from the fund list provided.

Rules:
- Use only fund_id values that appear in the fund list. Never invent funds.
- weight_pct values are whole numbers of at least 5 and must add up to exactly 100.
- For each holding, add claims chosen only from: low_risk, low_cost, diversified, income, growth, other.
- reason: plain English, at most 30 words. summary: at most 40 words.
- Never change the user's profile yourself. If the user's message implies a different goal, time horizon,
  risk level or amount, put it in profile_change_suggested (field, value, and the user's own words as quote),
  return an empty holdings list, and say in summary that the profile must be confirmed first.
- Do not present forecasts of returns as facts.
- If the question is not about building an investment plan from these funds, return an empty holdings list
  and explain briefly in summary.

Return JSON only, matching this shape:
{"holdings": [{"fund_id": "F02", "weight_pct": 60, "claims": ["diversified"], "reason": "..."}],
 "profile_change_suggested": null,
 "summary": "..."}"""


def build_user_message(profile: Profile, question: str, funds: dict,
                       failed_rules=None, validator_errors=None) -> str:
    parts = [
        "Confirmed profile (JSON):",
        json.dumps(profile.model_dump()),
        "",
        "Fund list (CSV):",
        funds_as_text(funds),
        "",
        f"User message: {question.strip() or 'Please suggest a plan for my profile.'}",
    ]
    if failed_rules:
        parts += ["", "The user asked for a new plan within their profile. "
                      "Your previous plan failed these suitability checks:"]
        parts += [f"- {r.rule}: {r.evidence} (limit {r.threshold})" for r in failed_rules]
        parts += ["Propose a new plan that avoids these problems."]
    if validator_errors:
        parts += ["", "Your previous output was rejected for these reasons. Fix them and return JSON only:"]
        parts += [f"- {e}" for e in validator_errors]
    return "\n".join(parts)
