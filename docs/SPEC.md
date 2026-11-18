# Second Look — System Specification (v0.3, 2026-11-17)

Status labels used throughout: **[I]** implemented in A2 · **[S]** simulated · **[P]** planned.

## 0. One-line description

An investment-suggestion assistant for beginner private investors. An LLM proposes a portfolio from a fixed fund list; **deterministic code** checks each suggestion against the user's confirmed profile; the interface attaches a per-suggestion hedge ("look again" / "review" / "checked") with the evidence beside it. The user decides; the system never trades.

Design question (from A1): if hedges are tied to *detectable suitability problems* instead of the model's own voice, do users reject unsuitable suggestions more often than with a generic disclaimer?

## 1. Interaction flow (main path)

1. User fills the profile form → system displays its interpretation → user **confirms or edits**. [I]
2. User asks for a plan (optional free-text question). [I]
3. System assembles the prompt (instruction + confirmed profile + fund list) → LLM returns JSON. [I]
4. Validator checks shape and fund IDs → retry once → otherwise **decline turn**. [I]
5. Checker runs rules R1–R5 → per-holding level + evidence. [I]
6. UI renders hedge per holding, plus a profile-level notice when the horizon is under 5 years. [I]
   Comparison mode: the same plan with one generic disclaimer; checks run and are logged but hidden. [I]
7. User: **Why?** (show evidence) · **Remove** (removed share kept as cash; the remaining plan is checked again and shown) · **Keep anyway** · **Undo** · **Suggest again within my profile** (one re-prompt with failed rules). [I]
8. Every flag and user action is logged. [I]

## 2. Profile (input contract)

Collected by form, never inferred from chat.

| Field | Type | Allowed values |
|---|---|---|
| `goal` | enum | `house_deposit`, `retirement`, `general_growth`, `income` |
| `horizon_years` | int | 1–30 |
| `risk` | enum | `low`, `medium`, `high` |
| `amount_gbp` | int | 500–1,000,000 |

Confirmation text (grounding by display, L07): *"I understood: a {horizon}-year {goal} goal, {risk} risk, £{amount}. Is that right?"* → [Confirm] [Edit]

If chat text implies a different profile (e.g. "I need the money next year"), the LLM must **not** change the profile. It returns `profile_change_suggested`; the UI asks the user to confirm the change in the form (repair: *confirm*). The checker always uses the last **confirmed** profile.

## 3. LLM output contract (JSON schema)

```json
{
  "holdings": [
    {
      "fund_id": "F07",
      "weight_pct": 50,
      "claims": ["growth"],
      "reason": "Short plain-English reason, max 30 words"
    }
  ],
  "profile_change_suggested": null,
  "summary": "Max 40 words"
}
```

- `fund_id`: must exist in `data/funds.csv` (closed universe).
- `weight_pct`: integer 5–100; all weights sum to 100.
- `claims`: list from enum `low_risk`, `low_cost`, `diversified`, `income`, `growth`, `other`. **Claims are structured so code can check them** (see R4).
- `profile_change_suggested`: `null` or `{"field": "...", "value": "...", "quote": "user's words"}`.

Implemented as Pydantic models; passed to the provider as a JSON schema where supported.

## 4. Validator (V-rules) — shape, not truth (L09)

| ID | Check | On failure |
|---|---|---|
| V1 | Parses against schema | retry once with the error message |
| V2 | Every `fund_id` in fund list | retry once ("unknown fund F99") |
| V3 | Weights sum to 100 (±1) | retry once |
| V4 | 1–6 holdings | retry once |
| V5 | Each fund at most once | retry once |
| — | Still failing after retry | **Decline turn**: "I couldn't produce a plan I can check. Try again or change your question." |

## 5. Checker rules (suitability) — deterministic code

Definitions, with `w` = holding weight (%) and fund fields from `funds.csv`:

