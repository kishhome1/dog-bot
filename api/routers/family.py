"""api/routers/family.py — аутентификация, создание/подключение/настройки семьи."""

import os

from fastapi import APIRouter, Depends, HTTPException

import database as db
from api.auth import get_current_member, get_telegram_user
from api.schemas import (
    AuthResponse,
    CreateFamilyRequest,
    CreateFamilyResponse,
    JoinFamilyRequest,
    JoinFamilyResponse,
    UpdateProfileRequest,
    UpdateRemindersRequest,
)

router = APIRouter(prefix="/api", tags=["family"])

# Юзернейм бота (без @) — нужен только для сборки инвайт-ссылки t.me/<bot>?start=invite_<code>.
BOT_USERNAME = os.getenv("BOT_USERNAME")


def build_invite_url(invite_code: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=invite_{invite_code}"


def _build_auth_response(tg_user_id: int) -> AuthResponse:
    member = db.get_member_by_tg_user_id(tg_user_id)
    if member is None:
        return AuthResponse(needs_onboarding=True)

    family = db.get_family(member["family_id"])
    members = db.get_family_members(member["family_id"])
    reminder_times = db.get_reminder_times(member["family_id"]) if family["reminder_mode"] == "fixed" else []
    return AuthResponse(
        needs_onboarding=False,
        family_id=member["family_id"],
        pet_name=family["pet_name"],
        pet_sex=family["pet_sex"],
        reminder_mode=family["reminder_mode"],
        interval_hours=family["interval_hours"],
        reminder_times=reminder_times,
        invite_url=build_invite_url(family["invite_code"]),
        members=members,
    )


@router.post("/auth", response_model=AuthResponse)
def auth(user: dict = Depends(get_telegram_user)):
    return _build_auth_response(user["tg_user_id"])


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
    return CreateFamilyResponse(invite_url=build_invite_url(result["invite_code"]), **result)


@router.post("/family/join", response_model=JoinFamilyResponse)
def join_family(payload: JoinFamilyRequest, user: dict = Depends(get_telegram_user)):
    family = db.get_family_by_invite_code(payload.invite_code)
    if family is None:
        raise HTTPException(status_code=404, detail="Инвайт-код не найден")

    result = db.join_family(family["id"], user["tg_user_id"], user["display_name"])
    return JoinFamilyResponse(**result)


@router.patch("/family", response_model=AuthResponse)
def update_profile(payload: UpdateProfileRequest, member: dict = Depends(get_current_member)):
    """Вкладка «Настройки» → «Профиль собаки» — правка клички/пола после онбординга."""
    fields = payload.model_dump(exclude_unset=True)
    db.update_family_profile(member["family_id"], fields)
    return _build_auth_response(member["tg_user_id"])


@router.patch("/family/reminders", response_model=AuthResponse)
def update_reminders(payload: UpdateRemindersRequest, member: dict = Depends(get_current_member)):
    """Вкладка «Настройки» → «Напоминания» — смена режима/времён после онбординга.
    Само расписание в bot.py подхватит изменение на ближайшем тике reconcile_reminders
    (раз в 5 минут) — отдельно ничего пересчитывать здесь не нужно."""
    db.set_reminder_config(
        member["family_id"],
        payload.reminder_mode,
        payload.interval_hours,
        payload.times or [],
    )
    return _build_auth_response(member["tg_user_id"])
