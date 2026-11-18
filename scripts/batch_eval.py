"""Batch evaluation: how often does a live model's plan break the checks, and do the prompt changes (v2 claim definitions, v3 profile-change scope) help?

Runs every profile in PROFILES `--runs` times per prompt version, through the same pipeline as the app
(prompt -> model -> validator -> checker), and writes one CSV row per run to eval/.

Usage (needs an API key in .env):
  python scripts/batch_eval.py --provider groq --runs 2 --prompts v1 v4 --questions plain theme
  python scripts/batch_eval.py --summarise eval/batch_XXXX.csv
"""
import argparse
import csv
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.funds import load_funds  # noqa: E402
from app.llm_client import make_client  # noqa: E402
from app.models import Profile  # noqa: E402
from app.pipeline import run  # noqa: E402

PROFILES = {  # spread across horizon bands and risk levels
    "deposit_3y_low": Profile(goal="house_deposit", horizon_years=3, risk="low", amount_gbp=10000),
    "growth_7y_medium": Profile(goal="general_growth", horizon_years=7, risk="medium", amount_gbp=20000),
    "growth_10y_medium": Profile(goal="general_growth", horizon_years=10, risk="medium", amount_gbp=100000),
    "retire_20y_high": Profile(goal="retirement", horizon_years=20, risk="high", amount_gbp=30000),
    "income_12y_low": Profile(goal="income", horizon_years=12, risk="low", amount_gbp=50000),
}
QUESTIONS = {  # a plain question and a theme-driven one (the theme one tempts sector bets and over-eager repair)
    "plain": "How should I invest my money?",
    "theme": "I'm really excited about AI and technology companies. How should I invest?",
}
FIELDS = ["ts", "provider", "model", "prompt_version", "profile", "question", "run", "status", "attempts",
          "validator_errors", "n_holdings", "failed_rules", "n_false_claims", "levels",
          "any_flag", "suitability_flag", "description_flag", "request_status", "error"]


def one_run(provider, prompt_version, name, profile, i, funds, qkey="plain"):
    client = make_client(provider)
    res = run(profile, QUESTIONS[qkey], client, funds, prompt_version=prompt_version)
    rep = res.report
    failed = [r for r in rep.failed_rules] if rep else []
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": provider,
        "model": getattr(client, "model", provider), "prompt_version": prompt_version, "profile": name,
        "question": qkey,
        "run": i, "status": res.status, "attempts": len(res.raw_outputs),
        "validator_errors": " | ".join(e for e in res.errors if e.startswith("V")),
        "n_holdings": len(res.plan.holdings) if res.plan else 0,
        "failed_rules": " ".join(sorted({r.rule for r in failed})),
        "n_false_claims": sum(1 for r in failed if r.rule == "R4"),
        "levels": " ".join(f"{k}:{v.level}" for k, v in rep.holdings.items()) if rep else "",
        "any_flag": int(bool(failed)),
        "suitability_flag": int(any(r.scope in ("portfolio", "holding") for r in failed)),
        "description_flag": int(any(r.scope == "description" for r in failed)),
        "request_status": "" if res.request is None else
        f"{res.request.status} ({res.request.requested_pct}->{res.request.actual_pct:.0f} {res.request.target})",
        "error": " | ".join(e for e in res.errors if not e.startswith("V"))[:300],
    }


def summarise(path):
    rows = list(csv.DictReader(open(path)))
    by = defaultdict(list)
    for r in rows:
        by[r["prompt_version"]].append(r)
    for v, rs in sorted(by.items()):
        ok = [r for r in rs if r["status"] == "ok"]
        rules = Counter(rule for r in ok for rule in r["failed_rules"].split())
        pc = sum(1 for r in rs if r["status"] == "profile_change")
        print(f"\nPrompt {v}: {len(rs)} runs, {len(ok)} produced a checkable plan, {pc} asked for a profile change, "
              f"{sum(1 for r in rs if int(r['attempts'] or 0) > 1)} needed a validator retry, "
              f"{sum(1 for r in rs if r['status'] == 'system_declined')} declined/failed")
        print(f"  plans with any flag:          {sum(int(r['any_flag']) for r in ok)}/{len(ok)}")
        print(f"  plans with a suitability flag: {sum(int(r['suitability_flag']) for r in ok)}/{len(ok)}")
        print(f"  plans with a false claim (R4): {sum(int(r['description_flag']) for r in ok)}/{len(ok)}"
              f"  (false claims in total: {sum(int(r['n_false_claims']) for r in ok)})")
        print("  failed rules (count of plans):", dict(sorted(rules.items())))
        reqs = Counter(r["request_status"].split(" ")[0] for r in ok if r.get("request_status"))
        if reqs:
            print("  explicit requests (R6):", dict(reqs))
        per_profile = defaultdict(list)
        for r in ok:
            per_profile[f'{r["profile"]}/{r.get("question", "plain")}'].append(r["failed_rules"] or "-")
        for p, fr in per_profile.items():
            print(f"    {p:26s} {fr}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="groq")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--prompts", nargs="+", default=["v1", "v4"])
    ap.add_argument("--questions", nargs="+", default=["plain", "theme"], choices=list(QUESTIONS))
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between calls (rate limits)")
    ap.add_argument("--summarise", help="summarise an existing CSV and exit")
    args = ap.parse_args()
    if args.summarise:
        return summarise(args.summarise)

    load_dotenv(ROOT / ".env")
    funds = load_funds()
    out = ROOT / "eval" / f"batch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{args.provider}.csv"
    out.parent.mkdir(exist_ok=True)
    total = len(args.prompts) * len(PROFILES) * len(args.questions) * args.runs
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        k = 0
        for v in args.prompts:
            for name, profile in PROFILES.items():
                for q in args.questions:
                    for i in range(1, args.runs + 1):
                        k += 1
                        row = one_run(args.provider, v, name, profile, i, funds, q)
                        w.writerow(row)
                        f.flush()
                        print(f"[{k}/{total}] {v} {q} {name} #{i}: {row['status']} "
                              f"{row['failed_rules'] or '-'} {row['error'][:80]}")
                        time.sleep(args.sleep)
    print(f"\nSaved {out.relative_to(ROOT)}")
    summarise(out)


if __name__ == "__main__":
    main()
