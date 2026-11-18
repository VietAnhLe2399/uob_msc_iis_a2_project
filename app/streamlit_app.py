"""Second Look — Streamlit UI (SPEC §1, §6). Run: streamlit run app/streamlit_app.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app.checker import check_plan, with_removed  # noqa: E402
from app.funds import load_funds  # noqa: E402
from app.hedge import hedge_text, not_checked_text  # noqa: E402
from app.llm_client import default_model, list_models, make_client, selectable_models  # noqa: E402
from app.logger import SessionLog  # noqa: E402
from app.models import GOAL_LABELS, Profile, apply_profile_change  # noqa: E402
from app.pipeline import DECLINE_TEXT, Result, run  # noqa: E402

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Second Look", layout="centered")
FUNDS = load_funds()
SCENARIOS = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / "replays").glob("*.json"))}
BADGE_MD = {"look_again": ":red-background[Look again]", "review": ":orange-background[Review]",
            "checked": ":green-background[Checked]"}
MODES = {"checks": "Checks on each suggestion", "disclaimer": "Generic disclaimer only"}
DISCLAIMER = "AI suggestions can be wrong. This is not financial advice."
ss = st.session_state


# ---------------- state ----------------
def reset():
    keep = {k: ss.get(k) for k in ("provider", "scenario", "mode", "model")}
    ss.clear()
    ss.update(keep)
    ss.stage = "form"
    ss.log = SessionLog()
    ss.log.mode = ss.mode


if "stage" not in ss:
    ss.provider = os.getenv("LLM_PROVIDER", "replay")
    ss.scenario = "scenario_2" if "scenario_2" in SCENARIOS else next(iter(SCENARIOS))
    ss.mode = "checks"
    reset()


def checks_on() -> bool:
    return ss.mode == "checks"


def client():
    if "client" not in ss:
        ss.client = make_client(ss.provider, ss.scenario, ss.get("model") or None)
    return ss.client


@st.cache_data(ttl=3600, show_spinner=False)
def available_models(provider: str):
    """Live model list from the provider (cached for an hour). Returns (models, error)."""
    try:
        return list_models(provider), None
    except Exception as exc:  # no key, no package, no network
        return [], f"{exc.__class__.__name__}: {exc}"


def scenario_defaults():
    if ss.provider == "replay":
        s = SCENARIOS[ss.scenario]
        return s["profile"], s["question"]
    return {"goal": "general_growth", "horizon_years": 10, "risk": "medium", "amount_gbp": 10000}, ""


def ask_model(failed_rules=None, keep_profile=False):
    try:
        c = client()
    except Exception as exc:  # missing package or API key: report, don't crash
        res = Result(status="system_declined",
                     errors=[f"Couldn't start the '{ss.provider}' model client ({exc.__class__.__name__}: {exc}). "
                             "Check your .env file and installed packages, or switch to 'replay'."])
    else:
        res = run(ss.profile, ss.question, c, FUNDS, failed_rules, keep_profile=keep_profile)
    ss.result, ss.removed, ss.kept, ss.why = res, set(), set(), set()
    ss.log.write("model_result", provider=ss.provider, status=res.status, prompt_version=res.prompt_version,
                 model=getattr(ss.get("client"), "model", ss.provider),
                 profile=ss.profile.model_dump(), question=ss.question,
                 holdings=[h.model_dump() for h in res.plan.holdings] if res.plan else [],
                 levels={k: v.level for k, v in res.report.holdings.items()} if res.report else {},
                 failed_rules=[r.rule for r in res.report.failed_rules] if res.report else [],
                 request=None if res.request is None else {"target": res.request.target,
                                                           "requested_pct": res.request.requested_pct,
                                                           "actual_pct": round(res.request.actual_pct, 1),
                                                           "status": res.request.status},
                 errors=res.errors, regenerate=bool(failed_rules), keep_profile=keep_profile,
                 raw_outputs=res.raw_outputs,
                 summary=res.plan.summary if res.plan else "",
                 profile_change=res.plan.profile_change_suggested.model_dump()
                 if res.plan and res.plan.profile_change_suggested else None)
    ss.stage = "result"


# ---------------- sidebar ----------------
with st.sidebar:
    st.subheader("Settings")
    providers = ["replay", "gemini", "groq"]
    chosen = st.selectbox("Model provider", providers, index=providers.index(ss.provider),
                          help="replay uses stored model outputs: no API key needed.")
    if chosen != ss.provider:
        ss.provider, ss.model = chosen, None
        reset()
        st.rerun()
    if ss.provider != "replay":
        live, err = available_models(ss.provider)
        models = selectable_models(ss.provider, live if live else None)  # live list unknown -> verified list
        fallback = default_model(ss.provider)
        if not models:
            ss.model = fallback or None
            st.caption(f"No verified {ss.provider} model is available right now. "
                       f"Using `{fallback or 'the default'}` from .env.")
        else:
            current = ss.get("model") if ss.get("model") in models else (fallback if fallback in models else models[0])
            picked = st.selectbox("Model", models, index=models.index(current),
                                  help="Models that produced a valid plan in this app "
                                       "(data/working_models.json) and that the provider still serves.")
            if picked != ss.get("model"):
                first_pick = ss.get("model") is None
                ss.model = picked
                if not first_pick:  # a different model starts a new session, so logs don't mix models
                    reset()
                    st.rerun()
                ss.pop("client", None)
    if ss.provider == "replay":
        sc = st.selectbox("Replay scenario", list(SCENARIOS), index=list(SCENARIOS).index(ss.scenario),
                          format_func=lambda k: f"{k}: {SCENARIOS[k]['title']}")
        if sc != ss.scenario:
            ss.scenario = sc
            reset()
            st.rerun()
    mode = st.radio("What the user sees", list(MODES), index=list(MODES).index(ss.mode),
                    format_func=MODES.get,
                    help="Comparison condition: the same plan with per-suggestion checks, "
                         "or with one generic disclaimer (checks still run and are logged, but are hidden).")
    if mode != ss.mode:
        ss.mode = mode
        reset()
        st.rerun()
    if st.button("Start over"):
        reset()
        st.rerun()
    st.divider()
    if checks_on():
        st.markdown("**What the badges mean**")
        st.markdown(f"{BADGE_MD['look_again']} this fund on its own doesn't suit your profile")
        st.markdown(f"{BADGE_MD['review']} it pushes the whole plan over a limit, or the model described it wrongly")
        st.markdown(f"{BADGE_MD['checked']} no check found a problem")
        st.caption("Checks cover suitability for your profile (share of stocks, one sector, one market, "
                   "average risk) and whether the model's claims match the fund data. They cannot check "
                   "forecasts. Fund data is fictional test data for this prototype.")
    else:
        st.caption("Disclaimer mode: checks run in the background for comparison but are not shown.")

# ---------------- header ----------------
st.title("Second Look")
st.caption("Investment suggestions from a language model, checked against your profile by rules you can "
           "inspect. Not financial advice. Nothing is bought or sold." if checks_on() else
           "Investment suggestions from a language model. Nothing is bought or sold.")

# ---------------- stage: form ----------------
if ss.stage == "form":
    d, q = scenario_defaults()
    base = ss.get("draft").model_dump() if ss.get("draft") else d
    with st.form("profile"):
        st.subheader("Your profile")
        goals = list(GOAL_LABELS)
        goal = st.selectbox("Goal", goals, index=goals.index(base["goal"]), format_func=GOAL_LABELS.get)
        horizon = st.number_input("When will you need the money? (years from now)", 1, 30, base["horizon_years"])
        risk = st.radio("How much ups and downs can you accept?", ["low", "medium", "high"],
                        index=["low", "medium", "high"].index(base["risk"]), horizontal=True)
        amount = st.number_input("Amount to invest (£)", 500, 1_000_000, base["amount_gbp"], step=500)
        if st.form_submit_button("Continue"):
            ss.draft = Profile(goal=goal, horizon_years=int(horizon), risk=risk, amount_gbp=int(amount))
            ss.question = ss.get("question") or q
            ss.stage = "confirm"
            st.rerun()

# ---------------- stage: confirm (grounding by display) ----------------
elif ss.stage == "confirm":
    st.info(f"I understood: {ss.draft.describe()}. Is that right?")
    c1, c2 = st.columns(2)
    if c1.button("Confirm", type="primary"):
        ss.profile = ss.draft
        ss.log.write("profile_confirmed", profile=ss.profile.model_dump())
        ss.stage = "ask"
        if ss.get("rerun_after_confirm"):
            ss.rerun_after_confirm = False
            ask_model()
        st.rerun()
    if c2.button("Edit"):
        ss.stage = "form"
        st.rerun()

# ---------------- shared: profile line + H0 ----------------
if ss.stage in ("ask", "result"):
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"**Profile:** {ss.profile.describe()}")
    if c2.button("Edit profile"):
        ss.draft, ss.stage = ss.profile, "form"
        st.rerun()
    if checks_on() and ss.profile.horizon_years < 5:
        st.warning("Money needed within 5 years is usually kept in savings rather than invested. "
                   "You can still see suggestions, but treat them with extra care.")

# ---------------- stage: ask ----------------
if ss.stage == "ask":
    ss.question = st.text_area("Your question", ss.get("question", ""),
                               placeholder="How should I invest this money?")
    if st.button("Get suggestions", type="primary"):
        with st.spinner("Asking the model, then checking its answer…" if checks_on() else "Asking the model…"):
            ask_model()
        st.rerun()


# ---------------- stage: result ----------------
def why_panel(fid, hr):
    fund = FUNDS[fid]
    st.markdown("**Fund data used by the checks**")
    st.table({k: [f"{fund[k]:g}" if isinstance(fund[k], float) else str(fund[k])]
              for k in ["asset_class", "region", "sector", "equity_pct", "eq_us", "eq_uk",
                        "risk_level", "ongoing_charge_pct"]})
    st.caption(f"Source: {fund['source']}, as of {fund['as_of']}")
    for r in hr.reasons:
        limit = f" Limit: {r.threshold:g}%." if r.threshold is not None and r.rule != "R5" else (
            f" Limit: {r.threshold:g}." if r.threshold is not None else "")
        st.markdown(f"- **{r.rule}** failed: {r.evidence}.{limit}")
    for p in hr.passes:
        st.markdown(f"- passed: {p}")
    for c in hr.not_checked:
        st.markdown(f"- not checked: '{c}' is the model's own view and cannot be verified")


def card(h, hr, fund):
    removed, kept = h.fund_id in ss.removed, h.fund_id in ss.kept
    with st.container(border=True):
        title = f"~~{fund['name']}~~" if removed else fund["name"]
        badge = BADGE_MD[hr.level] + " " if checks_on() else ""
        st.markdown(f"{badge}**{title}** · {h.weight_pct}%")
        if checks_on():
            st.write(hedge_text(hr))
        st.caption(f"Model's reason: {h.reason}")
        flagged = hr.level != "checked" or hr.not_checked
        cols = st.columns([1, 1, 1.4, 2])
        if checks_on() and flagged and cols[0].button("Why?", key=f"why_{h.fund_id}"):
            ss.why ^= {h.fund_id}
            ss.log.write("why", fund_id=h.fund_id, level=hr.level)
            st.rerun()
        if removed or kept:
            st.caption("Removed by you. Its share is kept as cash." if removed else "Kept by you.")
            if cols[1].button("Undo", key=f"undo_{h.fund_id}"):
                ss.removed.discard(h.fund_id)
                ss.kept.discard(h.fund_id)
                ss.log.write("undo", fund_id=h.fund_id, level=hr.level)
                st.rerun()
        elif hr.level != "checked" or not checks_on():  # a Checked card only offers Why? (for unverifiable claims)
            if cols[1].button("Remove", key=f"rm_{h.fund_id}"):
                ss.removed.add(h.fund_id)
                ss.log.write("remove", fund_id=h.fund_id, level=hr.level)
                st.rerun()
            if checks_on() and cols[2].button("Keep anyway", key=f"keep_{h.fund_id}"):
                ss.kept.add(h.fund_id)
                ss.log.write("keep", fund_id=h.fund_id, level=hr.level)
                st.rerun()
        if checks_on() and h.fund_id in ss.why:
            why_panel(h.fund_id, hr)


def request_panel(rr):
    """R6: compare what the user explicitly asked for with what the plan gives (code computes the share)."""
    with st.container(border=True):
        st.markdown("**Your request**")
        st.markdown(f"You wrote: “{rr.quote}”. I read this as **at least {rr.requested_pct}% in {rr.target}**. "
                    "If that's not what you meant, change your question.")
        st.markdown(f"This plan puts **{rr.actual_pct:.0f}%** in {rr.target}.")
        kind = "one sector" if rr.target in ("technology", "healthcare", "energy") else "one market"
        over_cap = rr.profile_cap is not None and rr.actual_pct > rr.profile_cap
        if rr.status == "followed":
            if over_cap:  # following the request is not the same as suiting the profile: no green here
                st.warning(f"The plan gives you what you asked for, but {rr.actual_pct:.0f}% in {rr.target} is "
                           f"above the {rr.profile_cap:g}% your profile allows in {kind}. See the flags below.")
            else:
                st.success("The plan gives you what you asked for.")
        else:
            if rr.profile_cap is not None and rr.requested_pct > rr.profile_cap:
                st.caption(f"Your profile allows up to {rr.profile_cap:g}% in {kind}, so the checks would flag "
                           f"{rr.requested_pct}%.")
            if rr.status == "reduced_explained":
                st.info(f"The plan gives you less than you asked for. Model's explanation (not checked): {rr.note}")
            else:
                st.warning("The plan gives you less than you asked for, and the model did not say why.")


def after_changes_panel(res):
    """Visible consequence of removals: the remaining plan is checked again (removed share kept as cash)."""
    edited = with_removed(res.plan, ss.removed)
    rep = check_plan(ss.profile, edited, FUNDS)
    with st.container(border=True):
        st.markdown("**Your plan after your changes** (removed share kept as cash)")
        st.write(", ".join(f"{FUNDS[h.fund_id]['name']} {h.weight_pct}%" for h in edited.holdings))
        port = [r for r in rep.rules if r.scope == "portfolio"]
        for r in port:
            st.markdown(f"{'✓' if r.passed else '✗'} {r.evidence}")
        if not rep.failed_rules:
            st.success("No check finds a problem with the plan after your changes.")
    return rep


if ss.stage == "result":
    res = ss.result
    st.markdown(f"**Your question:** {ss.question}")

    if res.status == "profile_change":
        ch = res.plan.profile_change_suggested
        st.warning(f"{res.plan.summary}\n\nYou wrote: “{ch.quote}”")
        proposed = apply_profile_change(ss.profile, ch)
        c1, c2 = st.columns(2)
        if proposed is None:
            c1.caption(f"I couldn't turn “{ch.value}” into a {ch.field.replace('_', ' ')} value. "
                       "Use Edit profile to set it yourself.")
        elif c1.button(f"Update {ch.field.replace('_', ' ')} to {ch.value}", type="primary"):
            ss.draft = proposed
            ss.log.write("profile_change_accepted", field=ch.field, value=ch.value)
            ss.rerun_after_confirm, ss.stage = True, "confirm"
            st.rerun()
        if c2.button("Keep my current profile"):
            ss.log.write("profile_change_rejected", field=ch.field, value=ch.value)
            with st.spinner("Building a plan for your current profile…"):
                ask_model(keep_profile=True)  # the user's choice is passed to the model and enforced in code
            st.rerun()

    elif res.status == "model_declined":
        st.info(res.plan.summary or "This question is outside what I can help with.")
        if st.button("Ask something else"):
            ss.stage = "ask"
            st.rerun()

    elif res.status == "system_declined":
        st.error(DECLINE_TEXT)
        with st.expander("What went wrong"):
            for e in res.errors:
                st.write(e if len(e) <= 400 else e[:400] + " …")
        if st.button("Try again"):
            ss.stage = "ask"
            st.rerun()

    else:
        rep = res.report
        if not checks_on():
            st.info(DISCLAIMER)
        if res.plan.summary:
            label = "**Model's summary** (not checked)" if checks_on() else "**Model's summary**"
            st.markdown(f"{label}: {res.plan.summary}")
        if checks_on() and res.request is not None:
            request_panel(res.request)
        for h in res.plan.holdings:
            card(h, rep.holdings[h.fund_id], FUNDS[h.fund_id])

        if checks_on():
            unchecked = [c for hr in rep.holdings.values() for c in hr.not_checked]
            if unchecked:
                st.caption(not_checked_text(unchecked))
            if ss.removed:
                after_changes_panel(res)

        c1, c2 = st.columns(2)
        if checks_on() and rep.failed_rules:
            if not ss.get("regenerated"):
                if c1.button("Suggest again within my profile"):
                    ss.regenerated = True
                    ss.log.write("regenerate", failed_rules=[r.rule for r in rep.failed_rules])
                    with st.spinner("Asking for a new plan, then checking it again…"):
                        ask_model(failed_rules=rep.failed_rules)
                    st.rerun()
            else:
                c1.caption("You've already asked for a new plan once. Edit your profile or question to try again.")
        if c2.button("Accept plan", type="primary"):
            final = with_removed(res.plan, ss.removed)
            final_rep = check_plan(ss.profile, final, FUNDS)
            ss.log.write("accept", kept=[h.fund_id for h in res.plan.holdings if h.fund_id not in ss.removed],
                         removed=sorted(ss.removed), kept_anyway=sorted(ss.kept),
                         final_failed_rules=[r.rule for r in final_rep.failed_rules])
            st.success("Plan accepted for this demo. Nothing has been bought. "
                       f"Decisions saved to {ss.log.path.name}.")

        with st.expander("Technical trace (for inspection)"):
            model = getattr(ss.get("client"), "model", None)
            st.markdown(f"Provider: `{ss.provider}`" + (f" · model: `{model}`" if model else "")
                        + f" · prompt: `{res.prompt_version}` · attempts: {len(res.raw_outputs)}"
                        + f" · display: `{ss.mode}`")
            if ss.provider == "replay" and "recorded_from" in SCENARIOS.get(ss.scenario, {}):
                rf = SCENARIOS[ss.scenario]["recorded_from"]
                st.caption(f"Replay of a live run: {rf['provider']} / {rf['model']} at {rf['ts']}, "
                           f"prompt {rf.get('prompt_version', 'v1')} (the prompt label above is not used in replay)")
            if not checks_on():
                st.caption("Checks below ran but were hidden from the user in this mode.")
            st.json({k: round(v, 1) for k, v in rep.metrics.items()})
            st.table([{"rule": r.rule, "passed": r.passed, "scope": r.scope,
                       "value": "" if r.value is None else f"{r.value:.1f}",
                       "limit": "" if r.threshold is None else f"{r.threshold:g}",
                       "evidence": r.evidence} for r in rep.rules])
            st.markdown("Raw model output (last attempt)")
            st.code(json.dumps(json.loads(res.raw_outputs[-1]), indent=2), language="json")
