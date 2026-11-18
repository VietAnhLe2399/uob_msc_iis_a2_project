"""Second Look — Streamlit UI (SPEC §1, §6). Run: streamlit run app/streamlit_app.py"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app.funds import load_funds  # noqa: E402
from app.hedge import BADGE, hedge_text, not_checked_text  # noqa: E402
from app.llm_client import make_client  # noqa: E402
from app.logger import SessionLog  # noqa: E402
from app.models import GOAL_LABELS, Profile  # noqa: E402
from app.pipeline import DECLINE_TEXT, Result, run  # noqa: E402

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Second Look", page_icon=None, layout="centered")
FUNDS = load_funds()
SCENARIOS = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / "replays").glob("scenario_*.json"))}
BADGE_MD = {"look_again": ":red-background[Look again]", "review": ":orange-background[Review]",
            "checked": ":green-background[Checked]"}
ss = st.session_state


# ---------------- state ----------------
def reset(keep_provider=True):
    provider, scenario = ss.get("provider"), ss.get("scenario")
    ss.clear()
    if keep_provider:
        ss.provider, ss.scenario = provider, scenario
    ss.stage = "form"
    ss.log = SessionLog()


if "stage" not in ss:
    ss.provider = os.getenv("LLM_PROVIDER", "replay")
    ss.scenario = "scenario_2"
    reset()


def client():
    if "client" not in ss:
        ss.client = make_client(ss.provider, ss.scenario)
    return ss.client


def scenario_defaults():
    if ss.provider == "replay":
        s = SCENARIOS[ss.scenario]
        return s["profile"], s["question"]
    return {"goal": "general_growth", "horizon_years": 10, "risk": "medium", "amount_gbp": 10000}, ""


def ask_model(failed_rules=None):
    try:
        c = client()
    except Exception as exc:  # missing package or API key: report, don't crash
        res = Result(status="system_declined",
                     errors=[f"Couldn't start the '{ss.provider}' model client ({exc.__class__.__name__}: {exc}). "
                             "Check your .env file and installed packages, or switch to 'replay'."])
    else:
        res = run(ss.profile, ss.question, c, FUNDS, failed_rules)
    ss.result, ss.removed, ss.kept, ss.why = res, set(), set(), set()
    ss.log.write("model_result", provider=ss.provider, status=res.status,
                 profile=ss.profile.model_dump(), question=ss.question,
                 holdings=[h.model_dump() for h in res.plan.holdings] if res.plan else [],
                 levels={k: v.level for k, v in res.report.holdings.items()} if res.report else {},
                 failed_rules=[r.rule for r in res.report.failed_rules] if res.report else [],
                 errors=res.errors, regenerate=bool(failed_rules))
    ss.stage = "result"


# ---------------- sidebar ----------------
with st.sidebar:
    st.subheader("Settings")
    providers = ["replay", "gemini", "groq", "ollama"]
    chosen = st.selectbox("Model provider", providers, index=providers.index(ss.provider),
                          help="replay uses stored model outputs: no API key needed.")
    if chosen != ss.provider:
        ss.provider = chosen
        reset()
        st.rerun()
    if ss.provider == "replay":
        sc = st.selectbox("Replay scenario", list(SCENARIOS), index=list(SCENARIOS).index(ss.scenario),
                          format_func=lambda k: f"{k[-1]}. {SCENARIOS[k]['title']}")
        if sc != ss.scenario:
            ss.scenario = sc
            reset()
            st.rerun()
    if st.button("Start over"):
        reset()
        st.rerun()
    st.divider()
    st.markdown("**What the badges mean**")
    st.markdown(f"{BADGE_MD['look_again']} this suggestion breaks a check on its own")
    st.markdown(f"{BADGE_MD['review']} it adds to a problem in the whole plan")
    st.markdown(f"{BADGE_MD['checked']} no check found a problem")
    st.caption("Checks cover suitability for your profile (share of stocks, one sector, US share, "
               "average risk, and claims about funds). They cannot check forecasts. "
               "Fund data is fictional for this prototype.")

# ---------------- header ----------------
st.title("Second Look")
st.caption("Investment suggestions from a language model, checked against your profile by rules you can "
           "inspect. Not financial advice. Nothing is bought or sold.")

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
def profile_bar():
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"**Profile:** {ss.profile.describe()}")
    if c2.button("Edit profile"):
        ss.draft, ss.stage = ss.profile, "form"
        st.rerun()


if ss.stage in ("ask", "result"):
    profile_bar()
    if ss.profile.horizon_years < 5:
        st.warning("Money needed within 5 years is usually kept in savings rather than invested. "
                   "You can still see suggestions, but treat them with extra care.")

# ---------------- stage: ask ----------------
if ss.stage == "ask":
    ss.question = st.text_area("Your question", ss.get("question", ""),
                               placeholder="How should I invest this money?")
    if st.button("Get suggestions", type="primary"):
        with st.spinner("Asking the model, then checking its answer…"):
            ask_model()
        st.rerun()


# ---------------- stage: result ----------------
def why_panel(fid, hr):
    fund = FUNDS[fid]
    st.markdown("**Fund data used by the checks**")
    st.table({k: [str(fund[k])] for k in ["asset_class", "region", "sector", "equity_pct", "us_pct",
                                         "risk_level", "ongoing_charge_pct"]})
    st.caption(f"Source: {fund['source']}, as of {fund['as_of']}")
    for r in hr.reasons:
        limit = f" Limit: {r.threshold:g}." if r.threshold is not None else ""
        st.markdown(f"- **{r.rule}** failed: {r.evidence}.{limit}")
    for p in hr.passes:
        st.markdown(f"- passed: {p}")
    for c in hr.not_checked:
        st.markdown(f"- not checked: '{c}' is a forecast and cannot be verified")


if ss.stage == "result":
    res = ss.result
    st.markdown(f"**Your question:** {ss.question}")

    if res.status == "profile_change":
        ch = res.plan.profile_change_suggested
        st.warning(f"{res.plan.summary}\n\nYou wrote: “{ch.quote}”")
        c1, c2 = st.columns(2)
        if c1.button(f"Update {ch.field.replace('_', ' ')} to {ch.value}", type="primary"):
            ss.draft = ss.profile.model_copy(update={ch.field: int(ch.value) if ch.field in
                                                     ("horizon_years", "amount_gbp") else ch.value})
            ss.log.write("profile_change_accepted", field=ch.field, value=ch.value)
            ss.rerun_after_confirm, ss.stage = True, "confirm"
            st.rerun()
        if c2.button("Keep my current profile"):
            ss.log.write("profile_change_rejected", field=ch.field, value=ch.value)
            ss.stage = "ask"
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
                st.write(e)
        if st.button("Try again"):
            ss.stage = "ask"
            st.rerun()

    else:
        rep = res.report
        if res.plan.summary:
            st.markdown(f"**Model's summary:** {res.plan.summary}")
        for h in res.plan.holdings:
            hr, fund = rep.holdings[h.fund_id], FUNDS[h.fund_id]
            with st.container(border=True):
                removed = h.fund_id in ss.removed
                title = f"~~{fund['name']}~~" if removed else fund["name"]
                st.markdown(f"{BADGE_MD[hr.level]} **{title}** · {h.weight_pct}%")
                st.write(hedge_text(hr))
                st.caption(f"Model's reason: {h.reason}")
                if removed:
                    st.caption("Removed by you.")
                elif h.fund_id in ss.kept:
                    st.caption("Kept by you.")
                if hr.level != "checked" or hr.not_checked:
                    b1, b2, b3, _ = st.columns([1, 1, 1.4, 2])
                    if b1.button("Why?", key=f"why_{h.fund_id}"):
                        ss.why ^= {h.fund_id}
                        ss.log.write("why", fund_id=h.fund_id, level=hr.level)
                        st.rerun()
                    if not removed and b2.button("Remove", key=f"rm_{h.fund_id}"):
                        ss.removed.add(h.fund_id)
                        ss.kept.discard(h.fund_id)
                        ss.log.write("remove", fund_id=h.fund_id, level=hr.level)
                        st.rerun()
                    if not removed and h.fund_id not in ss.kept and b3.button("Keep anyway", key=f"keep_{h.fund_id}"):
                        ss.kept.add(h.fund_id)
                        ss.log.write("keep", fund_id=h.fund_id, level=hr.level)
                        st.rerun()
                if h.fund_id in ss.why:
                    why_panel(h.fund_id, hr)

        unchecked = [c for hr in rep.holdings.values() for c in hr.not_checked]
        if unchecked:
            st.caption(not_checked_text(unchecked))

        c1, c2 = st.columns(2)
        if rep.failed_rules and not ss.get("regenerated"):
            if c1.button("Suggest again within my profile"):
                ss.regenerated = True
                ss.log.write("regenerate", failed_rules=[r.rule for r in rep.failed_rules])
                with st.spinner("Asking for a new plan, then checking it again…"):
                    ask_model(failed_rules=rep.failed_rules)
                st.rerun()
        elif rep.failed_rules:
            c1.caption("You've already asked for a new plan once. Edit your profile or question to try again.")
        if c2.button("Accept plan", type="primary"):
            kept = [h.fund_id for h in res.plan.holdings if h.fund_id not in ss.removed]
            ss.log.write("accept", kept=kept, removed=sorted(ss.removed))
            st.success("Plan accepted for this demo. Nothing has been bought. "
                       f"Decisions saved to {ss.log.path.name}.")

        with st.expander("Technical trace (for inspection)"):
            st.markdown(f"Provider: `{ss.provider}` · attempts: {len(res.raw_outputs)}")
            st.json({k: round(v, 2) for k, v in rep.metrics.items()})
            st.table([{"rule": r.rule, "passed": r.passed, "scope": r.scope,
                       "value": None if r.value is None else round(r.value, 2),
                       "limit": r.threshold, "evidence": r.evidence} for r in rep.rules])
            st.code(res.raw_outputs[-1], language="json")
