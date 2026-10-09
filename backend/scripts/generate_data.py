"""A reproducible synthetic dental clinic dataset: 24 months of patients, visits and billing.

Real patient data is not public, so this module simulates a clinic. Everything is driven by one
random seed, so the same inputs always produce the same dataset. Rows are plain dictionaries
that match the table columns, which ``scripts/seed.py`` inserts. The simulation follows the
rates and patterns described in the project plan (section 4.1):

* growth of 6 to 10 percent a year, a 4 percent price increase from month 13;
* a strong fourth quarter, slow July and August, a quiet last week of December;
* busiest Tuesday to Thursday, a light Friday afternoon, a half day Saturday, closed Sunday;
* about 82 percent of scheduled visits completed, 8 percent cancelled, 10 percent no shows;
* no show risk that rises with lead time, young adult age, earlier no shows, no confirmation,
  early morning and late Friday slots;
* a new dentist in month 10 who ramps up, one dentist who works fewer days from month 18;
* 58 percent of patients insured (insurers pay 14 to 45 days after the visit), 34 percent self
  pay at the visit and 8 percent on a payment plan, which produces realistic receivables.

The reference no show dataset named in the plan could not be used here (it needs a Kaggle
account), so the no show probabilities come from the plan's stated rates and published dental
no show ranges rather than from a fit to that file.
"""

import bisect
import math
import random
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from faker import Faker

DATASET_VERSION = 1
BUFFER_MINUTES = 10
GRID_MINUTES = 15
MAX_SEARCH_DAYS = 28
FUTURE_DAYS = 30
ARRIVAL_GROWTH = (
    1.12  # yearly growth of new patient arrivals; with churn it gives 6 to 10 percent volume growth
)

# --- catalog ---------------------------------------------------------------------------------------------

# code, name, category, minutes, price, description
SERVICES: list[tuple[str, str, str, int, str, str]] = [
    (
        "SV01",
        "Comprehensive Exam and X-rays",
        "preventive",
        60,
        "145",
        "A full examination of teeth, gums and bite with digital x-rays for new patients.",
    ),
    (
        "SV02",
        "Routine Exam and Cleaning",
        "preventive",
        45,
        "120",
        "A checkup and professional cleaning to keep teeth and gums healthy.",
    ),
    (
        "SV03",
        "Deep Cleaning (per quadrant)",
        "preventive",
        60,
        "220",
        "Scaling and root planing below the gum line to treat early gum disease.",
    ),
    (
        "SV04",
        "Tooth Colored Filling",
        "restorative",
        45,
        "210",
        "A natural looking filling that repairs a cavity and restores the tooth.",
    ),
    (
        "SV05",
        "Porcelain Crown",
        "restorative",
        90,
        "1150",
        "A custom porcelain cap that protects and restores a damaged tooth.",
    ),
    (
        "SV06",
        "Root Canal Therapy",
        "restorative",
        90,
        "980",
        "Treatment that removes infected tissue inside a tooth and seals it.",
    ),
    (
        "SV07",
        "Simple Extraction",
        "surgical",
        45,
        "240",
        "Removal of a tooth that is visible above the gum line.",
    ),
    (
        "SV08",
        "Surgical Extraction",
        "surgical",
        60,
        "480",
        "Removal of an impacted or broken tooth that needs a surgical approach.",
    ),
    (
        "SV09",
        "Dental Implant Consultation",
        "surgical",
        45,
        "90",
        "An assessment and planning visit for replacing missing teeth with implants.",
    ),
    (
        "SV10",
        "Dental Implant Placement",
        "surgical",
        120,
        "3200",
        "Surgical placement of a dental implant to replace a missing tooth.",
    ),
    (
        "SV11",
        "Professional Teeth Whitening",
        "cosmetic",
        60,
        "420",
        "In office whitening that brightens teeth in a single visit.",
    ),
    (
        "SV12",
        "Orthodontic Consultation",
        "orthodontic",
        45,
        "75",
        "An assessment of alignment and bite with a discussion of treatment options.",
    ),
    (
        "SV13",
        "Clear Aligner Treatment (plan fee)",
        "orthodontic",
        30,
        "4800",
        "A planned course of clear aligners to straighten teeth.",
    ),
    (
        "SV14",
        "Emergency Visit",
        "emergency",
        30,
        "160",
        "A prompt visit for severe pain, a broken tooth or another urgent problem.",
    ),
]
SERVICE_BY_CODE = {s[0]: s for s in SERVICES}