- Equity share `E = Σ w · equity_pct / 100`
- Equities in market m `M(m) = Σ w · equity_pct/100 · eq_m/100`, for m in US, UK, Europe, Emerging markets (`eq_*` in `funds.csv` = where the fund's equity part is invested)
- Sector share `S(x) = Σ w` over holdings whose `sector = x`, for thematic sectors only (excludes `diversified`, `government`, `cash`)
- Weighted risk `R = Σ w · risk_level / 100`

| ID | Rule | Threshold | Scope | Basis |
|---|---|---|---|---|
| R1 | Equity share within profile limit | see table below | portfolio → contributing holdings | Horizon bands from UK consumer guidance (invest only money not needed for ~5 years: MoneyHelper; HSBC); 20% steps follow common multi-asset ranges (e.g. Vanguard LifeStrategy 20–100%). Cell values: **ASSUMPTION** |
| R2 | No thematic sector above cap | low 20 · medium 30 · high 40 | holding | **ASSUMPTION** (declared design choice: a thematic fund should be a minor part of a beginner's plan; no regulatory sector limit applies) |
| R3 | Equities in any one market ≤ 60% of the plan | 60 | portfolio | Cap anchored on Winder et al. (2025) global ETF benchmark (~59% US). v0.2 checked the US only, so a plan 100% in UK shares passed every rule; v0.3 checks every market |
| R4 | Each structured claim matches fund data | see mapping | **description** | Fund data (provenance shown). A false claim means the model *described* the fund wrongly; it is not a verdict that the fund is unsuitable |
| R5 | Weighted risk ≤ profile max | low 3 · medium 5 · high 6 | portfolio → holdings with `risk_level` above max | 1–7 scale modelled on the UCITS SRRI volatility bands (3 ≈ ≤5% vol, 5 ≈ ≤15%, 7 = >25%). Cut-offs: **ASSUMPTION**. A weighted average ignores diversification, so it overstates portfolio risk: a deliberate cautious bias (a missed warning costs more than an extra one) |

R1 equity limit (%):

| Horizon | low | medium | high |
|---|---|---|---|
| < 5 years | 20 | 20 | 20 |
| 5–10 years | 40 | 60 | 80 |
| > 10 years | 60 | 80 | 100 |

### H0 — profile-level horizon notice [I]

If `horizon_years < 5`, show before any plan: *"Money needed within 5 years is usually kept in savings rather than invested. You can still see suggestions, but treat them with extra care."* This is a notice, not a block; the user decides (capability and scope made visible, Amershi G1–G2).

R4 claim mapping:

| Claim | Passes if | Otherwise |
|---|---|---|
| `low_risk` | `risk_level ≤ 3` | fail |
| `low_cost` | `ongoing_charge_pct ≤ 0.25` | fail |
| `diversified` | `sector = diversified` and `region = Global` | fail |
| `income` | `asset_class` in {bond, mixed, cash} | fail |
| `growth`, `other` | — | **not checked** (forecast; cannot be verified) |

### Per-holding level

- **look_again**: the fund on its own does not suit the profile (R2).
- **review**: (a) a portfolio rule failed (R1, R3, R5) and **this fund is itself over that limit** (its equity_pct > R1 limit; its own equity in the market > 60; its risk_level > R5 cap); or (b) the model's description of the fund is wrong (R4).
- **checked**: no failed rule touches it.

v0.2 flagged every fund that added *anything* to a failed portfolio rule (e.g. a 20/80 fund adding 4 points of shares), and gave false claims the same "Look again / not confident this suits you" wording as unsuitable funds. Live Groq runs showed a cash fund marked "Look again" for a low-risk profile only because the model called it "diversified". v0.3 separates the three meanings.
- Unverifiable claims are listed separately as **not checked** — never shown as passed.

### R6 — explicit request vs plan [I] (v0.4)

| Status | Condition | Shown |
|---|---|---|
| followed | actual share ≥ requested minimum | "The plan gives you what you asked for." |
| reduced_explained | actual < requested and `adjustment_note` is not empty | the note, labelled "(not checked)" |
| reduced_unexplained | actual < requested and no note | warning: "…the model did not say why." |

The model's reading of the request is an interpretation, so it is displayed back to the user ("I read this as at least 50% in technology"), as with the profile (grounding by display). If the request exceeds a suitability limit (R2 sector cap or R3 market cap), that limit is shown as a legitimate reason. R6 is plan-level: no per-holding badge, and it is not sent back on "Suggest again" (it would push the model against R2/R3).

## 6. Hedge rendering

First-person wording follows Kim et al. (2024). The wording is fixed by templates, **not generated by the LLM**, so the hedge always matches the checker result.

| Level | Badge | Template |
|---|---|---|
| look_again | Look again | "I'm not confident this suits you: {evidence}." |
| review (portfolio) | Review | "I'm unsure about this part of the plan: {evidence}." |
| review (description) | Review | "The model's description doesn't match the fund data: {evidence}." |
| checked | Checked | "{pass_evidence}." |
| not checked | — | "Not checked: {claims}. Nobody can verify forecasts." |

Comparison mode (**Disclaimer-only**) [I]: no badges, no H0, no Why; Remove available on every holding; one banner: "AI suggestions can be wrong. This is not financial advice." (mirrors the generic disclaimers Winder et al. found in ~95% of responses).

"Why?" panel: the fund's row from `funds.csv` (fields used, `source`, `as_of`) + the rule and threshold (shown, not just cited — L11).

## 7. Prompt specification (L09 six parts)

- **Task**: propose 1–6 holdings from the supplied fund list for the confirmed profile.
- **Audience**: beginner UK private investor; plain English.
- **Constraints**: only fund IDs from the list; integer weights summing to 100; never change the profile — use `profile_change_suggested`; no return forecasts as facts; if the question is outside portfolio suggestion, return an empty `holdings` list and say so in `summary` (decline).
- **Examples**: one valid output (kept short; L09 warns examples get copied).
- **Claim definitions** (v2): low_risk = risk_level ≤ 3; low_cost = charge ≤ 0.25%; diversified = the fund itself holds many sectors across many countries (not "adds diversification to the plan"); income = bonds, cash or a mix. Added after live runs showed the model and checker using "diversified" differently. v1 (no definitions) is kept for comparison (`PROMPT_VERSION`).
- **Success criteria** (checked by code/tests, reused for evaluation):
  1. Output passes V1–V4.
  2. No fund outside the list.
  3. Profile fields unchanged unless proposed via `profile_change_suggested`.
  4. `reason` ≤ 30 words, `summary` ≤ 40 words.
- **Output format**: JSON schema in §3.

Instruction text is versioned in `app/prompt.py`; profile and fund list are assembled per call (instruction vs information, L09).

## 8. Re-prompt ("Suggest again within my profile")

One extra call with the failed rules and their evidence appended as information. Result goes through V-rules and checker again. Max one re-prompt per request; the new plan is shown with its own flags (the system does not claim it is now "safe").

## 9. Seeded errors and replay [S]

- `replays/scenario_*.json`: stored profile, question, LLM output, expected checker result. `LLM_PROVIDER=replay` reads these — **no API key needed**, deterministic.
- Seeded-error cases: hand-written bad outputs with known faults (sector concentration, wrong `low_risk` claim, unknown fund, weights ≠ 100). `tests/` asserts the expected flags fire → evidence that hedges track real, known problems.

Scenarios for storyboards:
1. **Suitable plan, few flags** — medium risk, 10 years.
2. **Concentrated plan, strong flags** — house deposit, low risk, 3 years; H0 notice shown; F07 50 / F02 35 / F15 15 → R1 (85 > 20), R2 (tech 50 > 20), R3 (US 71 > 60), R5 (5.05 > 3) fail; F07 look_again, F02 review, F15 checked.
3. **Misread profile → repair** — chat implies a shorter horizon; system asks to confirm; plan regenerates.

## 10. Logging [I]

`logs/session_*.jsonl`: timestamp, mode (checks | disclaimer), prompt version, model, raw model output, profile, holdings, per-holding level, user action (why/remove/keep/regenerate/accept). No personal data beyond the form fields.

## 11. Boundaries (state these in the report)

- The checker catches **suitability** problems against the confirmed profile; it cannot judge forecasts or future returns.
- Thresholds marked ASSUMPTION are design choices, not regulatory rules.
- Fund data is fictional [S]; live data [P].
- No user study in A2 [P]; logging and the disclaimer mode prepare it.
- R2 has no look-through: technology inside a global fund is not counted [simplification].
- R5 largely overlaps R1 with this fund list (risk mostly comes from shares); kept because it would catch high-risk bond funds.
- Considered and dropped: a "one fund too large" rule. After R3 covers single markets, one global index fund at 100% is reasonable and a single-market fund at 100% is already caught.
- Not financial advice; the system never executes trades.

## 11b. Batch evaluation [I]

`scripts/batch_eval.py --provider groq --runs N --prompts v1 v2` runs 5 fixed profiles × N runs × prompt versions through the same pipeline and writes `eval/batch_*.csv` (status, validator retries, failed rules, false claims, levels). `--summarise` prints counts per prompt version. Purpose: how often a live model's plan breaks the checks, and whether claim definitions (v2) reduce false claims. Small N; descriptive only.

## 12. Sources for thresholds

- MoneyHelper, *Should I save or invest my money?* — consider investing only money not needed in the next five years.
- HSBC UK, *Saving vs investing* — for short-term needs such as a home deposit, saving makes sense; under 5 years gives less chance to recover a fall.
- Vanguard UK, LifeStrategy range — 20/40/60/80/100% equity mixes.
- UCITS KIID SRRI — 1–7 scale based on volatility bands (CESR, 2010).
- Winder, Hildebrand & Hartmann (2025) — global ETF benchmark ~59% US equities.

## Changelog

- v0.4 (2026-11-17): R6 compares an explicit user request with the plan. The model states the request it read (`requested_focus`: target, minimum %, the user's words) and any reduction (`adjustment_note`); code computes the plan's actual share and shows both, plus the profile limit if the request exceeds it. Flags a reduction the model did not explain. Prompt v4; replay scenario_4 (scripted). Trigger: a live run answered "most of my money into AI" with 20% tech and a confident summary.
- v0.3.3 (2026-11-17): prompt v3 states what counts as a profile change (a live run turned "I'm excited about AI" into a risk-level change and returned no plan). Batch evaluation adds a theme-driven question and compares v1 with v3.
- v0.3.2 (2026-11-17): Ollama (local models) removed: replay already gives reviewers a no-key option, and an untested provider adds nothing to the evaluation.
- v0.3.1 (2026-11-17): V5 rejects duplicate funds (would break the UI); a model-proposed profile change is validated before the user can apply it (odd values such as "next year" crashed the app); UI flows added to pytest.
- v0.3 (2026-11-17): after live Groq runs and a rule review. R3 generalised from US-only to any single market (adds `eq_*` columns to the fictional fund file). R4 becomes a *description* finding (Review, own wording) instead of Look again. Review attached only to funds that are themselves over a limit. Prompt v2 defines claims. Disclaimer-only mode, Remove → re-check (removed share kept as cash) and Undo implemented. Batch evaluation script added. "One fund too large" rule considered and dropped.

- v0.2 (2026-11-16): R1 horizon bands 3/7 → 5/10 years after checking UK consumer guidance; added H0 horizon notice; R2 caps 30/40/50 → 20/30/40; R5 high cap 7 → 6; Disclaimer-only mode moved to planned (deadline).
- v0.1 (2026-11-16): first draft.
