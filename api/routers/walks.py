"""api/routers/walks.py — список, создание и редактирование прогулок."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database as db
from api.auth import get_current_member
from api.schemas import WalkCreate, WalkOut, WalkUpdate

router = APIRouter(prefix="/api/walks", tags=["walks"])


@router.get("", response_model=List[WalkOut])
def list_walks(
    days: Optional[int] = Query(default=30),
    limit: Optional[int] = Query(default=None),
    offset: int = Query(default=0),
    member: dict = Depends(get_current_member),
):
    return db.get_walks(member["family_id"], days=days, limit=limit, offset=offset)


@router.post("", response_model=WalkOut)
def create_walk(payload: WalkCreate, member: dict = Depends(get_current_member)):
    walk_id = db.add_walk(
        member["family_id"],
        member["tg_user_id"],
        duration_minutes=payload.duration_minutes,
        note=payload.note,
        together=payload.together,
    )
    return db.get_walk(walk_id, member["family_id"])


@router.patch("/{walk_id}", response_model=WalkOut)
def patch_walk(walk_id: int, payload: WalkUpdate, member: dict = Depends(get_current_member)):
    if db.get_walk(walk_id, member["family_id"]) is None:
        raise HTTPException(status_code=404, detail="Прогулка не найдена")

    fields = payload.model_dump(exclude_unset=True)
    db.update_walk(walk_id, member["family_id"], fields)
    return db.get_walk(walk_id, member["family_id"])
