"""api/routers/stats.py — агрегаты для экрана «Статистика»."""

from typing import Literal

from fastapi import APIRouter, Depends, Query

import database as db
from api.auth import get_current_member
from api.schemas import StatsResponse

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
def get_stats(
    period: Literal["week", "month", "year"] = Query(default="week"),
    member: dict = Depends(get_current_member),
):
    result = db.get_stats(member["family_id"], period)
    return StatsResponse(period=period, **result)
