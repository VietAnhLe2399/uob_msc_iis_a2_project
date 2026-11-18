"""Checker, validator and replay tests, including seeded errors with known faults (SPEC §9).

Seeded errors give ground truth: each case has a fault put there on purpose,
and the test asserts that the matching flag fires. This checks that hedges track
real, known problems rather than being attached at random (cf. Kim et al., 2024).
"""
import json
from pathlib import Path

import pytest

from app.checker import check_plan, with_removed
from app.funds import load_funds
from app.hedge import hedge_text
from app.models import Plan, Profile
from app.validator import validate

ROOT = Path(__file__).resolve().parent.parent
FUNDS = load_funds()


def plan(*holdings):
    return Plan(holdings=[{"fund_id": f, "weight_pct": w, "claims": c} for f, w, c in holdings])


def levels(report):
    return {fid: hr.level for fid, hr in report.holdings.items()}


def failed(report):
    return sorted({r.rule for r in report.failed_rules})


def load_replay(name):
    return json.loads((ROOT / "replays" / f"{name}.json").read_text())


LOW_3Y = Profile(goal="house_deposit", horizon_years=3, risk="low", amount_gbp=10000)
MED_12Y = Profile(goal="retirement", horizon_years=12, risk="medium", amount_gbp=20000)
HIGH_12Y = Profile(goal="general_growth", horizon_years=12, risk="high", amount_gbp=20000)


# ---------- Replay scenarios: the storyboards must match the checker ----------

def test_scenario_1_one_false_claim_is_a_description_problem():
    s = load_replay("scenario_1")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert failed(r) == ["R4"]
    assert levels(r)["F09"] == "review"
    assert hedge_text(r.holdings["F09"]).startswith("The model's description doesn't match")
    assert all(v == "checked" for k, v in levels(r).items() if k != "F09")
    assert "growth" in r.holdings["F09"].not_checked


def test_scenario_2_concentrated_plan():
    s = load_replay("scenario_2")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert failed(r) == ["R1", "R2", "R3", "R5"]
    assert levels(r) == {"F07": "look_again", "F02": "review", "F15": "checked"}
    assert round(r.metrics["equity_pct"]) == 85 and round(r.metrics["equity_in_us"]) == 71
    assert r.notice is not None  # H0


def test_scenario_2_regenerated_plan_passes():
    s = load_replay("scenario_2")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][1]), FUNDS)
    assert failed(r) == [] and set(levels(r).values()) == {"checked"}


def test_scenario_3_repair_then_cautious_plan():
    s = load_replay("scenario_3")
    first = Plan(**s["calls"][0])
    assert first.holdings == [] and first.profile_change_suggested.field == "horizon_years"
    r = check_plan(Profile(**{**s["profile"], "horizon_years": 1}), Plan(**s["calls"][1]), FUNDS)
    assert failed(r) == [] and r.notice is not None


def test_live_groq_replay_flags():
    s = load_replay("live_groq")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert {"R1", "R4"} <= set(failed(r))
    lv = levels(r)
    assert lv["F01"] == "review" and lv["F10"] == "review" and lv["F02"] == "review"
    assert lv["F12"] == "checked"


# ---------- Seeded errors: one known fault per case ----------

def test_seeded_false_low_risk_claim_is_description_review():
    r = check_plan(MED_12Y, plan(("F07", 10, ["low_risk"]), ("F12", 90, [])), FUNDS)
    assert failed(r) == ["R4"] and levels(r) == {"F07": "review", "F12": "checked"}
    assert hedge_text(r.holdings["F07"]).startswith("The model's description")


def test_seeded_false_low_cost_claim():
    r = check_plan(MED_12Y, plan(("F09", 10, ["low_cost"]), ("F02", 60, []), ("F12", 30, [])), FUNDS)
    assert failed(r) == ["R4"] and levels(r)["F09"] == "review"


def test_seeded_sector_concentration_is_look_again():
    r = check_plan(MED_12Y, plan(("F08", 40, []), ("F12", 60, [])), FUNDS)
    assert failed(r) == ["R2"] and levels(r) == {"F08": "look_again", "F12": "checked"}


