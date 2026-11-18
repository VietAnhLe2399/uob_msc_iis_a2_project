"""Data contracts: the user profile (input) and the LLM plan (output). See docs/SPEC.md §2-3."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Goal = Literal["house_deposit", "retirement", "general_growth", "income"]
Risk = Literal["low", "medium", "high"]
Claim = Literal["low_risk", "low_cost", "diversified", "income", "growth", "other"]
FocusTarget = Literal["technology", "healthcare", "energy", "US", "UK", "Europe", "Emerging markets"]

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


def apply_profile_change(profile: "Profile", change: "ProfileChange") -> Optional["Profile"]:
    """Return the profile with the model's proposed change, or None if the value is not a valid profile value.
    The model proposes; the user confirms on the next screen; the form's own rules decide what is valid."""
    value: object = change.value
    if change.field in ("horizon_years", "amount_gbp"):
        try:
            value = int(str(change.value).strip())
        except ValueError:
            return None
    try:
        return Profile.model_validate({**profile.model_dump(), change.field: value})
    except Exception:
        return None


class RequestedFocus(BaseModel):
    """The model's structured reading of an explicit allocation wish in the user's message (shown back to the user)."""
    target: FocusTarget
    min_pct: int = Field(ge=1, le=100)
    quote: str = ""


class Plan(BaseModel):
    holdings: List[Holding]
    profile_change_suggested: Optional[ProfileChange] = None
    requested_focus: Optional[RequestedFocus] = None
    adjustment_note: str = ""
    summary: str = ""
