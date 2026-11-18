"""Suitability checker: deterministic rules R1-R5 + H0 notice (SPEC §5).

The checker never reads the model's prose. It only uses the confirmed profile,
the structured plan (fund IDs, weights, claim tags) and fund data from funds.csv.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.models import Plan, Profile

# --- Thresholds (SPEC §5; see §12 for sources and which values are assumptions) ---
EQUITY_LIMIT = {  # R1: horizon band -> risk -> max equity %
    "<5": {"low": 20, "medium": 20, "high": 20},
    "5-10": {"low": 40, "medium": 60, "high": 80},
    ">10": {"low": 60, "medium": 80, "high": 100},
}
SECTOR_CAP = {"low": 20, "medium": 30, "high": 40}  # R2 (assumption)
US_CAP = 60  # R3 (Winder et al., 2025 benchmark ~59%)
RISK_CAP = {"low": 3, "medium": 5, "high": 6}  # R5 (assumption on SRRI-style scale)
LOW_COST_MAX = 0.25  # R4 low_cost
NON_THEMATIC = {"diversified", "government", "cash"}
UNCHECKABLE_CLAIMS = {"growth", "other"}

LEVEL_ORDER = {"checked": 0, "review": 1, "look_again": 2}


def horizon_band(years: int) -> str:
    if years < 5:
        return "<5"
    return "5-10" if years <= 10 else ">10"


@dataclass
class RuleResult:
    rule: str
    passed: bool
    scope: str  # "portfolio" or "holding"
    evidence: str
    fund_ids: List[str] = field(default_factory=list)  # holdings touched when failed
    threshold: Optional[float] = None
    value: Optional[float] = None


@dataclass
class HoldingResult:
    fund_id: str
    weight_pct: int
    level: str = "checked"
    reasons: List[RuleResult] = field(default_factory=list)  # failed rules touching it
    passes: List[str] = field(default_factory=list)  # pass evidence for this holding
    not_checked: List[str] = field(default_factory=list)  # unverifiable claims


@dataclass
class CheckReport:
    rules: List[RuleResult]
    holdings: Dict[str, HoldingResult]
    notice: Optional[str] = None  # H0
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def failed_rules(self) -> List[RuleResult]:
        return [r for r in self.rules if not r.passed]


H0_TEXT = ("Money needed within 5 years is usually kept in savings rather than invested. "
           "You can still see suggestions, but treat them with extra care.")


def check_plan(profile: Profile, plan: Plan, funds: dict) -> CheckReport:
    hs = plan.holdings
    f = {h.fund_id: funds[h.fund_id] for h in hs}
    rules: List[RuleResult] = []

    # Metrics (SPEC §5 definitions)
    equity = sum(h.weight_pct * f[h.fund_id]["equity_pct"] / 100 for h in hs)
    us = sum(h.weight_pct * f[h.fund_id]["us_pct"] / 100 for h in hs)
    risk = sum(h.weight_pct * f[h.fund_id]["risk_level"] for h in hs) / 100
    sectors: Dict[str, int] = {}
    for h in hs:
        sector = f[h.fund_id]["sector"]
        if sector not in NON_THEMATIC:
            sectors[sector] = sectors.get(sector, 0) + h.weight_pct

    # R1 equity share
    eq_limit = EQUITY_LIMIT[horizon_band(profile.horizon_years)][profile.risk]
    rules.append(RuleResult(
        "R1", equity <= eq_limit, "portfolio",
        f"shares are {_n(equity)}% of the plan, above {eq_limit}% for your profile"
        if equity > eq_limit else
        f"shares are {_n(equity)}% of the plan, within {eq_limit}% for your profile",
        [h.fund_id for h in hs if f[h.fund_id]["equity_pct"] > 0] if equity > eq_limit else [],
        eq_limit, equity))

    # R2 thematic sector concentration (holding scope)
    cap = SECTOR_CAP[profile.risk]
    for sector, share in sectors.items():
        ids = [h.fund_id for h in hs if f[h.fund_id]["sector"] == sector]
        ok = share <= cap
        rules.append(RuleResult(
            "R2", ok, "holding",
            f"one sector ({sector}) is {share}% of the plan, and your profile allows up to {cap}%"
            if not ok else f"{sector} is {share}% of the plan, within {cap}%",
            [] if ok else ids, cap, share))

    # R3 US share
    rules.append(RuleResult(
        "R3", us <= US_CAP, "portfolio",
        f"about {_n(us)}% of the plan is in US companies, above {US_CAP}%"
        if us > US_CAP else f"about {_n(us)}% is in US companies, within {US_CAP}%",
        [h.fund_id for h in hs if f[h.fund_id]["us_pct"] > 0] if us > US_CAP else [],
        US_CAP, us))

    # R4 structured claims vs fund data (holding scope)
    not_checked: Dict[str, List[str]] = {h.fund_id: [] for h in hs}
    passes: Dict[str, List[str]] = {h.fund_id: [] for h in hs}
    for h in hs:
        fund = f[h.fund_id]
        for claim in h.claims:
            if claim in UNCHECKABLE_CLAIMS:
                not_checked[h.fund_id].append(claim)
                continue
            ok, ev = _check_claim(claim, fund)
            if ok:
                passes[h.fund_id].append(ev)
            else:
                rules.append(RuleResult("R4", False, "holding", ev, [h.fund_id]))

    # R5 weighted risk
    rcap = RISK_CAP[profile.risk]
    rules.append(RuleResult(
        "R5", risk <= rcap, "portfolio",
        f"the average risk level is {risk:.1f} of 7, above {rcap} for your profile"
        if risk > rcap else f"the average risk level is {risk:.1f} of 7, within {rcap}",
        [h.fund_id for h in hs if f[h.fund_id]["risk_level"] > rcap] if risk > rcap else [],
        rcap, risk))

    # Per-holding level (SPEC §5 "Per-holding level")
    results = {h.fund_id: HoldingResult(h.fund_id, h.weight_pct,
                                        passes=passes[h.fund_id],
                                        not_checked=not_checked[h.fund_id]) for h in hs}
    for r in rules:
        if r.passed:
            continue
        level = "look_again" if r.scope == "holding" else "review"
        for fid in r.fund_ids:
            hr = results[fid]
            hr.reasons.append(r)
            if LEVEL_ORDER[level] > LEVEL_ORDER[hr.level]:
                hr.level = level
    for h in hs:  # holding-level pass evidence: its own risk level vs profile
        rl = f[h.fund_id]["risk_level"]
        if rl <= rcap:
            results[h.fund_id].passes.insert(0, f"Risk level {rl} of 7 is within your profile's limit of {rcap}")

    return CheckReport(
        rules=rules, holdings=results,
        notice=H0_TEXT if profile.horizon_years < 5 else None,
        metrics={"equity_pct": equity, "us_pct": us, "avg_risk": risk})


def _check_claim(claim: str, fund: dict):
    name = fund["name"]
    if claim == "low_risk":
        ok = fund["risk_level"] <= 3
        return ok, (f"described as low risk, and its risk level is {fund['risk_level']} of 7" if ok
                    else f"it is described as low risk, but its risk level is {fund['risk_level']} of 7")
    if claim == "low_cost":
        ok = fund["ongoing_charge_pct"] <= LOW_COST_MAX
        return ok, (f"described as low cost, and its yearly charge is {fund['ongoing_charge_pct']}%" if ok
                    else f"it is described as low cost, but its yearly charge is {fund['ongoing_charge_pct']}% "
                         f"(above {LOW_COST_MAX}%)")
    if claim == "diversified":
        ok = fund["sector"] == "diversified" and fund["region"] == "Global"
        return ok, (f"described as diversified, and it spreads across sectors worldwide" if ok
                    else (f"it is described as diversified, but {name} focuses on one sector ({fund['sector']})"
                          if fund["sector"] != "diversified"
                          else f"it is described as diversified, but it invests only in {fund['region']}"))
    if claim == "income":
        ok = fund["asset_class"] in {"bond", "mixed", "cash"}
        return ok, (f"described as income, and it holds {fund['asset_class']}" if ok
                    else f"it is described as income, but it is an {fund['asset_class']} fund")
    raise ValueError(claim)


def _n(x: float) -> str:
    return str(int(round(x)))