def test_seeded_us_overweight_flags_only_the_us_fund():
    r = check_plan(MED_12Y, plan(("F03", 70, []), ("F12", 30, [])), FUNDS)
    assert failed(r) == ["R3"]
    assert levels(r) == {"F03": "review", "F12": "checked"}


def test_seeded_single_market_uk_is_caught():
    r = check_plan(HIGH_12Y, plan(("F01", 100, [])), FUNDS)
    assert failed(r) == ["R3"] and levels(r) == {"F01": "review"}


def test_one_global_fund_is_fine():
    r = check_plan(HIGH_12Y, plan(("F02", 100, ["diversified"])), FUNDS)
    assert failed(r) == []


def test_seeded_equity_too_high_flags_only_funds_over_limit():
    r = check_plan(LOW_3Y, plan(("F02", 50, []), ("F11", 20, []), ("F16", 30, [])), FUNDS)
    assert "R1" in failed(r)
    assert levels(r) == {"F02": "review", "F11": "checked", "F16": "checked"}  # F11 is only 20% shares


def test_correct_claim_on_cash_fund_is_not_flagged():
    r = check_plan(LOW_3Y, plan(("F16", 60, ["low_risk", "income"]), ("F14", 40, ["low_risk"])), FUNDS)
    assert failed(r) == [] and set(levels(r).values()) == {"checked"}


def test_unverifiable_claims_are_never_passed():
    hr = check_plan(MED_12Y, plan(("F02", 100, ["growth", "other"])), FUNDS).holdings["F02"]
    assert hr.not_checked == ["growth", "other"] and not any("growth" in p for p in hr.passes)


@pytest.mark.parametrize("years,risk,limit", [(4, "high", 20), (5, "low", 40), (10, "high", 80), (11, "medium", 80)])
def test_r1_horizon_bands(years, risk, limit):
    p = Profile(goal="general_growth", horizon_years=years, risk=risk, amount_gbp=5000)
    r1 = [r for r in check_plan(p, plan(("F02", 100, [])), FUNDS).rules if r.rule == "R1"][0]
    assert r1.threshold == limit


# ---------- User edits: removing a holding re-runs the checks ----------

def test_remove_keeps_weight_as_cash_and_rechecks():
    s = load_replay("scenario_2")
    p0 = Plan(**s["calls"][0])
    p1 = with_removed(p0, {"F07"})
    assert {h.fund_id: h.weight_pct for h in p1.holdings} == {"F02": 35, "F15": 15, "F16": 50}
    r = check_plan(Profile(**s["profile"]), p1, FUNDS)
    assert "R2" not in failed(r) and "R1" in failed(r)  # sector problem gone, still too many shares
    assert sum(h.weight_pct for h in p0.holdings) == 100  # original plan untouched


# ---------- Validator (shape, not truth) ----------

def test_validator_unknown_fund():
    p, errors = validate(json.dumps({"holdings": [{"fund_id": "F99", "weight_pct": 100}]}), FUNDS)
    assert p is None and errors[0].startswith("V2")


def test_validator_weights_not_100():
    raw = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 60}, {"fund_id": "F12", "weight_pct": 30}]})
    p, errors = validate(raw, FUNDS)
    assert p is None and errors[0].startswith("V3")


def test_validator_too_many_holdings():
    hs = [{"fund_id": f"F0{i}", "weight_pct": 10} for i in range(1, 8)] + [{"fund_id": "F12", "weight_pct": 30}]
    p, errors = validate(json.dumps({"holdings": hs}), FUNDS)
    assert p is None and any(e.startswith("V4") for e in errors)


def test_validator_not_json():
    p, errors = validate("Sure! Here is a plan: put everything in tech.", FUNDS)
    assert p is None and errors[0].startswith("V1")


def test_validator_bad_claim_tag():
    raw = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 100, "claims": ["safe"]}]})
    p, errors = validate(raw, FUNDS)
    assert p is None and errors[0].startswith("V1")


def test_validator_accepts_fenced_json_and_decline():
    p, errors = validate('```json\n{"holdings": [], "summary": "Out of scope."}\n```', FUNDS)
    assert errors == [] and p.holdings == []


# ---------- Replay client and prompt versions ----------

