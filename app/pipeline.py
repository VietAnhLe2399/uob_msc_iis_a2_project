"""One request: prompt -> model -> validator (retry once) -> checker (SPEC §1 steps 3-5)."""
from dataclasses import dataclass, field
from typing import List, Optional

from app.checker import CheckReport, check_plan
from app.models import Plan, Profile
from app.prompt import INSTRUCTION, build_user_message
from app.validator import validate

DECLINE_TEXT = "I couldn't produce a plan I can check. Try again or change your question."


@dataclass
class Result:
    plan: Optional[Plan] = None
    report: Optional[CheckReport] = None
    raw_outputs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    status: str = "ok"  # ok | profile_change | model_declined | system_declined


def run(profile: Profile, question: str, client, funds: dict, failed_rules=None) -> Result:
    result = Result()
    validator_errors = None
    for _attempt in range(2):  # first call + one retry (V-rules)
        user = build_user_message(profile, question, funds, failed_rules, validator_errors)
        try:
            raw = client.generate(INSTRUCTION, user)
        except Exception as exc:  # network, quota, missing key
            result.errors.append(f"model call failed: {exc.__class__.__name__}: {exc}")
            break
        result.raw_outputs.append(raw)
        plan, validator_errors = validate(raw, funds)
        if plan is not None:
            result.plan = plan
            if plan.profile_change_suggested:
                result.status = "profile_change"
            elif not plan.holdings:
                result.status = "model_declined"
            else:
                result.report = check_plan(profile, plan, funds)
            return result
        result.errors.extend(validator_errors)
    result.status = "system_declined"
    return result
