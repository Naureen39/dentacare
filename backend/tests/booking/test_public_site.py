from datetime import timedelta

from app.db.enums import UserRole
from app.db.models import Testimonial as TestimonialRow
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc

PUBLIC = "/api/v1/public"


async def test_services_are_listed_in_display_order_without_inactive_ones(
    practice: Practice,
) -> None:
    await practice.ctx.execute(
        "INSERT INTO services (code, name, category, duration_min, base_price, is_active) "
        "VALUES ('SVX', 'Retired Service', 'preventive', 30, 10.00, false)"
    )
    response = await practice.ctx.client.get(f"{PUBLIC}/services")
    assert response.status_code == 200
    assert [s["code"] for s in response.json()] == ["SV02", "SV05"]
    assert response.json()[0]["base_price"] == "120.00"
    assert response.json()[0]["duration_min"] == 45


async def test_dentists_can_be_filtered_by_service_and_hide_private_fields(
    practice: Practice,
) -> None:
    everyone = (await practice.ctx.client.get(f"{PUBLIC}/dentists")).json()
    crown_only = (
        await practice.ctx.client.get(
            f"{PUBLIC}/dentists", params={"service_id": str(practice.crown.id)}
        )
    ).json()
    assert len(everyone) == 2 and [d["full_name"] for d in crown_only] == ["Dr. Priya Raman"]
    assert "license_no" not in everyone[0] and "user_id" not in everyone[0]


async def test_inactive_dentists_are_not_listed(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE dentists SET is_active = false WHERE full_name = 'Dr. Marcus Lindqvist'"
    )
    names = [d["full_name"] for d in (await practice.ctx.client.get(f"{PUBLIC}/dentists")).json()]
    assert names == ["Dr. Priya Raman"]


