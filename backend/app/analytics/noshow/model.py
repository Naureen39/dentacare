"""Training, registering and using the no show model."""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import structlog
from lightgbm import LGBMClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.noshow.features import (
    AGE_BANDS,
    CATEGORICAL,
    FEATURES,
    build_features,
    describe,
    load_raw,
    model_matrix,
)
from app.core.crypto import FieldCipher
from app.db.models import AppointmentRisk, ModelRegistry

logger = structlog.get_logger(__name__)

MODEL_NAME = "no_show"
TRAIN_MONTHS = 18
SCORING_DAYS = 7
TOP_DRIVERS = 3
MIN_ROWS = 500
HIGH_QUANTILE = 0.90  # the top decile of scores is "high"
MEDIUM_QUANTILE = 0.70
PARAMS: dict[str, Any] = {
    "n_estimators": 250, "learning_rate": 0.04, "num_leaves": 15, "min_child_samples": 40,
    "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0,
    "random_state": 42, "verbose": -1, "n_jobs": 2,
}  # fmt: skip


class ModelError(Exception):
    """The model cannot be trained or loaded; the message is safe to show to an operator."""


@dataclass
class TrainResult:
    version: str
    metrics: dict[str, Any]
    bundle: dict[str, Any]
    train_rows: int
    test_rows: int
    data_through: datetime


def add_months(moment: pd.Timestamp, months: int) -> pd.Timestamp:
    return moment + pd.DateOffset(months=months)


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    """Predicted against observed no show rate in equal sized groups of appointments."""
    order = np.argsort(p)
    table = []
    for chunk in np.array_split(order, bins):
        if len(chunk) == 0:
            continue
        table.append(
            {
                "mean_predicted": float(p[chunk].mean()),
                "observed": float(y[chunk].mean()),
                "count": int(len(chunk)),
            }
        )
    return table


