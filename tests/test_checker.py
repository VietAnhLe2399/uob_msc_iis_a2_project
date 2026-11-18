"""Checker and validator tests, including seeded errors with known faults (SPEC §9).

Seeded errors give ground truth: each case has a fault we put there on purpose,
and the test asserts that the matching flag fires. This is how we check that the
hedges track real, known problems rather than being attached at random.
"""
import json
from pathlib import Path

import pytest

from app.checker import check_plan
from app.funds import load_funds
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


LOW_3Y = Profile(goal="house_deposit", horizon_years=3, risk="low", amount_gbp=10000)
MED_12Y = Profile(goal="retirement", horizon_years=12, risk="medium", amount_gbp=20000)


# ---------- Replay scenarios: the storyboards must match the checker ----------

def load_replay(name):
    return json.loads((ROOT / "replays" / f"{name}.json").read_text())


def test_scenario_1_one_false_claim():
    s = load_replay("scenario_1")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert failed(r) == ["R4"]
    assert levels(r) == {"F02": "checked", "F01": "checked", "F10": "checked",
                         "F12": "checked", "F09": "look_again"}
    assert "growth" in r.holdings["F09"].not_checked
    assert r.notice is None


def test_scenario_2_concentrated_plan():
    s = load_replay("scenario_2")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][0]), FUNDS)
    assert failed(r) == ["R1", "R2", "R3", "R5"]
    assert levels(r) == {"F07": "look_again", "F02": "review", "F15": "checked"}
    assert round(r.metrics["equity_pct"]) == 85
    assert round(r.metrics["us_pct"]) == 71
    assert r.notice is not None  # H0: horizon under 5 years


def test_scenario_2_regenerated_plan_passes():
    s = load_replay("scenario_2")
    r = check_plan(Profile(**s["profile"]), Plan(**s["calls"][1]), FUNDS)
    assert failed(r) == []
    assert set(levels(r).values()) == {"checked"}


def test_scenario_3_repair_then_cautious_plan():
    s = load_replay("scenario_3")
    first = Plan(**s["calls"][0])
    assert first.holdings == [] and first.profile_change_suggested.field == "horizon_years"
    new_profile = Profile(**{**s["profile"], "horizon_years": 1})
    r = check_plan(new_profile, Plan(**s["calls"][1]), FUNDS)
    assert failed(r) == [] and r.notice is not None


# ---------- Seeded errors: one known fault per case ----------

def test_seeded_false_low_risk_claim():
    r = check_plan(MED_12Y, plan(("F07", 20, ["low_risk"]), ("F02", 80, [])), FUNDS)
    assert "R4" in failed(r)
    assert levels(r)["F07"] == "look_again"


def test_seeded_false_low_cost_claim():
    r = check_plan(MED_12Y, plan(("F09", 10, ["low_cost"]), ("F02", 90, [])), FUNDS)
    assert "R4" in failed(r) and levels(r)["F09"] == "look_again"


def test_seeded_sector_concentration():
    r = check_plan(MED_12Y, plan(("F08", 40, []), ("F12", 60, [])), FUNDS)
    assert "R2" in failed(r) and levels(r)["F08"] == "look_again"


def test_seeded_us_overweight():
    r = check_plan(MED_12Y, plan(("F03", 70, []), ("F12", 30, [])), FUNDS)
    assert "R3" in failed(r)
    assert levels(r) == {"F03": "review", "F12": "review"}  # both hold US assets


def test_seeded_equity_too_high_for_short_horizon():
    r = check_plan(LOW_3Y, plan(("F02", 50, []), ("F16", 50, [])), FUNDS)
    assert "R1" in failed(r) and levels(r)["F02"] == "review" and levels(r)["F16"] == "checked"


def test_unverifiable_claims_are_never_passed():
    r = check_plan(MED_12Y, plan(("F02", 100, ["growth", "other"])), FUNDS)
    hr = r.holdings["F02"]
    assert hr.not_checked == ["growth", "other"]
    assert not any("growth" in p for p in hr.passes)


@pytest.mark.parametrize("years,risk,limit", [(4, "high", 20), (5, "low", 40), (10, "high", 80), (11, "medium", 80)])
def test_r1_horizon_bands(years, risk, limit):
    p = Profile(goal="general_growth", horizon_years=years, risk=risk, amount_gbp=5000)
    r1 = [r for r in check_plan(p, plan(("F02", 100, [])), FUNDS).rules if r.rule == "R1"][0]
    assert r1.threshold == limit


# ---------- Validator (shape, not truth) ----------

def test_validator_unknown_fund():
    raw = json.dumps({"holdings": [{"fund_id": "F99", "weight_pct": 100}]})
    plan_, errors = validate(raw, FUNDS)
    assert plan_ is None and errors[0].startswith("V2")


def test_validator_weights_not_100():
    raw = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 60}, {"fund_id": "F12", "weight_pct": 30}]})
    plan_, errors = validate(raw, FUNDS)
    assert plan_ is None and errors[0].startswith("V3")


def test_validator_too_many_holdings():
    hs = [{"fund_id": f"F0{i}", "weight_pct": 10} for i in range(1, 8)] + [{"fund_id": "F12", "weight_pct": 30}]
    plan_, errors = validate(json.dumps({"holdings": hs}), FUNDS)
    assert plan_ is None and any(e.startswith("V4") for e in errors)


def test_validator_not_json():
    plan_, errors = validate("Sure! Here is a plan: put everything in tech.", FUNDS)
    assert plan_ is None and errors[0].startswith("V1")


def test_validator_bad_claim_tag():
    raw = json.dumps({"holdings": [{"fund_id": "F02", "weight_pct": 100, "claims": ["safe"]}]})
    plan_, errors = validate(raw, FUNDS)
    assert plan_ is None and errors[0].startswith("V1")


def test_validator_accepts_fenced_json_and_decline():
    plan_, errors = validate('```json\n{"holdings": [], "summary": "Out of scope."}\n```', FUNDS)
    assert errors == [] and plan_.holdings == []
