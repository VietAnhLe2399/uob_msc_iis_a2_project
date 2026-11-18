"""Suitability checker: deterministic rules R1-R5 + H0 notice (SPEC §5, v0.3).

The checker never reads the model's prose. It only uses the confirmed profile,
the structured plan (fund IDs, weights, claim tags) and fund data from funds.csv.

Three kinds of finding, three meanings for the user:
  holding-scope (R2)      -> "look_again": this fund on its own does not suit the profile
  portfolio-scope (R1,R3,R5) -> "review" on the funds that are themselves over the limit
  description (R4)        -> "review": the model described the fund wrongly (not a suitability verdict)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.funds import COUNTRIES
from app.models import Plan, Profile

# --- Thresholds (SPEC §5; §12 lists sources and which values are assumptions) ---
EQUITY_LIMIT = {  # R1: horizon band -> risk -> max equity % of plan
    "<5": {"low": 20, "medium": 20, "high": 20},
    "5-10": {"low": 40, "medium": 60, "high": 80},
    ">10": {"low": 60, "medium": 80, "high": 100},
}
SECTOR_CAP = {"low": 20, "medium": 30, "high": 40}  # R2 (assumption)
MARKET_CAP = 60  # R3: equities in one market, % of plan (anchored on Winder et al., 2025: ~59% US in a global ETF)
RISK_CAP = {"low": 3, "medium": 5, "high": 6}  # R5 (assumption on SRRI-style 1-7 scale)
LOW_COST_MAX = 0.25  # R4 low_cost
NON_THEMATIC = {"diversified", "government", "cash"}
UNCHECKABLE_CLAIMS = {"growth", "other"}
CASH_FUND = "F16"  # where removed weight is parked when the user removes a holding

LEVEL_ORDER = {"checked": 0, "review": 1, "look_again": 2}
SCOPE_LEVEL = {"holding": "look_again", "portfolio": "review", "description": "review"}


def horizon_band(years: int) -> str:
    if years < 5:
        return "<5"
    return "5-10" if years <= 10 else ">10"


@dataclass
class RuleResult:
    rule: str
    passed: bool
    scope: str  # "portfolio" | "holding" | "description"
    evidence: str
    fund_ids: List[str] = field(default_factory=list)  # holdings flagged when failed
    threshold: Optional[float] = None
    value: Optional[float] = None


@dataclass
class HoldingResult:
    fund_id: str
    weight_pct: int
    level: str = "checked"
    reasons: List[RuleResult] = field(default_factory=list)  # failed rules touching it
    passes: List[str] = field(default_factory=list)
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

    def eq(h):  # equity points this holding adds to the plan
        return h.weight_pct * f[h.fund_id]["equity_pct"] / 100

    equity = sum(eq(h) for h in hs)
    risk = sum(h.weight_pct * f[h.fund_id]["risk_level"] for h in hs) / 100
    markets = {name: sum(eq(h) * f[h.fund_id][col] / 100 for h in hs) for col, name in COUNTRIES.items()}
    sectors: Dict[str, int] = {}
    for h in hs:
        sector = f[h.fund_id]["sector"]
        if sector not in NON_THEMATIC:
            sectors[sector] = sectors.get(sector, 0) + h.weight_pct

    # R1 equity share. Flag funds that are themselves above the limit.
    lim = EQUITY_LIMIT[horizon_band(profile.horizon_years)][profile.risk]
    over = equity > lim
    rules.append(RuleResult(
        "R1", not over, "portfolio",
        f"shares are {_n(equity)}% of the plan, above {lim}% for your profile" if over else
        f"shares are {_n(equity)}% of the plan, within {lim}% for your profile",
        [h.fund_id for h in hs if f[h.fund_id]["equity_pct"] > lim] if over else [], lim, equity))

    # R2 thematic sector concentration (holding scope)
    cap = SECTOR_CAP[profile.risk]
    for sector, share in sectors.items():
        ok = share <= cap
        rules.append(RuleResult(
            "R2", ok, "holding",
            f"one sector ({sector}) is {share}% of the plan, and your profile allows up to {cap}%"
            if not ok else f"{sector} is {share}% of the plan, within {cap}%",
            [] if ok else [h.fund_id for h in hs if f[h.fund_id]["sector"] == sector], cap, share))

    # R3 one-market concentration of equities. Flag funds whose own equity in that market exceeds the cap.
    for col, name in COUNTRIES.items():
        share = markets[name]
        if share <= MARKET_CAP:
            continue
        rules.append(RuleResult(
            "R3", False, "portfolio",
            f"about {_n(share)}% of the plan is in {name} shares, above {MARKET_CAP}% in one market",
            [h.fund_id for h in hs if f[h.fund_id]["equity_pct"] * f[h.fund_id][col] / 100 > MARKET_CAP],
            MARKET_CAP, share))
    top_name = max(markets, key=markets.get)
    if markets[top_name] <= MARKET_CAP:
        rules.append(RuleResult("R3", True, "portfolio",
                                f"the largest single market ({top_name}) is about {_n(markets[top_name])}% "
                                f"of the plan, within {MARKET_CAP}%", [], MARKET_CAP, markets[top_name]))

    # R4 structured claims vs fund data (description scope)
    not_checked: Dict[str, List[str]] = {h.fund_id: [] for h in hs}
    passes: Dict[str, List[str]] = {h.fund_id: [] for h in hs}
    for h in hs:
        for claim in h.claims:
            if claim in UNCHECKABLE_CLAIMS:
                not_checked[h.fund_id].append(claim)
                continue
            ok, ev = _check_claim(claim, f[h.fund_id])
            if ok:
                passes[h.fund_id].append(ev)
            else:
                rules.append(RuleResult("R4", False, "description", ev, [h.fund_id]))

    # R5 weighted risk. Flag funds whose own risk level is above the cap.
    rcap = RISK_CAP[profile.risk]
    over = risk > rcap
    rules.append(RuleResult(
        "R5", not over, "portfolio",
        f"the average risk level is {risk:.1f} of 7, above {rcap} for your profile" if over else
        f"the average risk level is {risk:.1f} of 7, within {rcap}",
        [h.fund_id for h in hs if f[h.fund_id]["risk_level"] > rcap] if over else [], rcap, risk))

    # Per-holding level
    results = {h.fund_id: HoldingResult(h.fund_id, h.weight_pct, passes=passes[h.fund_id],
                                        not_checked=not_checked[h.fund_id]) for h in hs}
    for r in rules:
        if r.passed:
            continue
        level = SCOPE_LEVEL[r.scope]
        for fid in r.fund_ids:
            hr = results[fid]
            hr.reasons.append(r)
            if LEVEL_ORDER[level] > LEVEL_ORDER[hr.level]:
                hr.level = level
    for h in hs:
        rl = f[h.fund_id]["risk_level"]
        if rl <= rcap:
            results[h.fund_id].passes.insert(0, f"risk level {rl} of 7 is within your profile's limit of {rcap}")

    metrics = {"equity_pct": equity, "avg_risk": risk}
    metrics.update({f"equity_in_{k.lower().replace(' ', '_')}": v for k, v in markets.items()})
    return CheckReport(rules=rules, holdings=results,
                       notice=H0_TEXT if profile.horizon_years < 5 else None, metrics=metrics)


@dataclass
class RequestResult:
    """R6: does the plan give the user what they explicitly asked for, and if not, does it say so?"""
    target: str
    requested_pct: int
    actual_pct: float
    quote: str
    status: str  # "followed" | "reduced_explained" | "reduced_unexplained"
    profile_cap: Optional[float]  # suitability cap that applies to this target, if any
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.status != "reduced_unexplained"


def check_request(profile: Profile, plan: Plan, funds: dict) -> Optional[RequestResult]:
    rf = plan.requested_focus
    if rf is None or not plan.holdings:
        return None
    f = {h.fund_id: funds[h.fund_id] for h in plan.holdings}
    if rf.target in COUNTRIES.values():  # a market: equity in that market, % of plan
        col = next(c for c, n in COUNTRIES.items() if n == rf.target)
        actual = sum(h.weight_pct * f[h.fund_id]["equity_pct"] / 100 * f[h.fund_id][col] / 100 for h in plan.holdings)
        cap = MARKET_CAP
    else:  # a thematic sector: weight of funds in that sector
        actual = sum(h.weight_pct for h in plan.holdings if f[h.fund_id]["sector"] == rf.target)
        cap = SECTOR_CAP[profile.risk]
    note = plan.adjustment_note.strip()
    if actual + 0.5 >= rf.min_pct:
        status = "followed"
    else:
        status = "reduced_explained" if note else "reduced_unexplained"
    return RequestResult(rf.target, rf.min_pct, actual, rf.quote, status, cap, note)


def with_removed(plan: Plan, removed: set) -> Plan:
    """The plan after the user removes holdings: removed weight is kept as cash (CASH_FUND), not reinvested."""
    kept = [h.model_copy() for h in plan.holdings if h.fund_id not in removed]
    freed = sum(h.weight_pct for h in plan.holdings if h.fund_id in removed)
    if freed:
        cash = next((h for h in kept if h.fund_id == CASH_FUND), None)
        if cash:
            cash.weight_pct += freed
        else:
            kept.append(plan.holdings[0].model_copy(update={
                "fund_id": CASH_FUND, "weight_pct": freed, "claims": [],
                "reason": "The share you removed, kept as cash (not invested)."}))
    return Plan(holdings=kept, summary=plan.summary)


def _check_claim(claim: str, fund: dict):
    rl, fee, name = fund["risk_level"], fund["ongoing_charge_pct"], fund["name"]
    if claim == "low_risk":
        ok = rl <= 3
        return ok, (f"described as low risk, and its risk level is {rl} of 7" if ok
                    else f"it is described as low risk, but its risk level is {rl} of 7")
    if claim == "low_cost":
        ok = fee <= LOW_COST_MAX
        return ok, (f"described as low cost, and its yearly charge is {fee:g}%" if ok
                    else f"it is described as low cost, but its yearly charge is {fee:g}% (above {LOW_COST_MAX}%)")
    if claim == "diversified":
        ok = fund["sector"] == "diversified" and fund["region"] == "Global"
        if ok:
            return ok, "described as diversified, and it spreads across sectors worldwide"
        if fund["sector"] != "diversified":
            return ok, f"it is described as diversified, but {name} focuses on one sector ({fund['sector']})"
        return ok, f"it is described as diversified, but it invests only in {fund['region']}"
    if claim == "income":
        ok = fund["asset_class"] in {"bond", "mixed", "cash"}
        return ok, (f"described as income, and it holds {fund['asset_class']}" if ok
                    else f"it is described as income, but it is an {fund['asset_class']} fund")
    raise ValueError(claim)


def _n(x: float) -> str:
    return str(int(round(x)))