def evaluate(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    decile = max(len(y) // 10, 1)
    top = np.argsort(-p)[:decile]
    base = float(y.mean())
    calibration = calibration_table(y, p)
    ece = sum(abs(c["mean_predicted"] - c["observed"]) * c["count"] for c in calibration) / len(y)
    return {
        "auc": float(roc_auc_score(y, p)),
        "precision_top_decile": float(y[top].mean()),
        "base_rate": base,
        "lift_top_decile": float(y[top].mean() / base) if base else None,
        "brier": float(brier_score_loss(y, p)),
        "expected_calibration_error": float(ece),
        "calibration": calibration,
    }


def train(
    db_frame: pd.DataFrame, cipher: FieldCipher, tz: ZoneInfo, *, version: str | None = None
) -> TrainResult:
    """Train on the first 18 months of outcomes and test on everything after them."""
    features = build_features(db_frame, cipher, tz)
    labelled = features[features["status"].isin(["completed", "no_show"])].copy()
    if len(labelled) < MIN_ROWS:
        raise ModelError(f"Only {len(labelled)} finished visits; at least {MIN_ROWS} are needed.")
    labelled["target"] = (labelled["status"] == "no_show").astype(int)
    first = labelled["start"].min()
    cutoff = add_months(first, TRAIN_MONTHS)
    train_rows = labelled[labelled["start"] < cutoff]
    test_rows = labelled[labelled["start"] >= cutoff]
    if len(train_rows) < MIN_ROWS or len(test_rows) < 100 or test_rows["target"].nunique() < 2:
        raise ModelError(
            "The history is too short for an 18 month training and a later test period."
        )

    categories = {
        "age_band": AGE_BANDS,
        "service_category": sorted(labelled["service_category"].astype(str).unique()),
    }
    x_train = model_matrix(train_rows, categories)
    x_test = model_matrix(test_rows, categories)
    model = LGBMClassifier(**PARAMS)
    model.fit(x_train, train_rows["target"], categorical_feature=CATEGORICAL)
    probabilities = np.asarray(model.predict_proba(x_test))[:, 1]
    metrics = evaluate(test_rows["target"].to_numpy(), probabilities)
    metrics["train_period"] = [
        train_rows["start"].min().isoformat(),
        train_rows["start"].max().isoformat(),
    ]
    metrics["test_period"] = [
        test_rows["start"].min().isoformat(),
        test_rows["start"].max().isoformat(),
    ]
    importance = dict(zip(FEATURES, model.booster_.feature_importance("gain"), strict=True))
    total = float(sum(importance.values())) or 1.0
    metrics["feature_importance"] = {
        k: round(float(v) / total, 4) for k, v in sorted(importance.items(), key=lambda kv: -kv[1])
    }

    # The cut points between low, medium and high come from the test period scores.
    thresholds = {
        "medium": float(np.quantile(probabilities, MEDIUM_QUANTILE)),
        "high": float(np.quantile(probabilities, HIGH_QUANTILE)),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    bundle = {
        "model": model, "features": FEATURES, "categories": categories,
        "thresholds": thresholds, "base_rate": metrics["base_rate"],
    }  # fmt: skip
    return TrainResult(
        version=version or stamp,
        metrics={**metrics, "thresholds": thresholds},
        bundle=bundle,
        train_rows=len(train_rows),
        test_rows=len(test_rows),
        data_through=labelled["start"].max().to_pydatetime(),
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def register(
    db: AsyncSession, result: TrainResult, directory: Path, *, activate: bool = True
) -> ModelRegistry:
    """Save the model file and record it. The new model becomes the active one."""
    path = directory / f"{MODEL_NAME}-{result.version}.joblib"

    def write() -> str:
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(result.bundle, path)
        return file_sha256(path)

    checksum = await asyncio.to_thread(write)
    row = ModelRegistry(
        id=uuid.uuid4(), name=MODEL_NAME, version=result.version, algorithm="lightgbm",
        path=path.name, sha256=checksum, metrics=result.metrics, features=FEATURES,
        train_rows=result.train_rows, test_rows=result.test_rows, data_through=result.data_through,
        is_active=False,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    if activate:
        await db.execute(
            update(ModelRegistry)
            .where(ModelRegistry.name == MODEL_NAME, ModelRegistry.id != row.id)
            .values(is_active=False)
        )
        row.is_active = True
    await db.commit()
    return row


async def active_model(db: AsyncSession) -> ModelRegistry | None:
    return (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.name == MODEL_NAME, ModelRegistry.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()


def load_bundle(row: ModelRegistry, directory: Path) -> dict[str, Any]:
    """Load the model file after checking it is the file that was registered."""
    path = directory / row.path
    if not path.is_file():
        raise ModelError(f"The model file {row.path} is missing.")
    if file_sha256(path) != row.sha256:
        raise ModelError("The model file does not match its registered checksum.")
    bundle: dict[str, Any] = joblib.load(path)  # noqa: S301  (checksum verified above)
    return bundle


async def load_bundle_async(row: ModelRegistry, directory: Path) -> dict[str, Any]:
    return await asyncio.to_thread(load_bundle, row, directory)


@dataclass
class Scored:
    appointment_id: uuid.UUID
    score: float
    drivers: list[dict[str, Any]]


def score_frame(bundle: dict[str, Any], features: pd.DataFrame) -> list[Scored]:
    """Score prepared feature rows. Drivers are the features pushing the score up the most."""
    if features.empty:
        return []
    matrix = model_matrix(features, bundle["categories"])
    model: LGBMClassifier = bundle["model"]
    probabilities = np.asarray(model.predict_proba(matrix))[:, 1]
    contributions = np.asarray(model.predict(matrix, pred_contrib=True))[:, : len(FEATURES)]
    out: list[Scored] = []
    rows = features.reset_index(drop=True)
    for i in range(len(rows)):
        order = np.argsort(-contributions[i])[:TOP_DRIVERS]
        drivers = [
            {
                "feature": FEATURES[j],
                "label": describe(FEATURES[j], rows.iloc[i]),
                "contribution": round(float(contributions[i][j]), 4),
            }
            for j in order
            if contributions[i][j] > 0
        ]
        out.append(Scored(rows.iloc[i]["id"], float(probabilities[i]), drivers))
    return out


def level(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["high"]:
        return "high"
    if score >= thresholds["medium"]:
        return "medium"
    return "low"


async def score_upcoming(
    db: AsyncSession,
    cipher: FieldCipher,
    directory: Path,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score booked and confirmed appointments in the next seven days and store the scores."""
    moment = now or datetime.now(UTC)
    row = await active_model(db)
    if row is None:
        return {"scored": 0, "skipped": "no model registered"}
    bundle = await load_bundle_async(row, directory)
    raw = await load_raw(db)
    if raw.empty:
        return {"scored": 0, "skipped": "no appointments"}
    features = build_features(raw, cipher, tz, now=pd.Timestamp(moment))
    window_end = pd.Timestamp(moment + timedelta(days=SCORING_DAYS))
    due = features[
        features["status"].isin(["booked", "confirmed"])
        & (features["start"] >= pd.Timestamp(moment))
        & (features["start"] < window_end)
    ]
    scored = score_frame(bundle, due)
    for s in scored:
        statement = insert(AppointmentRisk).values(
            appointment_id=s.appointment_id, score=round(s.score, 4), drivers=s.drivers,
            model_version=row.version, scored_at=moment,
        )  # fmt: skip
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[AppointmentRisk.appointment_id],
                set_={
                    "score": statement.excluded.score,
                    "drivers": statement.excluded.drivers,
                    "model_version": statement.excluded.model_version,
                    "scored_at": statement.excluded.scored_at,
                },
            )
        )
    # Scores of appointments that are no longer upcoming (cancelled, done) are dropped.
    await db.execute(
        text(
            "DELETE FROM appointment_risk r USING appointments a WHERE a.id = r.appointment_id "
            "AND (a.status NOT IN ('booked', 'confirmed') OR lower(a.slot) < :now)"
        ),
        {"now": moment},
    )
    await db.commit()
    return {"scored": len(scored), "model_version": row.version}
