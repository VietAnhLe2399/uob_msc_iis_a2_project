"""Data contracts: the user profile (input) and the LLM plan (output). See docs/SPEC.md §2-3."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Goal = Literal["house_deposit", "retirement", "general_growth", "income"]
Risk = Literal["low", "medium", "high"]
Claim = Literal["low_risk", "low_cost", "diversified", "income", "growth", "other"]

GOAL_LABELS = {
    "house_deposit": "house deposit",
    "retirement": "retirement",
    "general_growth": "general growth",
    "income": "income",
}


class Profile(BaseModel):
    goal: Goal
    horizon_years: int = Field(ge=1, le=30)
    risk: Risk
    amount_gbp: int = Field(ge=500, le=1_000_000)

    def describe(self) -> str:
        return (f"a {self.horizon_years}-year {GOAL_LABELS[self.goal]} goal, "
                f"{self.risk} risk, £{self.amount_gbp:,}")


class Holding(BaseModel):
    fund_id: str
    weight_pct: int = Field(ge=5, le=100)
    claims: List[Claim] = Field(default_factory=list)
    reason: str = ""


class ProfileChange(BaseModel):
    field: Literal["goal", "horizon_years", "risk", "amount_gbp"]
    value: str
    quote: str = ""


class Plan(BaseModel):
    holdings: List[Holding]
    profile_change_suggested: Optional[ProfileChange] = None
    summary: str = ""
