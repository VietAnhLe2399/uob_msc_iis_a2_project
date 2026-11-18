# Second Look

README prose word count: about 1430 (excluding code blocks and commands)

An investment-suggestion assistant for beginner UK investors. A language model proposes a portfolio from a fixed fund list; **deterministic code** checks every suggestion against the user's confirmed profile; the interface attaches a per-suggestion badge (*Look again* / *Review* / *Checked*) with the evidence beside it. The user decides; nothing is bought or sold. Design question carried from my Assignment 1: if hedges are tied to *detectable* suitability problems instead of the model's own confidence, can users spot unsuitable advice? Full specification and dated changelog: [docs/SPEC.md](docs/SPEC.md).

Status labels: **[I]** implemented · **[S]** simulated · **[P]** planned.

## Project status

**Implemented [I]**
- Profile form → "I understood…" confirmation → horizon notice (H0) for money needed within 5 years.
- LLM call (Groq or Gemini) returning JSON; validator V1–V6 (schema, closed fund list, weights = 100, ≤6 holdings, no duplicates, no repeated profile change once the user has refused one); one retry, then a decline turn.
- Checker: R1 share of stocks, R2 one sector, R3 one market, R4 model's claims vs fund data, R5 average risk, R6 the user's explicit request vs the plan.
- Badges with fixed hedge wording, *Why?* panel with the fund data and rule, *Remove* (plan re-checked, removed share kept as cash), *Keep anyway*, *Undo*, one *Suggest again within my profile*.
- Model-proposed profile changes shown for the user to confirm (repair turn); model summary labelled "(not checked)".
- Comparison mode: same plan with one generic disclaimer; checks still run and are logged.
- Logs of flags and user actions; replay of stored model outputs; batch evaluation; 58 tests.

**Simulated [S]**
- Fund data: 16 fictional funds used as controlled test data (known answers for every rule).
- Replay scenarios 1–4 use model outputs I scripted to show each behaviour; `live_*` replays are recorded live Groq runs.

**Planned [P] / unfinished**
- A small user study comparing the two display modes (the logging is ready).
- Real or live fund data; sector look-through for global funds (R2 counts thematic funds only).
- Keeping a profile between sessions.

**Deliberate boundaries:** the checks cover suitability against the confirmed profile; they cannot judge forecasts ("growth" claims are shown as *not checked*), and the model's reasons and summary are not checked. Not financial advice.

## Technology stack

| Part | Choice | Role |
|---|---|---|
| Language, UI | Python 3.10+, Streamlit | App and interaction |
| Contracts | Pydantic | Profile and plan schemas |
| LLM | Groq `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`; Google Gemini `gemini-3.8-flash` (verified models, see `data/working_models.json`) | Proposes the plan as JSON |
| No-key mode | `replay` | Serves stored model outputs |
| Tests | pytest, Streamlit AppTest | Rules, validator, UI flows |

Model names change over time, so the app offers only models verified end to end that the provider still serves; `.env` sets the default. Still open: which provider to use for a user study.

