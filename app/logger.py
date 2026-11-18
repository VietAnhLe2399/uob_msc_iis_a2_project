"""Append-only JSONL log of flags and user actions (SPEC §10). Only form fields are stored."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.getenv("SECOND_LOOK_LOG_DIR", Path(__file__).resolve().parent.parent / "logs"))


class SessionLog:
    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.path = LOG_DIR / f"session_{self.session_id}.jsonl"
        self.mode = "checks"  # "checks" or "disclaimer" (comparison condition)

    def write(self, event: str, **data):
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "session": self.session_id, "mode": self.mode, "event": event, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
