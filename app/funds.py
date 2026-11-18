"""Closed fund universe loaded from data/funds.csv (fictional, simulated)."""
import csv
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
FUNDS_CSV = ROOT / "data" / "funds.csv"

COUNTRIES = {"eq_us": "US", "eq_uk": "UK", "eq_europe": "Europe", "eq_em": "Emerging markets"}
NUMERIC = {"equity_pct": float, "eq_us": float, "eq_uk": float, "eq_europe": float, "eq_em": float,
           "eq_other": float, "risk_level": int, "ongoing_charge_pct": float}
# eq_* = where the fund's EQUITY part is invested (% of the equity part); eq_other = many smaller markets.
PROMPT_FIELDS = ["fund_id", "name", "asset_class", "region", "sector", "equity_pct",
                 "eq_us", "eq_uk", "eq_europe", "eq_em", "eq_other", "risk_level", "ongoing_charge_pct"]


def load_funds(path: Path = FUNDS_CSV) -> Dict[str, dict]:
    funds = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for key, cast in NUMERIC.items():
                row[key] = cast(row[key])
            funds[row["fund_id"]] = row
    return funds


def funds_as_text(funds: Dict[str, dict]) -> str:
    """Compact CSV text of the fund list for the prompt (information, not instruction)."""
    lines = [",".join(PROMPT_FIELDS)]
    for fund in funds.values():
        lines.append(",".join(str(fund[k]) for k in PROMPT_FIELDS))
    return "\n".join(lines)
