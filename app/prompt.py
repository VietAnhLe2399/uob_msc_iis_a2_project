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

import os

DEFAULT_PROMPT_VERSION = "v4"

INSTRUCTION_V1 = """You suggest simple investment plans for beginner private investors in the UK.

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


CLAIM_DEFINITIONS = """
Claim meanings (use a claim only if it is true of the fund itself, using the fund list):
- low_risk: the fund's risk_level is 3 or below.
- low_cost: the fund's ongoing_charge_pct is 0.25 or below.
- diversified: the fund itself holds many sectors across many countries (sector "diversified" and region "Global").
  Do not use it to mean "adds diversification to the plan".
- income: the fund holds bonds, cash or a bond/share mix.
- growth / other: your own view; these cannot be checked."""

# v2 (2026-11-17): adds claim definitions after live runs showed the model using "diversified"
# to mean "diversifies my plan" while the checker meant "the fund itself is diversified".
INSTRUCTION_V2 = INSTRUCTION_V1.replace("\n\nReturn JSON only", CLAIM_DEFINITIONS + "\n\nReturn JSON only")
PROFILE_CHANGE_SCOPE = """
What counts as a profile change: only a clear statement about when the money is needed, the amount, the goal,
or how much loss the user can accept (e.g. "I need it next year", "I can't afford to lose any of it").
An interest in a sector, theme or fund (e.g. "I'm excited about AI") is NOT a profile change: build a plan
for the confirmed profile and reflect the interest only as far as the profile allows."""

# v3 (2026-11-17): live run showed the model treating "I'm excited about AI and technology" as a request
# to change the risk level, so it returned no plan (the repair turn fired too eagerly).
INSTRUCTION_V3 = INSTRUCTION_V2.replace("\n\nReturn JSON only", PROFILE_CHANGE_SCOPE + "\n\nReturn JSON only")
REQUEST_FIELDS = """
If the user explicitly asks for a share of the plan in one sector or market (e.g. "most of my money in tech"),
fill requested_focus: target (one of: technology, healthcare, energy, US, UK, Europe, Emerging markets),
min_pct (the smallest percentage their words mean; "most" means 50), and quote (their exact words).
Otherwise set requested_focus to null.
If your plan gives them less than they asked for, say so and why in adjustment_note (at most 40 words);
otherwise leave adjustment_note empty."""

# v4 (2026-11-17): a live run answered "most of my money into AI" with 20% tech and a confident summary,
# without saying it had reduced the request. v4 asks the model to state the request it read and any reduction;
# the code then compares the request with the plan's actual share.
INSTRUCTION_V4 = INSTRUCTION_V3.replace("\n\nReturn JSON only", REQUEST_FIELDS + "\n\nReturn JSON only").replace(
    ' "profile_change_suggested": null,\n "summary": "..."}',
    ' "profile_change_suggested": null,\n "requested_focus": null,\n "adjustment_note": "",\n "summary": "..."}')
INSTRUCTIONS = {"v1": INSTRUCTION_V1, "v2": INSTRUCTION_V2, "v3": INSTRUCTION_V3, "v4": INSTRUCTION_V4}


def get_instruction(version: str = None) -> str:
    return INSTRUCTIONS[version or os.getenv("PROMPT_VERSION", DEFAULT_PROMPT_VERSION)]


KEEP_PROFILE_NOTE = ("The user was asked whether to change their profile and chose to keep it. "
                     "Do not propose a profile change. Build a plan for the confirmed profile above.")


def build_user_message(profile: Profile, question: str, funds: dict,
                       failed_rules=None, validator_errors=None, keep_profile=False) -> str:
    parts = [
        "Confirmed profile (JSON):",
        json.dumps(profile.model_dump()),
        "",
        "Fund list (CSV):",
        funds_as_text(funds),
        "",
        f"User message: {question.strip() or 'Please suggest a plan for my profile.'}",
    ]
    if keep_profile:
        parts += ["", KEEP_PROFILE_NOTE]
    if failed_rules:
        parts += ["", "The user asked for a new plan within their profile. "
                      "Your previous plan failed these suitability checks:"]
        parts += [f"- {r.rule}: {r.evidence} (limit {r.threshold})" for r in failed_rules]
        parts += ["Propose a new plan that avoids these problems."]
    if validator_errors:
        parts += ["", "Your previous output was rejected for these reasons. Fix them and return JSON only:"]
        parts += [f"- {e}" for e in validator_errors]
    return "\n".join(parts)
