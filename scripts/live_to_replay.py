"""Turn a logged live run into a replay scenario, so a real model run can be re-shown without an API key.

Usage: python scripts/live_to_replay.py logs/session_XXXX.jsonl [scenario_id] [title]
Takes the first confirmed profile and every model_result in the session, in order.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

log_path = Path(sys.argv[1])
scenario_id = sys.argv[2] if len(sys.argv) > 2 else "live_" + log_path.stem.replace("session_", "")
title = sys.argv[3] if len(sys.argv) > 3 else "Recorded live run"

records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
profile = next(r["profile"] for r in records if r["event"] == "profile_confirmed")
results = [r for r in records if r["event"] == "model_result" and r.get("raw_outputs")]
if not results:
    sys.exit("No model_result with raw_outputs in this log (runs before 2026-11-17 did not store them).")

calls = [json.loads(r["raw_outputs"][-1]) for r in results]  # last attempt = the validated one
scenario = {"id": scenario_id, "title": title, "profile": profile,
            "question": results[0]["question"], "calls": calls,
            "recorded_from": {"log": log_path.name, "provider": results[0]["provider"],
                              "model": results[0].get("model"), "ts": results[0]["ts"],
                              "prompt_version": results[0].get("prompt_version", "v1")}}
out = ROOT / "replays" / f"{scenario_id}.json"
out.write_text(json.dumps(scenario, indent=2))
print(f"Wrote {out.relative_to(ROOT)} with {len(calls)} call(s).")