def test_replay_exhausted_is_reported_not_repeated():
    from app.llm_client import ReplayClient
    from app.pipeline import run
    s = load_replay("scenario_1")
    client = ReplayClient("scenario_1")
    assert run(Profile(**s["profile"]), s["question"], client, FUNDS).status == "ok"
    second = run(Profile(**s["profile"]), s["question"], client, FUNDS)
    assert second.status == "system_declined" and "no further recorded" in second.errors[0]


def test_prompt_v2_adds_claim_definitions_only():
    from app.prompt import INSTRUCTION_V1, get_instruction
    v2 = get_instruction("v2")
    assert v2.startswith(INSTRUCTION_V1.split("Return JSON only")[0].rstrip()[:200])
    assert "Claim meanings" in v2 and "Claim meanings" not in INSTRUCTION_V1


# ---------- Edge cases seen as possible from live models ----------

def test_validator_duplicate_fund():
    raw = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 50}, {"fund_id": "F02", "weight_pct": 50}]})
    p, errors = validate(raw, FUNDS)
    assert p is None and errors[0].startswith("V5")


@pytest.mark.parametrize("field,value,ok", [("horizon_years", "1", True), ("horizon_years", "next year", False),
                                            ("goal", "wedding", False), ("risk", "very low", False),
                                            ("risk", "low", True), ("horizon_years", "45", False)])
def test_profile_change_is_validated(field, value, ok):
    from app.models import ProfileChange, apply_profile_change
    new = apply_profile_change(MED_12Y, ProfileChange(field=field, value=value, quote="..."))
    assert (new is not None) == ok


def test_prompt_v3_scopes_profile_changes():
    from app.prompt import get_instruction
    v3 = get_instruction("v3")
    assert "Claim meanings" in v3 and "is NOT a profile change" in v3
    assert "is NOT a profile change" not in get_instruction("v2")


# ---------- R6: the user's explicit request vs the plan ----------

def test_request_reduced_without_explanation():
    from app.checker import check_request
    s = load_replay("scenario_4")
    rr = check_request(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert rr.status == "reduced_unexplained" and rr.actual_pct == 20 and rr.requested_pct == 50
    assert rr.profile_cap == 30 and not rr.passed


def test_request_reduced_with_explanation():
    from app.checker import check_request
    s = load_replay("scenario_4")
    rr = check_request(Profile(**s["profile"]), Plan(**s["calls"][1]), FUNDS)
    assert rr.status == "reduced_explained" and rr.passed and "30%" in rr.note


def test_request_followed_for_a_market():
    from app.checker import check_request
    from app.models import RequestedFocus
    p = Plan(holdings=[{"fund_id": "F03", "weight_pct": 40}, {"fund_id": "F12", "weight_pct": 60}],
             requested_focus=RequestedFocus(target="US", min_pct=40, quote="put 40% in America"))
    rr = check_request(MED_12Y, p, FUNDS)
    assert rr.status == "followed" and rr.profile_cap == 60


def test_no_request_no_result():
    from app.checker import check_request
    assert check_request(MED_12Y, plan(("F02", 100, [])), FUNDS) is None


def test_live_groq_v4_ai_replay_all_three_badges_and_request_followed():
    from app.checker import check_request
    s = load_replay("live_groq_v4_ai")
    p, prof = Plan(**s["calls"][0]), Profile(**s["profile"])
    r = check_plan(prof, p, FUNDS)
    assert set(levels(r).values()) == {"look_again", "review", "checked"}
    assert check_request(prof, p, FUNDS).status == "followed"


# ---------- Model list filtering (live lists come from the providers' APIs) ----------

def test_filter_groq_models_keeps_active_chat_models():
    from app.llm_client import filter_groq_models
    raw = [{"id": "openai/gpt-oss-120b", "active": True}, {"id": "llama-3.1-8b-instant", "active": True},
           {"id": "whisper-large-v3", "active": True}, {"id": "playai-tts", "active": True},
           {"id": "meta-llama/llama-guard-4-12b", "active": True}, {"id": "old-model", "active": False}]
    assert filter_groq_models(raw) == ["llama-3.1-8b-instant", "openai/gpt-oss-120b"]


def test_filter_gemini_models_keeps_generate_content():
    from app.llm_client import filter_gemini_models
    raw = [{"name": "models/gemini-3.8-flash", "supported_actions": ["generateContent", "countTokens"]},
           {"name": "models/gemini-2.5-pro", "supported_actions": ["generateContent"]},
           {"name": "models/text-embedding-004", "supported_actions": ["embedContent"]},
           {"name": "models/gemini-embedding-001", "supported_actions": ["embedContent", "generateContent"]},
           {"name": "models/gemini-2.5-flash-image", "supported_actions": ["generateContent"]},
           {"name": "models/gemini-2.0-flash-live", "supported_actions": ["bidiGenerateContent"]}]
    assert filter_gemini_models(raw) == ["gemini-3.8-flash", "gemini-2.5-pro"]


# ---------- Provider-side JSON rejection is retried like V1, and errors stay short ----------

class _RejectThenAnswer:
    """Fake client: first call fails like Groq's json_validate_failed, second returns a valid plan."""
    def __init__(self, second):
        self.calls, self.second = 0, second

    def generate(self, system, user):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Error code: 400 - {'error': {'message': 'Failed to generate JSON.', "
                               "'code': 'json_validate_failed', 'failed_generation': '" + "x" * 5000 + "'}}")
        return self.second


def test_provider_json_rejection_is_retried_once():
    from app.pipeline import run
    good = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 100}]})
    client = _RejectThenAnswer(good)
    res = run(MED_12Y, "", client, FUNDS)
    assert client.calls == 2 and res.status == "ok"
    assert "Return only the JSON object" not in res.errors[0] and res.errors[0].startswith("V1 provider")


