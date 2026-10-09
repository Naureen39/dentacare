"""Features for the no show model, built only from what was known when the visit was booked.

Every number about a patient's earlier visits counts only visits that had already happened by
the moment this appointment was created. The one exception, the confirmation flag, is
something that becomes known days before the visit and is the signal the clinic acts on.
"""

from collections.abc import Callable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import FieldCipher

DOB_FIELD = "patients.dob"
AGE_BANDS = ["0-17", "18-29", "30-44", "45-64", "65+", "unknown"]
FEATURES = [
    "lead_days",
    "weekday",
    "hour",
    "age_band",
    "is_new",
    "prev_no_shows",
    "prev_no_show_rate",
    "prev_late_cancels",
    "service_category",
    "reminder_confirmed",
    "has_insurance",
]
CATEGORICAL = ["age_band", "service_category"]
NEW_PATIENT_DAYS = 90
CONFIRM_BEFORE_HOURS = 24

RAW_SQL = """
SELECT a.id, a.patient_id, a.dentist_id, lower(a.slot) AS start, a.created_at,
       a.status::text AS status, a.late_cancel, s.name AS service_name,
       s.category AS service_category, (p.insurance_provider_id IS NOT NULL) AS has_insurance,
       p.dob_enc, p.created_at AS patient_created,
       (SELECT min(h.changed_at) FROM appointment_status_history h
         WHERE h.appointment_id = a.id AND h.to_status = 'confirmed') AS confirmed_at
FROM appointments a
JOIN services s ON s.id = a.service_id
JOIN patients p ON p.id = a.patient_id
"""


async def load_raw(db: AsyncSession) -> pd.DataFrame:
    rows = (await db.execute(text(RAW_SQL))).mappings().all()
    frame = pd.DataFrame([dict(r) for r in rows])
    if frame.empty:
        return frame
    for column in ("start", "created_at", "patient_created", "confirmed_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def age_band(age: float | None) -> str:
    if age is None or np.isnan(age):
        return "unknown"
    if age < 18:
        return AGE_BANDS[0]
    if age < 30:
        return AGE_BANDS[1]
    if age < 45:
        return AGE_BANDS[2]
    if age < 65:
        return AGE_BANDS[3]
    return AGE_BANDS[4]


def build_features(
    raw: pd.DataFrame, cipher: FieldCipher, tz: ZoneInfo, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """One row per appointment with the model features, in the order of ``raw``."""
    if raw.empty:
        return raw.assign(**{name: [] for name in FEATURES})
    frame = raw.copy()
    local = frame["start"].dt.tz_convert(tz)
    frame["weekday"] = local.dt.weekday
    frame["hour"] = local.dt.hour
    frame["lead_days"] = ((frame["start"] - frame["created_at"]).dt.total_seconds() / 86400).clip(
        lower=0
    )

    births: dict[Any, date | None] = {}
    for patient_id, token in frame.drop_duplicates("patient_id")[
        ["patient_id", "dob_enc"]
    ].itertuples(index=False):
        # A patient without a date of birth arrives from pandas as NaN, which is truthy.
        value = (
            cipher.decrypt_optional(token, DOB_FIELD) if isinstance(token, str) and token else None
        )
        births[patient_id] = date.fromisoformat(value) if value else None
    ages = [
        ((start.date() - births[pid]).days / 365.25) if births[pid] else None
        for pid, start in zip(frame["patient_id"], local, strict=True)
    ]
    frame["age_band"] = [age_band(a) for a in ages]

    # Earlier visits: counted from the visits that started before this appointment was booked.
    starts = frame["start"].astype("int64").to_numpy()
    created = frame["created_at"].astype("int64").to_numpy()
    no_show = (frame["status"] == "no_show").to_numpy()
    completed = (frame["status"] == "completed").to_numpy()
    late = (frame["late_cancel"] & (frame["status"] == "cancelled")).to_numpy()
    prev_no_shows = np.zeros(len(frame))
    prev_completed = np.zeros(len(frame))
    prev_late = np.zeros(len(frame))
    for _, index in frame.groupby("patient_id").indices.items():
        order = index[np.argsort(starts[index])]
        sorted_starts = starts[order]
        cum_no_show = np.concatenate([[0], np.cumsum(no_show[order])])
        cum_completed = np.concatenate([[0], np.cumsum(completed[order])])
        cum_late = np.concatenate([[0], np.cumsum(late[order])])
        position = np.searchsorted(sorted_starts, created[index], side="left")
        prev_no_shows[index] = cum_no_show[position]
        prev_completed[index] = cum_completed[position]
        prev_late[index] = cum_late[position]
    attended = prev_no_shows + prev_completed
    frame["prev_no_shows"] = prev_no_shows
    frame["prev_late_cancels"] = prev_late
    frame["prev_no_show_rate"] = np.where(
        attended > 0, prev_no_shows / np.maximum(attended, 1), 0.0
    )
    frame["is_new"] = (
        (prev_completed == 0)
        & ((frame["created_at"] - frame["patient_created"]).dt.days < NEW_PATIENT_DAYS)
    ).astype(int)

    deadline = frame["start"] - pd.Timedelta(hours=CONFIRM_BEFORE_HOURS)
    if now is not None:
        deadline = deadline.where(deadline < now, now)
    frame["reminder_confirmed"] = (
        frame["confirmed_at"].notna() & (frame["confirmed_at"] <= deadline)
    ).astype(int)
    frame["has_insurance"] = frame["has_insurance"].astype(int)
    return frame


def model_matrix(frame: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    """The feature columns with categorical ones fixed to the categories seen in training."""
    matrix = frame[FEATURES].copy()
    for column in CATEGORICAL:
        matrix[column] = pd.Categorical(matrix[column], categories=categories[column])
    return matrix


LABELS: dict[str, Callable[[Any], str]] = {
    "lead_days": lambda r: f"Booked {r['lead_days']:.0f} days ahead",
    "weekday": lambda r: (
        f"{['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][int(r['weekday'])]} appointment"
    ),
    "hour": lambda r: (
        f"Appointment at {int(r['hour']) % 12 or 12}:00 {'AM' if r['hour'] < 12 else 'PM'}"
    ),
    "age_band": lambda r: f"Age group {r['age_band']}",
    "is_new": lambda r: "New patient" if r["is_new"] else "Returning patient",
    "prev_no_shows": lambda r: (
        f"{int(r['prev_no_shows'])} earlier no show{'s' if r['prev_no_shows'] != 1 else ''}"
    ),
    "prev_no_show_rate": lambda r: f"Earlier no show rate {r['prev_no_show_rate']:.0%}",
    "prev_late_cancels": lambda r: (
        f"{int(r['prev_late_cancels'])} earlier late cancellation{'s' if r['prev_late_cancels'] != 1 else ''}"
    ),
    "service_category": lambda r: f"{str(r['service_category']).capitalize()} visit",
    "reminder_confirmed": lambda r: (
        "Not confirmed yet" if not r["reminder_confirmed"] else "Confirmed"
    ),
    "has_insurance": lambda r: "Self pay" if not r["has_insurance"] else "Insured",
}


def describe(feature: str, row: Any) -> str:
    return str(LABELS[feature](row))