## Running or inspecting the work

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # LLM_PROVIDER=replay needs no API key
streamlit run app/streamlit_app.py
pytest                          # 58 tests
```

- **Without a key:** keep provider `replay` and pick a scenario in the sidebar. `live_groq_v4_ai` shows all three badges from a real run; `scenario_2` walks through remove, undo and *Suggest again*; `scenario_3` shows the profile-repair turn; `scenario_4` shows R6.
- **With your own key:** put `GROQ_API_KEY` or `GEMINI_API_KEY` in `.env`, choose the provider in the sidebar, then pick a model (verified models still served by the provider; `GROQ_MODEL` / `GEMINI_MODEL` set the default). Never commit `.env`.
- **Inspect a result:** open *Technical trace* under the plan (provider, model, prompt version, rule table, raw model output).
- **Comparison mode:** sidebar → *What the user sees* → *Generic disclaimer only*.

```bash
python scripts/batch_eval.py --provider groq --runs 2          # live runs → eval/batch_*.csv + summary
python scripts/batch_eval.py --summarise eval/<file>.csv
python scripts/live_to_replay.py logs/<session>.jsonl <id> "<title>"   # keep a live run as a replay
python scripts/check_models.py --provider groq                         # re-verify which models work
```

## Development record

The repository was created on 18 Nov after development on 16–18 Nov. The first three commits are real snapshots of the work as it existed on 16–17 Nov (dates in the commit messages); the next four group the later changes by component. Dated detail is in the [SPEC changelog](docs/SPEC.md#changelog).

| Commit | Content |
|---|---|
| [6ac3c12](../../commit/6ac3c12) | Spec v0.1, fund data, skeleton (16 Nov) |
| [094fb48](../../commit/094fb48) | Spec v0.2: thresholds (16 Nov) |
| [e03d762](../../commit/e03d762) | First working version (17 Nov, 10:49) |
| [06ef8a8](../../commit/06ef8a8) | Rules v0.3–v0.4 |
| [80faef5](../../commit/80faef5) | LLM layer and UI after live runs |
| [d648a5c](../../commit/d648a5c) | Live replays and tests |
| [2d91e14](../../commit/2d91e14) | Batch evaluation |

**1. Hedges come from code, not from the model.** A1 ended on the risk that hedges help only if they match real unreliability. Claude proposed computing them from suitability checks, since a model's confidence is a self-report, not a check (Lecture 9); I agreed and set the scope. *Checked:* seeded-error tests, one known fault each. [e03d762](../../commit/e03d762)

**2. Fictional fund data as controlled test data.** I kept it fictional when the deadline was extended: known answers make tests and evaluation meaningful, and real data is not what the project tests. [06ef8a8](../../commit/06ef8a8)

**3. Thresholds.** R1 bands moved from 3/7 to 5/10 years after checking UK guidance (MoneyHelper, HSBC); the market cap is anchored on Winder et al. (2025); sector and risk caps are declared assumptions. Claude found the sources; I read and approved them. [094fb48](../../commit/094fb48)

**4. Providers.** Groq's default model returned 404, so I switched to `openai/gpt-oss-120b`; Gemini 2.5 Flash was closed to new users, so model names moved to `.env` and I tested `gemini-3.8-flash`. I removed Ollama because replay already gives a no-key option. Later I added a model picker. A first version listed every chat model the provider served; trying a small one (`allam-2-7b`) showed it could not keep to the JSON format. Provider-side JSON rejections now get the same one retry as V1, and I decided the picker should offer only models verified to work: I checked `gpt-oss-20b` and `qwen3.8-27b` by hand, and `scripts/check_models.py` re-verifies the list. [80faef5](../../commit/80faef5)

**5. Rule review after live runs.** My first live run showed the model's summary claiming the plan "aligns with your medium risk" above three warnings, so summaries are now labelled "(not checked)". I then asked why *Review* badges had disappeared; a cash fund had been marked "not confident this suits you" only because the model called it "diversified". At my request we reviewed every rule: R4 became a *description* finding (Review, own wording), Review now marks only funds that are themselves over a limit, and R3 checks every market (100% UK shares had passed every rule). *Checked:* a test per case. [06ef8a8](../../commit/06ef8a8)

**6. Prompt changes, measured.** v2 defines claim tags; v3 says interest in a theme is not a profile change (an AI question had produced no plan); v4 asks the model to state the user's explicit request. Prompt rules alone were not enough: `gpt-oss-20b` still turned "most of my money in AI" into a risk change, and *Keep my current profile* led back to the same proposal. That button now asks for a plan at once and code (V6) refuses a repeated proposal, so the user's choice wins. Batch evaluation (Groq, 20 runs per version, descriptive only): profile-change turns 6/20 (v1) → 0/20 (v4); false claims 15 in 9 of 14 plans → 4 in 4 of 19. Never zero, so the code check stays. [eval/](eval)

**7. R6 built, not planned.** A live run answered "most of my money into AI" with 20% technology and no explanation. Claude listed this as planned; I asked why it could not be built. R6 now shows the request the model read and the plan's actual share, and warns when a reduction is unexplained. It is not sent back on *Suggest again*, so it cannot push past the sector limit. [06ef8a8](../../commit/06ef8a8)

**8. Scope and robustness.** The disclaimer-only mode, re-check after *Remove* and *Undo* were added after the extension; edge cases found in code review (duplicate funds, odd profile-change values) now have tests. [d648a5c](../../commit/d648a5c)

I did not tune thresholds to get more badges in live runs: *Look again* appeared in 1 of 33 checkable plans in the latest evaluation.

## AI assistance

I used **Claude (Anthropic, Opus 5.5)** throughout, in one long working session.

- **What it did:** drafted most of the code, the tests, `docs/SPEC.md`, the replay scenarios, the commit messages and this README, from my requirements and the module concepts; found threshold sources; reviewed the code for edge cases.
- **What I decided or changed:** the project direction from my A1; keeping fund data fictional; dropping Ollama; choosing the Groq and Gemini models after the defaults failed; asking why *Review* badges had disappeared, which led to the rule review; rejecting R6 as "planned" so it was built; wanting the history split into stages; after Claude advised against re-enacting or back-dating it, we used real snapshots.
- **How I checked:** ran the app live with Groq and Gemini and reviewed screenshots; ran the tests and the batch evaluation; opened the threshold sources; checked that no key or log is committed.

## Additional files

- `docs/SPEC.md`: specification, thresholds with sources, changelog.
- `replays/`: scripted (`scenario_*`) and recorded live (`live_*`) model outputs.
- `eval/`: batch evaluation results (CSV).
- `scripts/`: `batch_eval.py`, `live_to_replay.py`, `check_models.py`.
- `data/`: fictional fund list; `working_models.json` (verified models, with when and how).
- No ZIP is needed; everything is in this repository.
