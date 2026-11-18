# Second Look — System Specification (v0.2, 2026-11-16)

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
   (Comparison mode with a single generic disclaimer: [P].)
7. User: **Why?** (show evidence) · **Remove** · **Keep anyway** · **Suggest again within my profile** (one re-prompt with failed rules). [I]
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
| — | Still failing after retry | **Decline turn**: "I couldn't produce a plan I can check. Try again or change your question." |

## 5. Checker rules (suitability) — deterministic code

Definitions, with `w` = holding weight (%) and fund fields from `funds.csv`:

- Equity share `E = Σ w · equity_pct / 100`
- US share `U = Σ w · us_pct / 100`
- Sector share `S(x) = Σ w` over holdings whose `sector = x`, for thematic sectors only (excludes `diversified`, `government`, `cash`)
- Weighted risk `R = Σ w · risk_level / 100`

| ID | Rule | Threshold | Scope | Basis |
|---|---|---|---|---|
| R1 | Equity share within profile limit | see table below | portfolio → contributing holdings | Horizon bands from UK consumer guidance (invest only money not needed for ~5 years: MoneyHelper; HSBC); 20% steps follow common multi-asset ranges (e.g. Vanguard LifeStrategy 20–100%). Cell values: **ASSUMPTION** |
| R2 | No thematic sector above cap | low 20 · medium 30 · high 40 | holding | **ASSUMPTION** (declared design choice: a thematic fund should be a minor part of a beginner's plan; no regulatory sector limit applies) |
| R3 | US share ≤ 60% | 60 | portfolio → contributing holdings | Anchored on Winder et al. (2025) global ETF benchmark (~59% US) |
| R4 | Each structured claim matches fund data | see mapping | holding | Fund data (provenance shown) |
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

- **look_again**: holding fails a holding-scope rule (R2, R4 fail).
- **review**: holding contributes to a failed portfolio-scope rule (R1, R3, R5) and is not already `look_again`. A holding "contributes" if it adds to the exceeded quantity (equity > 0 for R1; us_pct > 0 for R3; risk_level above max for R5).
- **checked**: no failed rule touches it.
- Unverifiable claims are listed separately as **not checked** — never shown as passed.

## 6. Hedge rendering

First-person wording follows Kim et al. (2024). The wording is fixed by templates, **not generated by the LLM**, so the hedge always matches the checker result.

| Level | Badge | Template |
|---|---|---|
| look_again | Look again | "I'm not confident this suits you: {evidence}." |
| review | Review | "I'm unsure about this part of the plan: {evidence}." |
| checked | Checked | "{pass_evidence}." |
| not checked | — | "Not checked: {claims}. Nobody can verify forecasts." |

Comparison mode (**Disclaimer-only**) [P]: no badges; one banner: "AI suggestions can be wrong. This is not financial advice." (mirrors the generic disclaimers Winder et al. found in ~95% of responses).

"Why?" panel: the fund's row from `funds.csv` (fields used, `source`, `as_of`) + the rule and threshold (shown, not just cited — L11).

## 7. Prompt specification (L09 six parts)

- **Task**: propose 1–6 holdings from the supplied fund list for the confirmed profile.
- **Audience**: beginner UK private investor; plain English.
- **Constraints**: only fund IDs from the list; integer weights summing to 100; never change the profile — use `profile_change_suggested`; no return forecasts as facts; if the question is outside portfolio suggestion, return an empty `holdings` list and say so in `summary` (decline).
- **Examples**: one valid output (kept short; L09 warns examples get copied).
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

`logs/session_*.jsonl`: timestamp, mode (hedge; disclaimer mode [P]), profile, holdings, per-holding level, user action (why/remove/keep/regenerate/accept). No personal data beyond the form fields.

## 11. Boundaries (state these in the report)

- The checker catches **suitability** problems against the confirmed profile; it cannot judge forecasts or future returns.
- Thresholds marked ASSUMPTION are design choices, not regulatory rules.
- Fund data is fictional [S]; live data [P].
- No user study in A2 [P]; logging prepares it. Disclaimer-only comparison mode [P] (cut to fit the 19/11 deadline).
- Not financial advice; the system never executes trades.

## 12. Sources for thresholds

- MoneyHelper, *Should I save or invest my money?* — consider investing only money not needed in the next five years.
- HSBC UK, *Saving vs investing* — for short-term needs such as a home deposit, saving makes sense; under 5 years gives less chance to recover a fall.
- Vanguard UK, LifeStrategy range — 20/40/60/80/100% equity mixes.
- UCITS KIID SRRI — 1–7 scale based on volatility bands (CESR, 2010).
- Winder, Hildebrand & Hartmann (2025) — global ETF benchmark ~59% US equities.

## Changelog

- v0.2 (2026-11-16): R1 horizon bands 3/7 → 5/10 years after checking UK consumer guidance; added H0 horizon notice; R2 caps 30/40/50 → 20/30/40; R5 high cap 7 → 6; Disclaimer-only mode moved to planned (deadline).
- v0.1 (2026-11-16): first draft.