async def test_availability_response_shape(practice: Practice) -> None:
    day = future_date(2)
    response = await practice.ctx.client.get(
        f"{PUBLIC}/availability",
        params={
            "service_id": str(practice.cleaning.id),
            "from": day.isoformat(),
            "to": (day + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [d["date"] for d in body] == [day.isoformat(), (day + timedelta(days=1)).isoformat()]
    slot = body[0]["slots"][0]
    assert set(slot) == {"start", "end", "dentist_id", "dentist_name"}
    assert slot["start"].endswith("Z")


async def test_availability_validates_its_input(practice: Practice) -> None:
    day = future_date(2)
    service = str(practice.cleaning.id)
    client = practice.ctx.client
    assert (
        await client.get(f"{PUBLIC}/availability", params={"service_id": service})
    ).status_code == 422
    assert (
        await client.get(
            f"{PUBLIC}/availability",
            params={
                "service_id": service,
                "from": day.isoformat(),
                "to": (day - timedelta(days=1)).isoformat(),
            },
        )
    ).status_code == 422
    assert (
        await client.get(
            f"{PUBLIC}/availability",
            params={
                "service_id": service,
                "from": day.isoformat(),
                "to": (day + timedelta(days=40)).isoformat(),
            },
        )
    ).status_code == 422
    assert (
        await client.get(
            f"{PUBLIC}/availability",
            params={
                "service_id": "00000000-0000-0000-0000-000000000000",
                "from": day.isoformat(),
                "to": day.isoformat(),
            },
        )
    ).status_code == 404
    assert (
        await client.get(
            f"{PUBLIC}/availability",
            params={"service_id": "nonsense", "from": day.isoformat(), "to": day.isoformat()},
        )
    ).status_code == 422


async def test_availability_is_served_from_cache_within_thirty_seconds(practice: Practice) -> None:
    day = future_date(2)
    params = {
        "service_id": str(practice.cleaning.id),
        "from": day.isoformat(),
        "to": day.isoformat(),
    }
    await practice.ctx.client.get(f"{PUBLIC}/availability", params=params)
    keys = [k async for k in practice.ctx.redis.scan_iter("avail:0:*")]
    assert len(keys) == 1 and 0 < await practice.ctx.redis.ttl(keys[0]) <= 30


async def test_availability_reflects_a_new_booking_immediately(practice: Practice) -> None:
    day = future_date(2)
    params = {
        "service_id": str(practice.cleaning.id),
        "from": day.isoformat(),
        "to": day.isoformat(),
        "dentist_id": str(practice.dentist_a.id),
    }
    before = (await practice.ctx.client.get(f"{PUBLIC}/availability", params=params)).json()[0][
        "slots"
    ]

    token = await practice.staff_token(UserRole.RECEPTIONIST)
    created = await practice.ctx.client.post(
        "/api/v1/staff/appointments",
        headers=practice.ctx.auth(token),
        json={
            "patient_id": str(practice.patient.id),
            "service_id": str(practice.cleaning.id),
            "dentist_id": str(practice.dentist_a.id),
            "start": local_utc(day, 10, 0).isoformat(),
        },
    )
    assert created.status_code == 201
    after = (await practice.ctx.client.get(f"{PUBLIC}/availability", params=params)).json()[0][
        "slots"
    ]
    assert len(after) < len(before)


# --- contact form, newsletter, testimonials -------------------------------------------------------


async def test_contact_form_stores_an_inquiry(practice: Practice) -> None:
    response = await practice.ctx.client.post(
        f"{PUBLIC}/contact",
        json={
            "name": "Lena Fischer",
            "email": "lena@example.com",
            "message": "Do you offer weekend appointments?",
        },
    )
    assert response.status_code == 201
    rows = await practice.ctx.fetch(
        "SELECT name, source::text, status::text FROM contact_inquiries"
    )
    assert rows == [("Lena Fischer", "contact_form", "new")]


async def test_contact_form_validation(practice: Practice) -> None:
    client = practice.ctx.client
    assert (
        await client.post(f"{PUBLIC}/contact", json={"name": "A", "message": "hi"})
    ).status_code == 422
    assert (
        await client.post(f"{PUBLIC}/contact", json={"name": "A", "message": "x" * 2001})
    ).status_code == 422
    assert (
        await client.post(
            f"{PUBLIC}/contact", json={"name": "A", "email": "nope", "message": "A valid message"}
        )
    ).status_code == 422
    assert (
        await client.post(
            f"{PUBLIC}/contact",
            json={"name": "A", "message": "A valid message", "status": "closed"},
        )
    ).status_code == 422


async def test_contact_form_is_limited_to_five_per_hour_per_ip(practice: Practice) -> None:
    practice.ctx.set_settings(rate_limit_contact_per_hour=5)
    statuses = []
    for _ in range(7):
        response = await practice.ctx.client.post(
            f"{PUBLIC}/contact",
            json={"name": "Visitor", "message": "Hello, a question about hours."},
        )
        statuses.append(response.status_code)
    assert statuses == [201] * 5 + [429] * 2


async def test_newsletter_signup_is_idempotent_and_case_insensitive(practice: Practice) -> None:
    for address in ("Reader@Example.com", "reader@example.com", "READER@example.com"):
        response = await practice.ctx.client.post(f"{PUBLIC}/newsletter", json={"email": address})
        assert response.status_code == 202
    assert await practice.ctx.fetch("SELECT count(*) FROM newsletter_subscribers") == [(1,)]


async def test_resubscribing_clears_a_previous_unsubscribe(practice: Practice) -> None:
    email = unique_email("reader")
    await practice.ctx.client.post(f"{PUBLIC}/newsletter", json={"email": email})
    await practice.ctx.execute("UPDATE newsletter_subscribers SET unsubscribed_at = now()")
    await practice.ctx.client.post(f"{PUBLIC}/newsletter", json={"email": email})
    assert await practice.ctx.fetch("SELECT unsubscribed_at FROM newsletter_subscribers") == [
        (None,)
    ]


async def test_testimonials_list_only_published_entries_newest_first(practice: Practice) -> None:
    async with practice.ctx.session_factory() as db:
        db.add_all(
            [
                TestimonialRow(
                    first_name="Anna",
                    last_initial="K",
                    treatment="Cleaning",
                    rating=5,
                    body="Friendly and thorough team.",
                ),
                TestimonialRow(
                    first_name="Ben",
                    last_initial="R",
                    treatment="Crown",
                    rating=4,
                    body="Comfortable visit.",
                    is_published=False,
                ),
            ]
        )
        await db.commit()
    body = (await practice.ctx.client.get(f"{PUBLIC}/testimonials")).json()
    assert [t["first_name"] for t in body] == ["Anna"]
    assert set(body[0]) == {"id", "first_name", "last_initial", "treatment", "rating", "body"}


async def test_insurance_providers_are_listed_by_name(practice: Practice) -> None:
    await practice.ctx.execute(
        "INSERT INTO insurance_providers (name, plan_types) VALUES "
        "('Zenith Health', '{PPO}'), ('Alpine Mutual', '{HMO,PPO}')"
    )
    response = await practice.ctx.client.get(f"{PUBLIC}/insurance-providers")
    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == ["Alpine Mutual", "Zenith Health"]
    assert response.json()[0]["plan_types"] == ["HMO", "PPO"]
