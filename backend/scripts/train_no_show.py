"""Train the no show model on the appointments in the database and register it.

    python -m scripts.train_no_show

The first 18 months of finished visits train the model and the later visits test it, so the
reported figures describe how it would have done on appointments it had never seen. The
model file goes to MODEL_DIR and a row in ``model_registry`` records its version, checksum,
metrics and features. The newest model becomes the active one.
"""

import asyncio
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from app.analytics.noshow.features import load_raw
from app.analytics.noshow.model import ModelError, register, train
from app.core.config import Settings, get_settings
from app.core.crypto import FieldCipher
from app.db.session import create_engine, create_session_factory


async def run(settings: Settings) -> dict[str, object]:
    engine = create_engine(settings)
    cipher = FieldCipher.from_settings(
        settings.field_encryption_key, settings.field_encryption_old_keys, settings.jwt_secret
    )
    try:
        factory = create_session_factory(engine)
        async with factory() as db:
            raw = await load_raw(db)
            result = await asyncio.to_thread(train, raw, cipher, ZoneInfo(settings.clinic_tz))
            row = await register(db, result, Path(settings.model_dir))
        return {
            "version": row.version,
            "path": row.path,
            "train_rows": row.train_rows,
            "test_rows": row.test_rows,
            **result.metrics,
        }
    finally:
        await engine.dispose()


def main() -> int:
    try:
        report = asyncio.run(run(get_settings()))
    except ModelError as error:
        print(f"Could not train the model: {error}", file=sys.stderr)
        return 1
    calibration = report.pop("calibration")
    print(json.dumps(report, indent=2, default=str))
    print("\nCalibration (predicted against observed, equal sized groups):")
    for row in calibration:  # type: ignore[attr-defined]
        print(
            f"  predicted {row['mean_predicted']:.3f}  observed {row['observed']:.3f}  n={row['count']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
