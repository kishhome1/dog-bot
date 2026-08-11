"""api/routers/family.py — аутентификация, создание и подключение к семье."""

import os

from fastapi import APIRouter, Depends, HTTPException

import database as db
from api.auth import get_telegram_user
from api.schemas import (
    AuthResponse,
    CreateFamilyRequest,
    CreateFamilyResponse,
    JoinFamilyRequest,
    JoinFamilyResponse,
)

router = APIRouter(prefix="/api", tags=["family"])

# Юзернейм бота (без @) — нужен только для сборки инвайт-ссылки t.me/<bot>?start=invite_<code>.
BOT_USERNAME = os.getenv("BOT_USERNAME")


@router.post("/auth", response_model=AuthResponse)
def auth(user: dict = Depends(get_telegram_user)):
    member = db.get_member_by_tg_user_id(user["tg_user_id"])
    if member is None:
        return AuthResponse(needs_onboarding=True)

    family = db.get_family(member["family_id"])
    members = db.get_family_members(member["family_id"])
    return AuthResponse(
        needs_onboarding=False,
        family_id=member["family_id"],
        pet_name=family["pet_name"],
        pet_sex=family["pet_sex"],
        reminder_mode=family["reminder_mode"],
        interval_hours=family["interval_hours"],
        members=members,
    )


@router.post("/family", response_model=CreateFamilyResponse)
def create_family(payload: CreateFamilyRequest, user: dict = Depends(get_telegram_user)):
    if db.get_member_by_tg_user_id(user["tg_user_id"]) is not None:
        raise HTTPException(status_code=409, detail="Пользователь уже состоит в семье")

    result = db.create_family(
        pet_name=payload.pet_name,
        reminder_mode=payload.reminder_mode,
        interval_hours=payload.interval_hours,
        times=payload.times or [],
        tg_user_id=user["tg_user_id"],
        display_name=user["display_name"],
        timezone=payload.timezone,
        pet_sex=payload.pet_sex,
    )
    invite_url = f"https://t.me/{BOT_USERNAME}?start=invite_{result['invite_code']}"
    return CreateFamilyResponse(invite_url=invite_url, **result)


@router.post("/family/join", response_model=JoinFamilyResponse)
def join_family(payload: JoinFamilyRequest, user: dict = Depends(get_telegram_user)):
    family = db.get_family_by_invite_code(payload.invite_code)
    if family is None:
        raise HTTPException(status_code=404, detail="Инвайт-код не найден")

    result = db.join_family(family["id"], user["tg_user_id"], user["display_name"])
    return JoinFamilyResponse(**result)
