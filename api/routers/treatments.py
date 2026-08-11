"""api/routers/treatments.py — категории обработок, история, добавление/редактирование."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import database as db
from api.auth import get_current_member
from api.constants import TREATMENT_LABELS, compute_status
from api.schemas import TreatmentCategoryOut, TreatmentCreate, TreatmentOut, TreatmentUpdate

router = APIRouter(prefix="/api/treatments", tags=["treatments"])


@router.get("", response_model=List[TreatmentCategoryOut])
def list_categories(member: dict = Depends(get_current_member)):
    rows = db.get_treatment_categories(member["family_id"])
    result = []
    for row in rows:
        status = compute_status(row["interval_days"], row["treated_on"])
        label = row["custom_name"] if row["category"] == "other" else TREATMENT_LABELS[row["category"]]
        result.append(TreatmentCategoryOut(label=label, **status, **row))
    return result


@router.get("/history", response_model=List[TreatmentOut])
def category_history(
    category: str,
    custom_name: Optional[str] = Query(default=None),
    member: dict = Depends(get_current_member),
):
    return db.get_treatment_history(member["family_id"], category, custom_name)


@router.post("", response_model=TreatmentOut)
def create_treatment(payload: TreatmentCreate, member: dict = Depends(get_current_member)):
    treatment_id = db.add_treatment(
        member["family_id"],
        category=payload.category,
        treated_on=payload.treated_on,
        custom_name=payload.custom_name,
        drug_name=payload.drug_name,
        interval_days=payload.interval_days,
    )
    return db.get_treatment(treatment_id, member["family_id"])


@router.patch("/{treatment_id}", response_model=TreatmentOut)
def patch_treatment(treatment_id: int, payload: TreatmentUpdate, member: dict = Depends(get_current_member)):
    if db.get_treatment(treatment_id, member["family_id"]) is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    fields = payload.model_dump(exclude_unset=True)
    db.update_treatment(treatment_id, member["family_id"], fields)
    return db.get_treatment(treatment_id, member["family_id"])