def test_provider_json_rejection_twice_declines_with_short_errors():
    from app.pipeline import run

    class AlwaysReject(_RejectThenAnswer):
        def generate(self, system, user):
            self.calls += 1
            raise RuntimeError("Error code: 400 - json_validate_failed " + "y" * 5000)
    res = run(MED_12Y, "", AlwaysReject(None), FUNDS)
    assert res.status == "system_declined" and all(len(e) < 500 for e in res.errors)


def test_selectable_models_are_verified_and_still_served():
    from app.llm_client import load_working_models, selectable_models
    working = {"groq": {"a": "note", "b": "note"}}
    assert selectable_models("groq", ["b", "c"], working) == ["b"]
    assert selectable_models("groq", None, working) == ["a", "b"]
    assert "openai/gpt-oss-120b" in load_working_models()["groq"]


# ---------- The user's "keep my profile" decision wins over the model ----------

class _Sequence:
    """Fake client returning the given raw outputs in order and recording the prompts it saw."""
    def __init__(self, *outputs):
        self.outputs, self.prompts = list(outputs), []

    def generate(self, system, user):
        self.prompts.append(user)
        return self.outputs.pop(0)


CHANGE_ONLY = json.dumps({"holdings": [], "profile_change_suggested":
                          {"field": "risk", "value": "high", "quote": "most of my money in AI"}, "summary": "confirm"})
PLAN = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 60}, {"fund_id": "F12", "weight_pct": 40}]})


def test_keep_profile_is_sent_to_model_and_change_is_refused():
    from app.pipeline import run
    client = _Sequence(CHANGE_ONLY, PLAN)  # model insists once, then complies
    res = run(MED_12Y, "most of my money in AI", client, FUNDS, keep_profile=True)
    assert res.status == "ok" and len(client.prompts) == 2
    assert "chose to keep it" in client.prompts[0] and "V6" in client.prompts[1]


def test_keep_profile_drops_a_change_attached_to_a_plan():
    from app.pipeline import run
    both = json.dumps({**json.loads(PLAN), "profile_change_suggested":
                       {"field": "risk", "value": "high", "quote": "AI"}})
    res = run(MED_12Y, "AI", _Sequence(both), FUNDS, keep_profile=True)
    assert res.status == "ok" and res.plan.profile_change_suggested is None and res.report is not None


def test_without_keep_profile_a_change_is_still_offered():
    from app.pipeline import run
    assert run(MED_12Y, "AI", _Sequence(CHANGE_ONLY), FUNDS).status == "profile_change"
