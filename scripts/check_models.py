"""Find which provider models can run this app end to end, and record them in data/working_models.json.

For each chat model the provider currently serves, sends one fixed request through the app's pipeline
(prompt -> model -> validator -> checker). A model is kept if it returns a valid, checkable plan.

Usage (needs API keys in .env):
  python scripts/check_models.py --provider groq           # check all current Groq chat models
  python scripts/check_models.py --provider gemini --dry-run
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.funds import load_funds  # noqa: E402
from app.llm_client import WORKING_MODELS_FILE, list_models, make_client  # noqa: E402
from app.models import Profile  # noqa: E402
from app.pipeline import run  # noqa: E402

PROFILE = Profile(goal="general_growth", horizon_years=10, risk="medium", amount_gbp=10000)
QUESTION = "How should I invest my money?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["groq", "gemini"])
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true", help="report only, do not update the file")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    funds = load_funds()
    data = json.loads(WORKING_MODELS_FILE.read_text()) if WORKING_MODELS_FILE.exists() else {}
    verified = data.setdefault(args.provider, {})

    for model in list_models(args.provider):
        res = run(PROFILE, QUESTION, make_client(args.provider, model=model), funds)
        ok = res.status == "ok"
        note = res.status if ok else (res.errors[-1][:90] if res.errors else res.status)
        print(f"{'OK  ' if ok else 'FAIL'} {model}: {note}")
        if ok:
            verified[model] = f"{date.today()}: check_models.py, valid plan ({len(res.raw_outputs)} attempt(s))"
        else:
            verified.pop(model, None)
        time.sleep(args.sleep)

    if args.dry_run:
        print("\nDry run: file not changed.")
    else:
        WORKING_MODELS_FILE.write_text(json.dumps(data, indent=2) + "\n")
        print(f"\nUpdated {WORKING_MODELS_FILE.relative_to(ROOT)}: {sorted(verified)}")


if __name__ == "__main__":
    main()
