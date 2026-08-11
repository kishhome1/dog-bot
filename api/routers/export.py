"""api/routers/export.py — выгрузка истории в CSV (вкладка «Настройки» → «Экспорт истории»).

Портирует логику старого /export из bot.py (когда это ещё была команда бота)
под новую family_id-схему; прогулки и обработки — два отдельных файла, а не
один с разными листами (CSV не поддерживает несколько листов)."""

import csv
import io

from fastapi import APIRouter, Depends, Response

import database as db
from api.auth import get_current_member
from api.constants import TREATMENT_LABELS

router = APIRouter(prefix="/api/export", tags=["export"])


def _csv_response(header: list, rows: list, filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    # utf-8-sig — чтобы Excel на Windows не перепутал кодировку кириллицы.
    content = buffer.getvalue().encode("utf-8-sig")
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/walks")
def export_walks(member: dict = Depends(get_current_member)):
    family_id = member["family_id"]
    name_by_tg_user_id = {m["tg_user_id"]: m["display_name"] for m in db.get_family_members(family_id)}
    walks = db.get_walks(family_id)

    rows = [
        [
            w["walked_at"].strftime("%d.%m.%Y %H:%M"),
            name_by_tg_user_id.get(w["tg_user_id"], "Кто-то"),
            w["duration_minutes"] if w["duration_minutes"] is not None else "",
            "Да" if w["together"] else "",
            w["note"] or "",
        ]
        for w in walks
    ]
    return _csv_response(
        ["Дата и время", "Кто гулял", "Длительность (мин)", "Вместе", "Заметка"],
        rows,
        "barbos_walks.csv",
    )


@router.get("/treatments")
def export_treatments(member: dict = Depends(get_current_member)):
    treatments = db.get_all_treatments(member["family_id"])

    rows = [
        [
            t["treated_on"].strftime("%d.%m.%Y"),
            t["custom_name"] if t["category"] == "other" else TREATMENT_LABELS.get(t["category"], t["category"]),
            t["drug_name"] or "",
            t["interval_days"],
        ]
        for t in treatments
    ]
    return _csv_response(
        ["Дата", "Категория", "Препарат", "Срок действия (дней)"],
        rows,
        "barbos_treatments.csv",
    )