# name, specialty, services offered, weekdays worked (0 = Monday), colour
DENTISTS: list[tuple[str, str, list[str], list[int], str]] = [
    (
        "Dr. Priya Raman",
        "general",
        ["SV01", "SV02", "SV03", "SV04", "SV05", "SV07", "SV09", "SV11", "SV14"],
        [0, 1, 2, 3, 4, 5],
        "#13A3A1",
    ),
    (
        "Dr. Marcus Lindqvist",
        "orthodontics",
        ["SV01", "SV02", "SV12", "SV13"],
        [0, 1, 2, 3, 4, 5],
        "#3B82F6",
    ),
    (
        "Dr. Hannah Okafor",
        "pediatric",
        ["SV01", "SV02", "SV04", "SV07", "SV14"],
        [0, 1, 2, 3, 4, 5],
        "#F59E0B",
    ),
    (
        "Dr. Daniel Reyes",
        "endodontics",
        ["SV01", "SV02", "SV05", "SV06", "SV14"],
        [0, 1, 2, 3, 4],
        "#8B5CF6",
    ),
    (
        "Dr. Sofia Marchetti",
        "periodontics",
        ["SV01", "SV02", "SV03", "SV04", "SV07", "SV08"],
        [0, 1, 2, 3, 4, 5],
        "#EC4899",
    ),
    (
        "Dr. Theodore Whitfield",
        "oral surgery",
        ["SV01", "SV07", "SV08", "SV09", "SV10", "SV14"],
        [0, 1, 2, 3, 4],
        "#EF4444",
    ),
    ("Dr. Amara Nwosu", "cosmetic", ["SV02", "SV04", "SV05", "SV11"], [0, 1, 2, 3, 4], "#10B981"),
]
NEW_DENTIST = "Dr. Amara Nwosu"  # joins in month 10 and ramps up
REDUCED_DENTIST = "Dr. Daniel Reyes"  # stops working Fridays from month 18
NEW_DENTIST_MONTH = 10
REDUCED_FROM_MONTH = 18

INSURERS = [
    ("Northwind Dental Plan", ["ppo", "hmo"]),
    ("Harborlight Health", ["ppo"]),
    ("Summit Benefits", ["ppo", "indemnity"]),
    ("Cedar Valley Mutual", ["hmo"]),
    ("Brightpath Insurance", ["ppo", "hmo"]),
    ("Lakeshore Dental Alliance", ["ppo"]),
]
COVERAGE = {"preventive": 0.90, "restorative": 0.65, "surgical": 0.50, "cosmetic": 0.0,
            "orthodontic": 0.50, "emergency": 0.70}  # fmt: skip
COVERAGE_BY_CODE = {"SV03": 0.70, "SV04": 0.80}

# Treatment visits other than cleanings, weighted by the service mix in the plan.
TREATMENTS: list[tuple[str, float]] = [
    ("SV04", 18), ("SV05", 8), ("SV11", 6), ("SV12", 6), ("SV06", 4), ("SV07", 3),
    ("SV08", 1), ("SV09", 2), ("SV10", 1), ("SV13", 1),
]  # fmt: skip

MONTH_DEMAND = {1: 0.98, 2: 0.97, 3: 1.0, 4: 1.0, 5: 1.0, 6: 0.98, 7: 0.82, 8: 0.82, 9: 1.0,
                10: 1.06, 11: 1.14, 12: 1.16}  # fmt: skip
WEEKDAY_WEIGHT = {0: 0.95, 1: 1.15, 2: 1.15, 3: 1.10, 4: 0.75, 5: 0.45}
HOUR_WEIGHT = {
    8: 0.7,
    9: 1.15,
    10: 1.2,
    11: 1.1,
    12: 0.8,
    13: 0.9,
    14: 1.1,
    15: 1.1,
    16: 0.9,
    17: 0.55,
}
AGE_BANDS = [(0, 17, 0.17), (18, 29, 0.17), (30, 44, 0.25), (45, 64, 0.26), (65, 88, 0.15)]


# --- configuration and output --------------------------------------------------------------------------------


