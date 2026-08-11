"""api/schemas.py — pydantic-модели запросов и ответов FastAPI."""

from datetime import date, datetime, time
from typing import List, Literal, Optional

from pydantic import BaseModel, model_validator


class FamilyMemberOut(BaseModel):
    id: int
    tg_user_id: int
    display_name: str


class AuthResponse(BaseModel):
    needs_onboarding: bool
    family_id: Optional[int] = None
    pet_name: Optional[str] = None
    reminder_mode: Optional[Literal["fixed", "interval"]] = None
    interval_hours: Optional[float] = None
    members: List[FamilyMemberOut] = []


class CreateFamilyRequest(BaseModel):
    pet_name: str
    reminder_mode: Literal["fixed", "interval"]
    interval_hours: Optional[float] = None
    times: Optional[List[time]] = None

    @model_validator(mode="after")
    def check_mode_params(self):
        # field_validator would skip fields that fall back to their default
        # (i.e. weren't passed at all) unless validate_default=True — since
        # times/interval_hours are exactly the fields we expect callers to
        # omit for the "wrong" mode, the cross-field check has to live here
        # instead, where it always runs against the fully-built model.
        if self.reminder_mode == "fixed" and not self.times:
            raise ValueError("Для режима 'fixed' нужно хотя бы одно время")
        if self.reminder_mode == "interval" and not self.interval_hours:
            raise ValueError("Для режима 'interval' нужно указать interval_hours")
        return self


class CreateFamilyResponse(BaseModel):
    family_id: int
    invite_code: str
    invite_url: str


class JoinFamilyRequest(BaseModel):
    invite_code: str


class JoinFamilyResponse(BaseModel):
    family_id: int


class WalkCreate(BaseModel):
    duration_minutes: Optional[int] = None
    note: Optional[str] = None
    together: bool = False


class WalkUpdate(BaseModel):
    duration_minutes: Optional[int] = None
    note: Optional[str] = None
    together: Optional[bool] = None


class WalkOut(BaseModel):
    id: int
    tg_user_id: int
    walked_at: datetime
    duration_minutes: Optional[int] = None
    note: Optional[str] = None
    together: bool


class TreatmentCreate(BaseModel):
    category: Literal["ticks", "deworming", "vaccine", "other"]
    custom_name: Optional[str] = None
    treated_on: date
    drug_name: Optional[str] = None

    @model_validator(mode="after")
    def check_custom_name(self):
        if self.category == "other" and not self.custom_name:
            raise ValueError("Для категории 'other' нужно название")
        return self


class TreatmentUpdate(BaseModel):
    treated_on: Optional[date] = None
    drug_name: Optional[str] = None
    custom_name: Optional[str] = None


class TreatmentOut(BaseModel):
    id: int
    category: str
    custom_name: Optional[str] = None
    treated_on: date
    drug_name: Optional[str] = None


class TreatmentCategoryOut(BaseModel):
    category: str
    custom_name: Optional[str] = None
    label: str
    treated_on: date
    drug_name: Optional[str] = None
    days_remaining: int
    status: Literal["ok", "soon", "overdue"]
    progress_percent: int


class StatsMemberCount(BaseModel):
    member_id: int
    display_name: str
    walk_count: int


class StatsReward(BaseModel):
    member_id: int
    display_name: str
    bronze: int
    silver: int
    gold: int


class StatsResponse(BaseModel):
    period: Literal["week", "month", "year"]
    total: int
    by_member: List[StatsMemberCount]
    rewards: List[StatsReward]
