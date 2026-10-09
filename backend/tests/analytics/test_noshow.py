"""The no show model: features free of leakage, an honest time split, registry, and scoring."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.analytics.noshow import model as noshow
from app.analytics.noshow.features import (
    CATEGORICAL,
    FEATURES,
    build_features,
    load_raw,
)
from app.core.crypto import FieldCipher
from app.db.enums import UserRole
from tests.analytics.conftest import AS_OF, DATABASE, NOW, analytics_settings
from tests.analytics.helpers import Api
from tests.auth.conftest import Ctx, unique_email
from tests.db.conftest import sqlalchemy_url

TZ = ZoneInfo("America/New_York")
OUTCOME_COLUMNS = {"status", "late_cancel", "target", "cancelled_at"}


def cipher() -> FieldCipher:
    s = analytics_settings()
    return FieldCipher.from_settings(
        s.field_encryption_key, s.field_encryption_old_keys, s.jwt_secret
    )


@pytest.fixture(scope="session")
def raw(seeded_database: str) -> pd.DataFrame:
    async def run() -> pd.DataFrame:
        engine = create_async_engine(sqlalchemy_url(DATABASE), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as db:
                return await load_raw(db)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture(scope="session")
def trained(raw: pd.DataFrame) -> noshow.TrainResult:
    return noshow.train(raw, cipher(), TZ, version="test")


@pytest.fixture
async def clean_models(ctx: Ctx) -> AsyncIterator[None]:
    yield
    await ctx.execute("DELETE FROM appointment_risk")
    await ctx.execute("DELETE FROM model_registry")


@pytest.fixture
def frame(raw: pd.DataFrame) -> pd.DataFrame:
    return build_features(raw, cipher(), TZ)


# --- how it was trained ---------------------------------------------------------------------------------------------


def test_training_uses_the_first_18_months_and_tests_on_the_rest(
    trained: noshow.TrainResult, raw: pd.DataFrame
) -> None:
    first = raw[raw["status"].isin(["completed", "no_show"])]["start"].min()
    cutoff = noshow.add_months(first, 18)
    train_end = datetime.fromisoformat(trained.metrics["train_period"][1])
    test_start = datetime.fromisoformat(trained.metrics["test_period"][0])
    assert pd.Timestamp(train_end) < cutoff <= pd.Timestamp(test_start)
    assert trained.train_rows > trained.test_rows > 100
    assert trained.train_rows + trained.test_rows == int(
        raw["status"].isin(["completed", "no_show"]).sum()
    )


def test_the_model_ranks_risk_well_on_appointments_it_never_saw(
    trained: noshow.TrainResult,
) -> None:
    metrics = trained.metrics
    assert 0.62 <= metrics["auc"] <= 0.90, metrics["auc"]
    assert metrics["precision_top_decile"] >= 1.8 * metrics["base_rate"]
    assert metrics["lift_top_decile"] >= 1.8
    assert 0.07 <= metrics["base_rate"] <= 0.14


def test_scores_are_calibrated(trained: noshow.TrainResult) -> None:
    metrics = trained.metrics
    assert metrics["expected_calibration_error"] < 0.05
    table = metrics["calibration"]
    assert len(table) == 10 and sum(row["count"] for row in table) == trained.test_rows
    assert [r["mean_predicted"] for r in table] == sorted(r["mean_predicted"] for r in table)
    assert table[-1]["observed"] > table[0]["observed"]  # higher scores really are riskier


def test_the_features_are_known_at_booking_time_and_include_no_outcomes() -> None:
    assert set(FEATURES).isdisjoint(OUTCOME_COLUMNS)
    expected = {"lead_days", "weekday", "hour", "age_band", "is_new", "prev_no_shows", "prev_no_show_rate", "prev_late_cancels", "service_category", "reminder_confirmed", "has_insurance"}  # fmt: skip
    assert set(FEATURES) == expected and set(CATEGORICAL) <= expected


def test_lead_time_matters_most_as_the_plan_expects(trained: noshow.TrainResult) -> None:
    importance = trained.metrics["feature_importance"]
    assert next(iter(importance)) == "lead_days"
    assert abs(sum(importance.values()) - 1.0) < 0.01


# --- leakage ---------------------------------------------------------------------------------------------------------------


def test_features_do_not_change_when_later_outcomes_change(
    raw: pd.DataFrame, frame: pd.DataFrame
) -> None:
    """Rewrite what happened after an appointment was booked. Its features must stay the same."""
    multi = frame.groupby("patient_id").size()
    patient = multi[multi >= 6].index[0]
    rows = frame[frame["patient_id"] == patient].sort_values("start")
    target = rows.iloc[len(rows) // 2]
    altered = raw.copy()
    mask = (altered["patient_id"] == patient) & (altered["start"] >= target["created_at"])
    altered.loc[mask, "status"] = "no_show"
    altered.loc[mask, "late_cancel"] = True
    again = build_features(altered, cipher(), TZ)
    before = frame[frame["id"] == target["id"]][FEATURES].reset_index(drop=True)
    after = again[again["id"] == target["id"]][FEATURES].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


def test_earlier_visits_count_only_when_they_happened_before_booking(frame: pd.DataFrame) -> None:
    for _patient, rows in list(frame.groupby("patient_id"))[:150]:
        for _, row in rows.iterrows():
            earlier = rows[(rows["start"] < row["created_at"])]
            assert row["prev_no_shows"] == (earlier["status"] == "no_show").sum()
            attended = earlier["status"].isin(["completed", "no_show"]).sum()
            expected_rate = (earlier["status"] == "no_show").sum() / attended if attended else 0.0
            assert abs(row["prev_no_show_rate"] - expected_rate) < 1e-9
            assert (
                row["prev_late_cancels"]
                == ((earlier["status"] == "cancelled") & earlier["late_cancel"]).sum()
            )


def test_confirmation_counts_only_when_made_a_day_before_the_visit(frame: pd.DataFrame) -> None:
    confirmed = frame[frame["reminder_confirmed"] == 1]
    assert (confirmed["confirmed_at"] <= confirmed["start"] - pd.Timedelta(hours=24)).all()
    late = frame[
        frame["confirmed_at"].notna()
        & (frame["confirmed_at"] > frame["start"] - pd.Timedelta(hours=24))
    ]
    assert len(late) > 0 and (late["reminder_confirmed"] == 0).all()
    assert 0.3 < frame["reminder_confirmed"].mean() < 0.9


def test_age_bands_come_from_the_encrypted_birth_date(frame: pd.DataFrame) -> None:
    assert set(frame["age_band"]) <= {"0-17", "18-29", "30-44", "45-64", "65+", "unknown"}
    assert (frame["age_band"] == "unknown").sum() == 0
    assert frame["age_band"].nunique() == 5


def test_a_missing_birth_date_means_an_unknown_age_not_an_error(raw: pd.DataFrame) -> None:
    """pandas hands a missing value over as NaN, which is truthy and has no text to decrypt."""
    gap = raw.copy()
    patients = gap["patient_id"].drop_duplicates().iloc[:5]
    gap["dob_enc"] = gap["dob_enc"].astype(object)
    gap.loc[gap["patient_id"].isin(patients), "dob_enc"] = float("nan")
    result = build_features(gap, cipher(), TZ)
    assert (result.loc[result["patient_id"].isin(patients), "age_band"] == "unknown").all()
    assert (result.loc[~result["patient_id"].isin(patients), "age_band"] != "unknown").all()


def test_new_patients_have_no_completed_visit_and_a_recent_record(frame: pd.DataFrame) -> None:
    new = frame[frame["is_new"] == 1]
    assert len(new) > 0
    assert ((new["created_at"] - new["patient_created"]).dt.days < 90).all()
    for _, row in new.head(200).iterrows():
        earlier = frame[
            (frame["patient_id"] == row["patient_id"]) & (frame["start"] < row["created_at"])
        ]
        assert not (earlier["status"] == "completed").any()  # a new patient has never been treated


# --- registry and files ---------------------------------------------------------------------------------------------------------


async def test_a_trained_model_is_registered_with_its_metrics(
    ctx: Ctx, trained: noshow.TrainResult, tmp_path: Path, clean_models: None
) -> None:
    async with ctx.session_factory() as db:
        row = await noshow.register(db, trained, tmp_path)
        assert row.is_active and row.algorithm == "lightgbm" and row.features == FEATURES
        assert row.metrics["auc"] == trained.metrics["auc"] and row.train_rows == trained.train_rows
        assert (tmp_path / row.path).is_file() and len(row.sha256) == 64
        active = await noshow.active_model(db)
        assert active is not None and active.id == row.id


async def test_a_newer_model_replaces_the_active_one(
    ctx: Ctx, trained: noshow.TrainResult, tmp_path: Path, clean_models: None
) -> None:
    newer = noshow.TrainResult(
        "newer",
        trained.metrics,
        trained.bundle,
        trained.train_rows,
        trained.test_rows,
        trained.data_through,
    )
    async with ctx.session_factory() as db:
        first = await noshow.register(db, trained, tmp_path)
        second = await noshow.register(db, newer, tmp_path)
        rows = await ctx.fetch("SELECT version, is_active FROM model_registry ORDER BY version")
        assert rows == [("newer", True), ("test", False)]
        active = await noshow.active_model(db)
        assert active is not None and active.id == second.id != first.id


async def test_a_changed_or_missing_model_file_is_refused(
    ctx: Ctx, trained: noshow.TrainResult, tmp_path: Path, clean_models: None
) -> None:
    async with ctx.session_factory() as db:
        row = await noshow.register(db, trained, tmp_path)
    assert noshow.load_bundle(row, tmp_path)["features"] == FEATURES
    path = tmp_path / row.path
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(noshow.ModelError, match="checksum"):
        noshow.load_bundle(row, tmp_path)
    path.unlink()
    with pytest.raises(noshow.ModelError, match="missing"):
        noshow.load_bundle(row, tmp_path)


def test_too_little_history_is_reported_clearly(raw: pd.DataFrame) -> None:
    with pytest.raises(noshow.ModelError, match="finished visits"):
        noshow.train(raw.head(50), cipher(), TZ)
    short = raw[raw["start"] < raw["start"].min() + pd.Timedelta(days=200)]
    with pytest.raises(noshow.ModelError):
        noshow.train(short, cipher(), TZ)


# --- scoring ---------------------------------------------------------------------------------------------------------------------------


def test_scores_are_probabilities_with_at_most_three_reasons(
    trained: noshow.TrainResult, frame: pd.DataFrame
) -> None:
    upcoming = frame[frame["status"].isin(["booked", "confirmed"])].head(60)
    scored = noshow.score_frame(trained.bundle, upcoming)
    assert len(scored) == len(upcoming) > 0
    assert all(0 <= s.score <= 1 for s in scored)
    for s in scored:
        assert len(s.drivers) <= 3
        assert all(d["contribution"] > 0 and d["label"] for d in s.drivers)
        assert [d["contribution"] for d in s.drivers] == sorted(
            (d["contribution"] for d in s.drivers), reverse=True
        )
    assert noshow.score_frame(trained.bundle, upcoming.head(0)) == []


def test_the_drivers_name_what_raises_the_risk(
    trained: noshow.TrainResult, frame: pd.DataFrame
) -> None:
    risky = frame[(frame["lead_days"] > 40) & (frame["reminder_confirmed"] == 0)].head(25)
    scored = noshow.score_frame(trained.bundle, risky)
    features = {d["feature"] for s in scored for d in s.drivers}
    assert "lead_days" in features
    labels = [d["label"] for s in scored for d in s.drivers if d["feature"] == "lead_days"]
    assert all(label.startswith("Booked ") and label.endswith(" days ahead") for label in labels)
    safe = frame[(frame["lead_days"] < 2) & (frame["reminder_confirmed"] == 1)].head(25)

    def average(xs: list[noshow.Scored]) -> float:
        return sum(s.score for s in xs) / len(xs)

    assert average(scored) > 2 * average(noshow.score_frame(trained.bundle, safe))


def test_levels_follow_the_stored_thresholds() -> None:
    thresholds = {"medium": 0.12, "high": 0.2}
    assert [noshow.level(s, thresholds) for s in (0.05, 0.12, 0.19, 0.2, 0.6)] == [
        "low",
        "medium",
        "medium",
        "high",
        "high",
    ]


async def _register_and_score(
    ctx: Ctx, trained: noshow.TrainResult, directory: Path
) -> dict[str, Any]:
    async with ctx.session_factory() as db:
        await noshow.register(db, trained, directory)
        return await noshow.score_upcoming(db, cipher(), directory, TZ, now=NOW)


async def test_scoring_stores_a_score_for_each_upcoming_appointment(
    ctx: Ctx, trained: noshow.TrainResult, tmp_path: Path, clean_models: None
) -> None:
    result = await _register_and_score(ctx, trained, tmp_path)
    due = await ctx.fetch(
        """SELECT count(*) FROM appointments WHERE status IN ('booked', 'confirmed')
           AND lower(slot) >= :a AND lower(slot) < :b""",
        a=NOW, b=NOW + timedelta(days=7),
    )  # fmt: skip
    assert due[0][0] > 5 and result["scored"] == due[0][0]
    stored = await ctx.fetch(
        "SELECT count(*), min(score), max(score), min(model_version) FROM appointment_risk"
    )
    assert (
        stored[0][0] == due[0][0]
        and 0 <= stored[0][1] <= stored[0][2] <= 1
        and stored[0][3] == "test"
    )
    async with ctx.session_factory() as db:
        again = await noshow.score_upcoming(db, cipher(), tmp_path, TZ, now=NOW)
    assert again["scored"] == result["scored"]
    assert (await ctx.fetch("SELECT count(*) FROM appointment_risk"))[0][0] == due[0][
        0
    ]  # updated, not duplicated


async def test_a_cancelled_appointment_loses_its_score(
    ctx: Ctx, trained: noshow.TrainResult, tmp_path: Path, clean_models: None
) -> None:
    await _register_and_score(ctx, trained, tmp_path)
    victim = (await ctx.fetch("SELECT appointment_id::text FROM appointment_risk LIMIT 1"))[0][0]
    await ctx.execute("UPDATE appointments SET status = 'cancelled' WHERE id = :i", i=victim)
    try:
        async with ctx.session_factory() as db:
            await noshow.score_upcoming(db, cipher(), tmp_path, TZ, now=NOW)
        assert (
            await ctx.fetch(
                "SELECT count(*) FROM appointment_risk WHERE appointment_id = :i", i=victim
            )
        )[0][0] == 0
    finally:
        await ctx.execute("UPDATE appointments SET status = 'booked' WHERE id = :i", i=victim)


async def test_scoring_without_a_model_does_nothing(
    ctx: Ctx, clean_models: None, tmp_path: Path
) -> None:
    async with ctx.session_factory() as db:
        result = await noshow.score_upcoming(db, cipher(), tmp_path, TZ, now=NOW)
    assert result == {"scored": 0, "skipped": "no model registered"}


# --- the endpoint ------------------------------------------------------------------------------------------------------------------------


async def test_the_endpoint_says_so_when_no_model_exists(admin: Api, clean_models: None) -> None:
    body = await admin.get("/no-show/upcoming-risk")
    assert body["rows"] == [] and body["model_version"] is None
    assert "scripts/train_no_show.py" in body["note"]


async def test_the_endpoint_lists_next_weeks_appointments_riskiest_first(
    ctx: Ctx, admin: Api, trained: noshow.TrainResult, clean_models: None
) -> None:
    async with ctx.session_factory() as db:
        await noshow.register(db, trained, Path(ctx.settings.model_dir))
    body = await admin.get("/no-show/upcoming-risk")
    assert body["model_version"] == "test" and body["model_auc"] == trained.metrics["auc"]
    rows = body["rows"]
    assert len(rows) > 5
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    window_start = datetime.combine(AS_OF, datetime.min.time(), tzinfo=UTC)
    for row in rows:
        start = datetime.fromisoformat(row["start"])
        assert window_start <= start < window_start + timedelta(days=9)
        assert row["status"] in ("booked", "confirmed") and len(row["drivers"]) <= 3
        assert row["patient_name"] and row["service_name"] and row["dentist_name"]
        thresholds = trained.metrics["thresholds"]
        expected = (
            "high"
            if row["score"] >= thresholds["high"]
            else "medium"
            if row["score"] >= thresholds["medium"]
            else "low"
        )
        assert row["level"] == expected
    assert {r["level"] for r in rows} >= {"low"}
    audit = await ctx.fetch("SELECT count(*) FROM audit_logs WHERE action = 'analytics.risk_view'")
    assert audit[0][0] >= 1


async def test_a_dentist_sees_only_their_own_risk_list(
    ctx: Ctx, trained: noshow.TrainResult, clean_models: None
) -> None:
    async with ctx.session_factory() as db:
        await noshow.register(db, trained, Path(ctx.settings.model_dir))
    dentist_id = (
        await ctx.fetch(
            "SELECT dentist_id::text FROM appointments WHERE status = 'booked' AND lower(slot) > :n GROUP BY 1 ORDER BY count(*) DESC LIMIT 1",
            n=NOW,
        )
    )[0][0]
    email = unique_email("dentist")
    user = await ctx.create_user(email, UserRole.DENTIST, with_patient=False)
    await ctx.execute("UPDATE dentists SET user_id = NULL WHERE user_id = :u", u=str(user.id))
    await ctx.execute("DELETE FROM dentists WHERE full_name LIKE 'Dr. Person'")
    await ctx.execute(
        "UPDATE dentists SET user_id = :u WHERE id = :d", u=str(user.id), d=dentist_id
    )
    api = Api(ctx, ctx.auth(await ctx.access_token(email)))
    body = await api.get("/no-show/upcoming-risk")
    assert body["rows"] and {r["dentist_id"] for r in body["rows"]} == {dentist_id}
    await ctx.execute("UPDATE dentists SET user_id = NULL WHERE id = :d", d=dentist_id)


def test_the_module_never_trains_on_the_future(
    raw: pd.DataFrame, trained: noshow.TrainResult
) -> None:
    upcoming = raw[raw["status"].isin(["booked", "confirmed"])]
    assert len(upcoming) > 0
    assert pd.Timestamp(trained.data_through) <= pd.Timestamp(NOW)
    iterator: Iterator[None] = iter(())
    del iterator