@dataclass
class GenConfig:
    now: datetime  # the moment of the run; history ends the day before
    seed: int = 20260101
    patients: int = 4500
    existing_share: float = 0.40  # patients already in the practice when the history starts
    months: int = 24
    clinic_tz: str = "America/New_York"
    target_no_show: float = 0.078
    target_cancel: float = 0.105
    insured_share: float = 0.58
    plan_share_of_uninsured: float = 8 / 42
    treatment_chance: float = 0.62
    regular_share: float = 0.60
    regular_return: float = 0.92
    irregular_return: float = 0.30
    emergency_share: float = 0.04
    price_increase: float = 0.04
    future_days: int = FUTURE_DAYS

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_tz)

    @property
    def end_date(self) -> date:
        return self.now.astimezone(self.tz).date() - timedelta(days=1)

    @property
    def start_date(self) -> date:
        end = self.end_date
        index = end.year * 12 + end.month - 1 - self.months
        return date(index // 12, index % 12 + 1, 1)


@dataclass
class Dataset:
    config: GenConfig
    insurance_providers: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    dentists: list[dict[str, Any]] = field(default_factory=list)
    dentist_services: list[dict[str, Any]] = field(default_factory=list)
    dentist_schedules: list[dict[str, Any]] = field(default_factory=list)
    schedule_exceptions: list[dict[str, Any]] = field(default_factory=list)
    patients: list[dict[str, Any]] = field(default_factory=list)
    appointments: list[dict[str, Any]] = field(default_factory=list)
    status_history: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    invoice_items: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    requested: int = 0
    unplaced: int = 0


@dataclass
class _Patient:
    id: uuid.UUID
    age_at_start: float
    insured: bool
    provider: uuid.UUID | None
    plan: bool
    regular: bool
    frailty: float
    created_at: datetime
    existing: bool
    history: list[tuple[datetime, str, bool]] = field(default_factory=list)  # start, status, late
    busy_days: set[date] = field(default_factory=set)


@dataclass
class _Request:
    patient: _Patient
    day: date
    code: str
    kind: str  # first, recall, treatment, emergency


def _money(value: Decimal | float) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _month_index(day: date, start: date) -> int:
    return (day.year - start.year) * 12 + day.month - start.month


def _local(day: date, minute: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=tz) + timedelta(minutes=minute)


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _weighted(rng: random.Random, items: list[tuple[Any, float]]) -> Any:
    total = sum(w for _, w in items)
    pick = rng.random() * total
    running = 0.0
    for item, weight in items:
        running += weight
        if pick <= running:
            return item
    return items[-1][0]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# --- the generator -------------------------------------------------------------------------------------------


class Generator:
    def __init__(self, config: GenConfig, encrypt: Callable[[str, str], str]) -> None:
        self.cfg = config
        self.encrypt = encrypt
        self.rng = random.Random(config.seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(config.seed)
        self.tz = config.tz
        self.start = config.start_date
        self.end = config.end_date
        self.horizon = self.end + timedelta(days=1 + config.future_days)
        self.data = Dataset(config)
        self._busy: dict[tuple[uuid.UUID, date], list[tuple[int, int]]] = defaultdict(list)
        self._days_off: set[tuple[uuid.UUID, date]] = set()
        self._holidays: set[date] = set()
        self._dentist: dict[str, dict[str, Any]] = {}
        self._service_ids: dict[str, uuid.UUID] = {}
        self._providers: list[uuid.UUID] = []

    def uid(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    # --- reference data ---

    def build_reference(self) -> None:
        for name, plans in INSURERS:
            pid = self.uid()
            self._providers.append(pid)
            self.data.insurance_providers.append({"id": pid, "name": name, "plan_types": plans})
        for order, (code, name, category, minutes, price, description) in enumerate(SERVICES, 1):
            sid = self.uid()
            self._service_ids[code] = sid
            self.data.services.append(
                {"id": sid, "code": code, "name": name, "category": category,
                 "description": description, "duration_min": minutes,
                 "base_price": Decimal(price), "is_active": True, "display_order": order}
            )  # fmt: skip
        self._holidays = self._holiday_dates()
        for index, (name, specialty, codes, weekdays, color) in enumerate(DENTISTS, 1):
            did = self.uid()
            joins = name == NEW_DENTIST
            created = _utc(
                datetime.combine(self._add_months(self.start, NEW_DENTIST_MONTH if joins else 0),
                                 time(7, 0), tzinfo=self.tz)
            ) - timedelta(days=0 if joins else 400)  # fmt: skip
            self._dentist[name] = {"id": did, "name": name, "codes": codes, "weekdays": weekdays,
                                   "joins": joins, "created": created}  # fmt: skip
            self.data.dentists.append(
                {"id": did, "user_id": None, "full_name": name, "specialty": specialty,
                 "bio": f"{name} practices {specialty} dentistry at Meridian Dental Care.",
                 "photo_url": None, "license_no": f"NY-DDS-{410000 + index * 137}",
                 "is_active": True, "color": color, "created_at": created}
            )  # fmt: skip
            for code in codes:
                self.data.dentist_services.append(
                    {"dentist_id": did, "service_id": self._service_ids[code]}
                )
            for weekday in weekdays:
                saturday = weekday == 5
                self.data.dentist_schedules.append(
                    {"id": self.uid(), "dentist_id": did, "weekday": weekday,
                     "start_time": time(9, 0) if saturday else time(8, 0),
                     "end_time": time(14, 0) if saturday else time(18, 0),
                     "break_start": None if saturday else time(12, 30),
                     "break_end": None if saturday else time(13, 30)}
                )  # fmt: skip
            self._add_exceptions(name, did, weekdays)

    @staticmethod
    def _add_months(day: date, months: int) -> date:
        index = day.year * 12 + day.month - 1 + months
        return date(index // 12, index % 12 + 1, 1)

    def _holiday_dates(self) -> set[date]:
        days: set[date] = set()
        for year in range(self.start.year, self.horizon.year + 1):
            days.add(date(year, 1, 1))
            days.add(date(year, 7, 4))
            days.add(date(year, 12, 25))
            november = [date(year, 11, d) for d in range(1, 31) if date(year, 11, d).weekday() == 3]
            days.add(november[3])  # fourth Thursday
        return {d for d in days if self.start <= d <= self.horizon}

    def _add_exceptions(self, name: str, did: uuid.UUID, weekdays: list[int]) -> None:
        """Holidays for everyone, and the Fridays one dentist gave up from month 18."""
        days = set(self._holidays)
        if name == REDUCED_DENTIST:
            first = self._add_months(self.start, REDUCED_FROM_MONTH)
            day = first
            while day <= self.horizon:
                if day.weekday() == 4:
                    days.add(day)
                day += timedelta(days=1)
        for day in sorted(days):
            if day.weekday() not in weekdays:
                continue
            reason = "holiday" if day in self._holidays else "leave"
            self._days_off.add((did, day))
            self.data.schedule_exceptions.append(
                {"id": self.uid(), "dentist_id": did,
                 "starts_at": _utc(_local(day, 0, self.tz)),
                 "ends_at": _utc(_local(day + timedelta(days=1), 0, self.tz)),
                 "reason": reason, "note": None}
            )  # fmt: skip

    # --- patients ---

    def build_patients(self) -> list[_Patient]:
        cfg = self.cfg
        existing = int(cfg.patients * cfg.existing_share)
        out: list[_Patient] = []
        days = (self.end - self.start).days + 1
        weights = [ARRIVAL_GROWTH ** (d / 365.0) for d in range(days)]
        cumulative: list[float] = []
        running = 0.0
        for w in weights:
            running += w
            cumulative.append(running)
        for index in range(cfg.patients):
            is_existing = index < existing
            insured = self.rng.random() < cfg.insured_share
            plan = (not insured) and self.rng.random() < cfg.plan_share_of_uninsured
            band = _weighted(self.rng, [((lo, hi), w) for lo, hi, w in AGE_BANDS])
            age = self.rng.uniform(band[0], band[1] + 0.99)
            if is_existing:
                created = _utc(
                    datetime.combine(self.start, time(9, 0), tzinfo=self.tz)
                    - timedelta(days=self.rng.randint(30, 1800))
                )
                first_day = self.start + timedelta(days=self.rng.randint(0, 200))
            else:
                pick = self.rng.random() * cumulative[-1]
                offset = bisect.bisect_left(cumulative, pick)
                first_day = self.start + timedelta(days=min(offset, days - 1))
                created = _utc(
                    datetime.combine(first_day, time(9, 0), tzinfo=self.tz)
                    - timedelta(days=self.rng.uniform(0.05, 25))
                )
            patient = _Patient(
                id=self.uid(), age_at_start=age, insured=insured,
                provider=self.rng.choice(self._providers) if insured else None,
                plan=plan, regular=self.rng.random() < cfg.regular_share,
                frailty=self.rng.gauss(0, 0.55), created_at=created, existing=is_existing,
            )  # fmt: skip
            patient.first_day = first_day  # type: ignore[attr-defined]
            out.append(patient)
            self._add_patient_row(patient, index)
        return out

    def _add_patient_row(self, patient: _Patient, index: int) -> None:
        first = self.fake.first_name()
        last = self.fake.last_name()
        local = "".join(c for c in f"{first}.{last}".lower() if c.isalnum() or c == ".")
        email = f"{local}{index + 1}@example.com"
        born = self.start - timedelta(days=int(patient.age_at_start * 365.25))
        phone = f"(555) 010-{self.rng.randint(0, 9999):04d}"
        source = _weighted(
            self.rng, [("web", 40), ("walk_in", 28), ("referral", 22), ("chatbot", 10)]
        )
        self.data.patients.append(
            {"id": patient.id, "user_id": None, "first_name": first, "last_name": last,
             "dob_enc": self.encrypt(born.isoformat(), "patients.dob"),
             "phone_enc": self.encrypt(phone, "patients.phone"), "email": email,
             "address_enc": None, "insurance_provider_id": patient.provider,
             "insurance_member_id_enc": self.encrypt(f"MBR{self.rng.randint(10**8, 10**9 - 1)}",
                                                     "patients.insurance_member_id")
             if patient.insured else None,
             "marketing_consent": self.rng.random() < 0.45, "source": source,
             "created_at": patient.created_at, "anonymized_at": None}
        )  # fmt: skip

    # --- visit requests ---

    def build_requests(self, patients: list[_Patient]) -> list[_Request]:
        cfg = self.cfg
        requests: list[_Request] = []
        for patient in patients:
            day: date = patient.first_day  # type: ignore[attr-defined]
            age = patient.age_at_start + (day - self.start).days / 365.25
            if patient.existing:
                code = _weighted(self.rng, [("SV02", 90), ("SV03", 7), ("SV01", 3)])
                kind = "recall"
            else:
                code = _weighted(
                    self.rng,
                    [
                        ("SV01", 84),
                        ("SV14", 6),
                        ("SV12", 4 if age < 45 else 0),
                        ("SV09", 3),
                        ("SV02", 3),
                    ],
                )
                kind = "first"
            requests.append(_Request(patient, day, code, kind))
            self._follow_ups(requests, patient, day, code, first=not patient.existing)
            cycle_day = day
            returns = cfg.regular_return if patient.regular else cfg.irregular_return
            while True:
                if self.rng.random() > returns:
                    break
                cycle_day = cycle_day + timedelta(days=int(self.rng.gauss(182, 22)))
                if cycle_day > self.horizon:
                    break
                recall = _weighted(self.rng, [("SV02", 92), ("SV03", 5), ("SV01", 3)])
                requests.append(_Request(patient, cycle_day, recall, "recall"))
                self._follow_ups(requests, patient, cycle_day, recall, first=False)
        total = len(requests)
        for _ in range(int(total * cfg.emergency_share / (1 - cfg.emergency_share))):
            patient = self.rng.choice(patients)
            span = (self.horizon - self.start).days
            day = self.start + timedelta(days=self.rng.randint(0, span))
            if day >= patient.created_at.astimezone(self.tz).date():
                requests.append(_Request(patient, day, "SV14", "emergency"))
        return requests

    def _follow_ups(
        self, out: list[_Request], patient: _Patient, day: date, code: str, *, first: bool
    ) -> None:
        if code not in ("SV01", "SV02", "SV03"):
            return
        chance = self.cfg.treatment_chance * (1.5 if first else 1.0)
        if self.rng.random() >= chance:
            return
        count = 1 + (self.rng.random() < 0.45) + (self.rng.random() < 0.15)
        when = day
        for _ in range(count):
            treatment = _weighted(self.rng, TREATMENTS)
            if treatment == "SV12" and patient.age_at_start > 55:
                treatment = "SV04"
            when = when + timedelta(days=self.rng.randint(7, 35))
            if when <= self.horizon:
                out.append(_Request(patient, when, treatment, "treatment"))
                if treatment == "SV09" and self.rng.random() < 0.45:
                    placement = when + timedelta(days=self.rng.randint(21, 60))
                    if placement <= self.horizon:
                        out.append(_Request(patient, placement, "SV10", "treatment"))
                if treatment == "SV12" and self.rng.random() < 0.40:
                    plan = when + timedelta(days=self.rng.randint(7, 21))
                    if plan <= self.horizon:
                        out.append(_Request(patient, plan, "SV13", "treatment"))

    def shape_dates(self, requests: list[_Request]) -> None:
        """Apply seasonality and the weekly pattern to the wanted dates."""
        for request in requests:
            day = request.day
            if request.kind != "emergency":
                demand = MONTH_DEMAND[day.month]
                if demand < 1 and self.rng.random() < (1 - demand) * 1.5:
                    day += timedelta(days=self.rng.randint(45, 110))  # summer visits slip to autumn
                elif day.month in (1, 2, 3) and self.rng.random() < 0.26:
                    pulled = day - timedelta(days=self.rng.randint(45, 100))
                    if pulled >= self.start:
                        day = pulled  # benefits that expire in December pull visits forward
                if day.month == 12 and day.day >= 24 and self.rng.random() < 0.7:
                    day = date(day.year + 1, 1, 1) + timedelta(days=self.rng.randint(1, 9))
            monday = day - timedelta(days=day.weekday())
            weekday = _weighted(self.rng, list(WEEKDAY_WEIGHT.items()))
            request.day = monday + timedelta(days=weekday)
            if request.day < self.start:
                request.day = self.start + timedelta(days=self.rng.randint(0, 20))

    # --- booking ---

    def _ramp(self, dentist: dict[str, Any], day: date) -> float:
        if not dentist["joins"]:
            return 1.0
        opened = self._add_months(self.start, NEW_DENTIST_MONTH)
        if day < opened:
            return 0.0
        weeks = (day - opened).days / 7
        return min(1.0, 0.15 + 0.85 * weeks / 12)

    def _free_starts(
        self, dentist: dict[str, Any], day: date, minutes: int
    ) -> list[tuple[int, float]]:
        weekday = day.weekday()
        if weekday not in dentist["weekdays"] or (dentist["id"], day) in self._days_off:
            return []
        saturday = weekday == 5
        open_min, close_min = (9 * 60, 14 * 60) if saturday else (8 * 60, 18 * 60)
        windows = (
            [(open_min, close_min)]
            if saturday
            else [(open_min, 12 * 60 + 30), (13 * 60 + 30, close_min)]
        )
        busy = self._busy[(dentist["id"], day)]
        options: list[tuple[int, float]] = []
        for lo, hi in windows:
            start = lo
            while start + minutes <= hi:
                end = start + minutes
                if all(end + BUFFER_MINUTES <= b0 or start >= b1 for b0, b1 in busy):
                    hour = start // 60
                    weight = HOUR_WEIGHT.get(hour, 0.8)
                    if weekday == 4 and hour >= 15:
                        weight *= 0.45
                    options.append((start, weight))
                start += GRID_MINUTES
        return options

    def book(self, requests: list[_Request]) -> list[dict[str, Any]]:
        """Give each request a dentist and a time, the nearest that fits. Returns bookings."""
        bookings: list[dict[str, Any]] = []
        requests.sort(key=lambda r: (r.day, str(r.patient.id)))
        for request in requests:
            code = request.code
            minutes = SERVICE_BY_CODE[code][3]
            patient = request.patient
            age = patient.age_at_start + (request.day - self.start).days / 365.25
            candidates = [
                d for d in self._dentist.values()
                if code in d["codes"] and (d["specialty_ok"](age) if "specialty_ok" in d else True)
            ]  # fmt: skip
            placed = False
            day = request.day
            for _ in range(MAX_SEARCH_DAYS):
                if day > self.horizon:
                    break
                if day.weekday() < 6 and day not in patient.busy_days:
                    pool = [
                        (d, self._ramp(d, day) * (1.0 if d["joins"] is False else 1.0))
                        for d in candidates
                    ]
                    pool = [(d, w) for d, w in pool if w > 0]
                    order: list[dict[str, Any]] = []
                    remaining = list(pool)
                    while remaining:
                        pick = _weighted(self.rng, remaining)
                        order.append(pick)
                        remaining = [(d, w) for d, w in remaining if d is not pick]
                    for dentist in order:
                        options = self._free_starts(dentist, day, minutes)
                        if not options:
                            continue
                        start_minute = _weighted(self.rng, options)
                        self._busy[(dentist["id"], day)].append(
                            (start_minute, start_minute + minutes + BUFFER_MINUTES)
                        )
                        patient.busy_days.add(day)
                        bookings.append(
                            {
                                "request": request,
                                "dentist": dentist,
                                "day": day,
                                "minute": start_minute,
                            }
                        )
                        placed = True
                        break
                if placed:
                    break
                day += timedelta(days=1)
        return bookings

    # --- outcomes ---

    def lead_days(self, request: _Request) -> float:
        if request.kind == "emergency":
            return self.rng.uniform(0.0, 0.6)
        lead = math.exp(self.rng.gauss(math.log(6.0), 0.95))
        if request.kind == "first":
            lead *= 0.8
        return min(max(lead, 0.04), 75.0)

    def build_appointments(self, bookings: list[dict[str, Any]]) -> None:
        cfg = self.cfg
        now = cfg.now
        rows: list[dict[str, Any]] = []
        for b in bookings:
            request: _Request = b["request"]
            minutes = SERVICE_BY_CODE[request.code][3]
            start = _utc(_local(b["day"], b["minute"], self.tz))
            lead = self.lead_days(request)
            created = start - timedelta(days=lead)
            if created > now:
                continue  # not booked yet at the time of the run
            patient = request.patient
            if created < patient.created_at:
                created = max(patient.created_at, start - timedelta(days=lead))
                created = patient.created_at + timedelta(minutes=5) if created >= start else created
            rows.append({"b": b, "start": start, "end": start + timedelta(minutes=minutes),
                         "created": created, "lead": (start - created).total_seconds() / 86400})  # fmt: skip
        rows.sort(key=lambda r: r["start"])

        past = [r for r in rows if r["start"] <= now]
        cancelled_flags = {id(r): self.rng.random() < self._cancel_probability(r) for r in past}
        for row in rows:
            row["confirmed_early"] = self._confirmed_early(row)
        # First pass: outcomes in time order, so earlier no shows can influence later visits.
        draws = {id(r): self.rng.random() for r in rows}
        intercept = self._calibrate(rows, past, cancelled_flags)
        for row in rows:
            request = row["b"]["request"]
            patient = request.patient
            if row not in past:
                row["status"] = "confirmed" if row["confirmed_early"] else "booked"
                row["late_cancel"] = False
                continue
            if cancelled_flags[id(row)]:
                row["status"] = "cancelled"
                late = self.rng.random() < 0.30
                hours = (
                    self.rng.uniform(1, 23)
                    if late
                    else self.rng.uniform(25, 24 * min(row["lead"], 20) + 26)
                )
                row["cancelled_at"] = max(
                    row["start"] - timedelta(hours=hours), row["created"] + timedelta(minutes=30)
                )
                row["late_cancel"] = (row["start"] - row["cancelled_at"]) < timedelta(hours=24)
                row["cancel_reason"] = "Cancelled by patient"
                patient.history.append((row["start"], "cancelled", row["late_cancel"]))
                continue
            probability = _sigmoid(intercept + self._no_show_logit(row, patient))
            if draws[id(row)] < probability:
                row["status"] = "no_show"
            else:
                row["status"] = "completed"
            row["late_cancel"] = False
            patient.history.append((row["start"], row["status"], False))
        self._emit(rows)

    def _cancel_probability(self, row: dict[str, Any]) -> float:
        lead_effect = min(row["lead"], 30) / 30
        return float(min(0.30, self.cfg.target_cancel * (0.55 + 0.9 * lead_effect)))

    def _confirmed_early(self, row: dict[str, Any]) -> bool:
        patient = row["b"]["request"].patient
        if row["lead"] < 1.3:
            return False
        probability = _sigmoid(0.50 - 0.55 * patient.frailty + 0.10 * min(row["lead"], 6))
        return self.rng.random() < probability

    def _features(self, row: dict[str, Any], patient: _Patient) -> dict[str, float]:
        start_local = row["start"].astimezone(self.tz)
        age = (
            patient.age_at_start
            + (row["start"].astimezone(self.tz).date() - self.start).days / 365.25
        )
        prior = [h for h in patient.history if h[0] < row["created"]]
        no_shows = sum(1 for h in prior if h[1] == "no_show")
        late = sum(1 for h in prior if h[2])
        completed_before = sum(1 for h in prior if h[1] == "completed")
        is_new = completed_before == 0 and (row["created"] - patient.created_at) < timedelta(
            days=90
        )
        category = SERVICE_BY_CODE[row["b"]["request"].code][2]
        return {
            "lead": row["lead"], "age": age, "no_shows": float(no_shows), "late": float(late),
            "new": float(is_new), "hour": float(start_local.hour), "weekday": float(start_local.weekday()),
            "uninsured": float(not patient.insured), "confirmed": float(row["confirmed_early"]),
            "emergency": float(category == "emergency"), "surgical": float(category == "surgical"),
        }  # fmt: skip

    def _no_show_logit(self, row: dict[str, Any], patient: _Patient) -> float:
        f = self._features(row, patient)
        logit = 0.022 * min(f["lead"], 45.0)
        if f["age"] < 18:
            logit -= 0.2
        elif f["age"] < 30:
            logit += 0.55
        elif f["age"] < 45:
            logit += 0.10
        elif f["age"] >= 65:
            logit -= 0.35
        logit += 0.75 * min(f["no_shows"], 3.0) + 0.20 * min(f["late"], 2.0)
        logit += 0.0 if f["confirmed"] else 0.85
        if f["hour"] < 9:
            logit += 0.35
        if f["weekday"] == 4 and f["hour"] >= 15:
            logit += 0.40
        logit += 0.25 * f["new"] + 0.30 * f["uninsured"]
        logit += -0.9 * f["emergency"] - 0.2 * f["surgical"]
        return logit + patient.frailty

    def _calibrate(
        self, rows: list[dict[str, Any]], past: list[dict[str, Any]], cancelled: dict[int, bool]
    ) -> float:
        """Find the intercept that gives the target no show rate. Earlier no shows would change
        later logits, so use a no history approximation, which is close because they are rare."""
        attended = [r for r in past if not cancelled[id(r)]]
        if not attended:
            return -2.0
        base = [self._no_show_logit(r, r["b"]["request"].patient) for r in attended]
        low, high = -8.0, 4.0
        for _ in range(40):
            mid = (low + high) / 2
            rate = sum(_sigmoid(mid + x) for x in base) / len(base)
            if rate < self.cfg.target_no_show:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    # --- rows ---

    def _emit(self, rows: list[dict[str, Any]]) -> None:
        d = self.data
        for row in rows:
            b = row["b"]
            request: _Request = b["request"]
            patient = request.patient
            appointment_id = self.uid()
            row["id"] = appointment_id
            channel = _weighted(self.rng, [("web", 55), ("staff", 33), ("chatbot", 12)])
            if request.kind == "emergency":
                channel = "staff"
            slot_range = (row["start"], row["end"])
            d.appointments.append(
                {"id": appointment_id, "patient_id": patient.id, "dentist_id": b["dentist"]["id"],
                 "service_id": self._service_ids[request.code], "slot": slot_range,
                 "status": row["status"], "channel": channel, "reason_note": None,
                 "cancel_reason": row.get("cancel_reason"), "created_by": None,
                 "created_at": row["created"], "rescheduled_from": None,
                 "late_cancel": row["late_cancel"]}
            )  # fmt: skip
            self._history(row, appointment_id)
            if row["status"] == "completed":
                self._bill(row, request, appointment_id)
        d.status_history.sort(key=lambda h: h["changed_at"])

    def _history(self, row: dict[str, Any], appointment_id: uuid.UUID) -> None:
        h = self.data.status_history

        def add(old: str | None, new: str, when: datetime) -> None:
            h.append({"id": self.uid(), "appointment_id": appointment_id, "from_status": old,
                      "to_status": new, "changed_by": None, "changed_at": when})  # fmt: skip

        add(None, "booked", row["created"])
        status = row["status"]
        confirmed_at: datetime | None = None
        if row["confirmed_early"]:
            latest = row["start"] - timedelta(hours=25)
            earliest = max(row["created"] + timedelta(hours=1), row["start"] - timedelta(days=6))
            if latest > earliest:
                confirmed_at = earliest + (latest - earliest) * self.rng.random()
            else:
                row["confirmed_early"] = False
        if status == "cancelled":
            if confirmed_at is not None and confirmed_at < row["cancelled_at"]:
                add("booked", "confirmed", confirmed_at)
                add("confirmed", "cancelled", row["cancelled_at"])
            else:
                add("booked", "cancelled", row["cancelled_at"])
        elif status == "no_show":
            if confirmed_at is not None:
                add("booked", "confirmed", confirmed_at)
                add("confirmed", "no_show", row["start"] + timedelta(minutes=15))
            else:
                add("booked", "no_show", row["start"] + timedelta(minutes=15))
        elif status == "completed":
            add("booked", "confirmed", confirmed_at or row["start"] - timedelta(minutes=10))
            add("confirmed", "checked_in", row["start"] - timedelta(minutes=5))
            add("checked_in", "completed", row["end"])
        elif status == "confirmed":
            add("booked", "confirmed", confirmed_at or row["created"] + timedelta(hours=2))

    def _bill(self, row: dict[str, Any], request: _Request, appointment_id: uuid.UUID) -> None:
        cfg = self.cfg
        d = self.data
        code, name, category, _, price, _ = SERVICE_BY_CODE[request.code]
        patient = request.patient
        local_day = row["start"].astimezone(self.tz).date()
        base = Decimal(price)
        if _month_index(local_day, self.start) >= 12:
            base = base * (Decimal(1) + Decimal(str(cfg.price_increase)))
        subtotal = _money(base)
        discount = Decimal("0.00")
        reason = None
        if self.rng.random() < 0.04:
            discount = _money(subtotal * Decimal("0.10"))
            reason = "Loyalty discount"
        total = subtotal - discount
        expected = Decimal("0.00")
        if patient.insured:
            cover = COVERAGE_BY_CODE.get(code, COVERAGE[category])
            expected = _money(total * Decimal(str(cover)))
        invoice_id = self.uid()
        issued = row["end"] + timedelta(minutes=10)
        d.invoice_items.append(
            {"id": self.uid(), "invoice_id": invoice_id, "service_id": self._service_ids[code],
             "description": name, "qty": 1, "unit_price": subtotal, "amount": subtotal,
             "created_at": issued}
        )  # fmt: skip
        payments = self._payments(invoice_id, patient, total, expected, issued, code)
        paid = sum((p["amount"] for p in payments), Decimal("0.00"))
        status = "paid" if paid >= total else ("partially_paid" if paid > 0 else "issued")
        d.invoices.append(
            {"id": invoice_id, "appointment_id": appointment_id, "patient_id": patient.id,
             "issued_at": issued, "subtotal": subtotal, "discount": discount, "tax": Decimal("0.00"),
             "total": total, "insurance_expected": expected, "status": status,
             "discount_reason": reason, "voided_at": None, "void_reason": None}
        )  # fmt: skip
        d.payments.extend(payments)

    def _payments(
        self,
        invoice_id: uuid.UUID,
        patient: _Patient,
        total: Decimal,
        expected: Decimal,
        issued: datetime,
        code: str,
    ) -> list[dict[str, Any]]:
        now = self.cfg.now
        out: list[dict[str, Any]] = []

        def pay(amount: Decimal, when: datetime, insurer: bool) -> None:
            if amount <= 0 or when > now:
                return
            method = (
                "insurance"
                if insurer
                else _weighted(self.rng, [("card", 70), ("cash", 22), ("bank_transfer", 8)])
            )
            out.append(
                {"id": self.uid(), "invoice_id": invoice_id, "amount": amount, "method": method,
                 "payer_type": "insurer" if insurer else "patient", "paid_at": when,
                 "reference": f"CLM-{self.rng.randint(10**7, 10**8 - 1)}" if insurer else None,
                 "card_last4": f"{self.rng.randint(0, 9999):04d}" if method == "card" else None,
                 "sandbox": False, "recorded_by": None}
            )  # fmt: skip

        patient_part = total - expected
        if patient.insured and expected > 0:
            roll = self.rng.random()
            when = issued + timedelta(days=self.rng.randint(14, 45), hours=self.rng.randint(0, 20))
            if roll < 0.03:
                pass  # claim denied and never paid
            elif roll < 0.07:
                pay(_money(expected * Decimal("0.85")), when, True)
            else:
                pay(expected, when, True)
        if patient.plan and total >= 300:
            share = _money(patient_part / 3)
            pay(share, issued + timedelta(minutes=20), False)
            pay(share, issued + timedelta(days=30), False)
            pay(patient_part - 2 * share, issued + timedelta(days=60), False)
        elif self.rng.random() < 0.012:
            pass  # a bill that is never settled
        else:
            pay(patient_part, issued + timedelta(minutes=self.rng.randint(5, 40)), False)
        return out

    # --- orchestration ---

    def run(self) -> Dataset:
        self.build_reference()
        for dentist in self._dentist.values():
            specialty = next(r["specialty"] for r in self.data.dentists if r["id"] == dentist["id"])
            if specialty == "pediatric":
                dentist["specialty_ok"] = lambda age: age < 18
        patients = self.build_patients()
        requests = self.build_requests(patients)
        self.shape_dates(requests)
        bookings = self.book(requests)
        self.data.requested = len(requests)
        self.data.unplaced = len(requests) - len(bookings)
        self.build_appointments(bookings)
        self.data.invoices.sort(key=lambda r: r["issued_at"])
        return self.data


def generate(config: GenConfig, encrypt: Callable[[str, str], str]) -> Dataset:
    return Generator(config, encrypt).run()


def summarize(data: Dataset) -> dict[str, Any]:
    """Headline numbers used to check the dataset against the targets in the plan."""
    cfg = data.config
    tz = cfg.tz
    appointments = data.appointments
    status: dict[str, int] = defaultdict(int)
    monthly: dict[str, int] = defaultdict(int)
    mix: dict[str, int] = defaultdict(int)
    code_of = {s["id"]: s["code"] for s in data.services}
    for a in appointments:
        status[a["status"]] += 1
        if a["status"] == "completed":
            monthly[a["slot"][0].astimezone(tz).strftime("%Y-%m")] += 1
            mix[code_of[a["service_id"]]] += 1
    past = sum(status[s] for s in ("completed", "cancelled", "no_show"))
    attended = status["completed"] + status["no_show"]
    first_year = sum(
        v for k, v in monthly.items() if k < f"{cfg.start_date.year + 1}-{cfg.start_date.month:02d}"
    )
    months = sorted(monthly)
    return {
        "patients": len(data.patients),
        "appointments": len(appointments),
        "status": dict(status),
        "completed_share": status["completed"] / past if past else 0,
        "cancel_share": status["cancelled"] / past if past else 0,
        "no_show_share": status["no_show"] / past if past else 0,
        "no_show_rate": status["no_show"] / attended if attended else 0,
        "invoices": len(data.invoices),
        "payments": len(data.payments),
        "months": len(months),
        "first_year_completed": first_year,
        "mix": dict(mix),
        "monthly_completed": dict(sorted(monthly.items())),
    }
