from typing import Any

import pytest
from httpx import Response

from app.db.enums import UserRole
from tests.auth.conftest import Ctx, unique_email
from tests.knowledge.conftest import FakeEmbedder

BASE = "/api/v1/admin/kb"

GOOD_BODY = (
    "We are open on weekdays from 8:00 AM to 6:00 PM and on Saturday morning.\n\n"
    "## Short answer\nWe are open weekdays and Saturday morning."
)


def payload(slug: str = "extra-hours", **overrides: Any) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": "Extra hours",
        "category": "practice",
        "body": GOOD_BODY,
        **overrides,
    }


@pytest.fixture
async def admin(ctx: Ctx, fake_embedder: FakeEmbedder) -> dict[str, str]:
    ctx.app.state.embedder = fake_embedder
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    return ctx.auth(await ctx.access_token(email))


async def create(ctx: Ctx, admin: dict[str, str], **overrides: Any) -> Response:
    return await ctx.client.post(f"{BASE}/documents", headers=admin, json=payload(**overrides))


# --- who can use it --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/documents"),
        ("GET", "/documents/x"),
        ("POST", "/documents"),
        ("PUT", "/documents/x"),
        ("POST", "/documents/x/reembed"),
        ("POST", "/reindex"),
        ("GET", "/search?q=hours"),
    ],
)
async def test_only_administrators_may_manage_the_knowledge_base(
    ctx: Ctx, fake_embedder: FakeEmbedder, method: str, path: str
) -> None:
    ctx.app.state.embedder = fake_embedder
    assert (await ctx.client.request(method, BASE + path, json={})).status_code == 401
    for role in (UserRole.PATIENT, UserRole.RECEPTIONIST, UserRole.DENTIST):
        email = unique_email(role.value)
        await ctx.create_user(email, role)
        headers = ctx.auth(await ctx.access_token(email))
        response = await ctx.client.request(method, BASE + path, headers=headers, json={})
        assert response.status_code == 403, (role, method, path)


# --- create, read, list -------------------------------------------------------------------------------


async def test_creating_a_document_stores_chunks_and_marks_it_console_managed(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    response = await create(ctx, admin)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["slug"], body["managed_by"], body["stale"]) == ("extra-hours", "admin", False)
    assert (
        body["chunks"] >= 1 and body["short_answer"] == "We are open weekdays and Saturday morning."
    )
    assert body["embedded_at"] is not None
    assert (await ctx.fetch("SELECT count(*) FROM kb_chunks"))[0][0] == body["chunks"]
    audit = await ctx.fetch("SELECT action, entity FROM audit_logs WHERE action = 'kb.create'")
    assert audit == [("kb.create", "kb_document")]


async def test_a_document_can_be_saved_without_embedding_and_is_then_stale(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    body = (await create(ctx, admin, reembed=False)).json()
    assert body["stale"] is True and body["chunks"] == 0 and body["embedded_at"] is None
    stale = (
        await ctx.client.get(f"{BASE}/documents", params={"stale_only": "true"}, headers=admin)
    ).json()
    assert [d["slug"] for d in stale] == ["extra-hours"]


async def test_duplicate_ids_are_rejected(ctx: Ctx, admin: dict[str, str]) -> None:
    await create(ctx, admin)
    response = await create(ctx, admin)
    assert response.status_code == 409 and response.json()["code"] == "conflict"


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"slug": "Bad Slug"}, "id must be lower case"),
        ({"category": "gossip"}, "category must be one of"),
        ({"body": "No short answer section here."}, "Short answer"),
        ({"body": "Text.\n\n## Short answer\nOne. Two. Three. Four."}, "one to three sentences"),
    ],
)
async def test_invalid_documents_are_rejected_with_the_reasons(
    ctx: Ctx, admin: dict[str, str], overrides: dict[str, object], problem: str
) -> None:
    response = await create(ctx, admin, **overrides)
    assert response.status_code == 422
    assert any(problem in p for p in response.json()["details"])
    assert (await ctx.fetch("SELECT count(*) FROM kb_documents"))[0][0] == 0


async def test_request_bodies_reject_unknown_fields_and_oversized_text(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    assert (await create(ctx, admin, managed_by="file")).status_code == 422
    assert (await create(ctx, admin, body="x" * 20_001)).status_code == 422
    assert (await create(ctx, admin, title="")).status_code == 422


async def test_unknown_placeholders_are_rejected_and_known_ones_are_filled(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    bad = await create(ctx, admin, body="Call {{secret}}.\n\n## Short answer\nCall us.")
    assert bad.status_code == 422
    ok = await create(
        ctx,
        admin,
        slug="phone",
        body="Call {{clinic_phone}} to book.\n\n## Short answer\nCall {{clinic_phone}}.",
    )
    assert (
        ok.status_code == 201
        and "(555) 010-0199" in ok.json()["body"]
        and "{{" not in ok.json()["body"]
    )


async def test_documents_can_be_read_and_listed_with_filters(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    await create(ctx, admin, slug="extra-hours")
    await create(ctx, admin, slug="price-extra", title="Extra price", category="pricing")
    client = ctx.client

    one = await client.get(f"{BASE}/documents/extra-hours", headers=admin)
    assert one.status_code == 200 and one.json()["body"].startswith("We are open")
    assert (await client.get(f"{BASE}/documents/missing", headers=admin)).status_code == 404

    everything = (await client.get(f"{BASE}/documents", headers=admin)).json()
    assert [d["slug"] for d in everything] == ["extra-hours", "price-extra"]
    pricing = (
        await client.get(f"{BASE}/documents", params={"category": "pricing"}, headers=admin)
    ).json()
    assert [d["slug"] for d in pricing] == ["price-extra"]
    found = (await client.get(f"{BASE}/documents", params={"q": "price"}, headers=admin)).json()
    assert [d["slug"] for d in found] == ["price-extra"]
    assert set(everything[0]) == {
        "slug",
        "title",
        "category",
        "updated_at",
        "managed_by",
        "stale",
        "chunks",
    }


# --- editing and re-embedding ----------------------------------------------------------------------------


async def test_editing_a_document_re_embeds_it_and_protects_it_from_the_file_sync(
    ctx: Ctx, admin: dict[str, str], fake_embedder: FakeEmbedder
) -> None:
    await create(ctx, admin)
    before = fake_embedder.documents_embedded
    new_body = "We now open at seven on weekdays.\n\n## Short answer\nWe open at seven on weekdays."

    response = await ctx.client.put(
        f"{BASE}/documents/extra-hours", headers=admin, json={"body": new_body}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stale"] is False and body["managed_by"] == "admin" and "seven" in body["body"]
    assert fake_embedder.documents_embedded > before
    texts = [r[0] for r in await ctx.fetch("SELECT text FROM kb_chunks")]
    assert any("seven" in t for t in texts) and not any("8:00 AM" in t for t in texts)
    assert (await ctx.fetch("SELECT count(*) FROM audit_logs WHERE action = 'kb.update'"))[0][
        0
    ] == 1


async def test_editing_only_the_title_or_category_keeps_the_rest(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    await create(ctx, admin)
    response = await ctx.client.put(
        f"{BASE}/documents/extra-hours",
        headers=admin,
        json={"title": "Weekend hours", "category": "policies"},
    )
    body = response.json()
    assert (body["title"], body["category"]) == ("Weekend hours", "policies") and body[
        "body"
    ].startswith("We are open")


async def test_invalid_edits_change_nothing(ctx: Ctx, admin: dict[str, str]) -> None:
    await create(ctx, admin)
    bad = await ctx.client.put(
        f"{BASE}/documents/extra-hours", headers=admin, json={"body": "No heading."}
    )
    assert bad.status_code == 422
    assert (
        await ctx.client.put(f"{BASE}/documents/missing", headers=admin, json={"title": "x"})
    ).status_code == 404
    assert (
        (await ctx.client.get(f"{BASE}/documents/extra-hours", headers=admin))
        .json()["body"]
        .startswith("We are open")
    )


async def test_edits_without_embedding_leave_the_document_stale_until_reindexed(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    await create(ctx, admin)
    await ctx.client.put(
        f"{BASE}/documents/extra-hours",
        headers=admin,
        json={"body": "Changed text.\n\n## Short answer\nChanged.", "reembed": False},
    )
    stale = (
        await ctx.client.get(f"{BASE}/documents", params={"stale_only": "true"}, headers=admin)
    ).json()
    assert [d["slug"] for d in stale] == ["extra-hours"]

    result = await ctx.client.post(f"{BASE}/reindex", headers=admin)
    assert result.status_code == 200
    assert result.json()["reembedded"] == ["extra-hours"] and result.json()["chunks_written"] >= 1
    assert (
        await ctx.client.get(f"{BASE}/documents", params={"stale_only": "true"}, headers=admin)
    ).json() == []
    assert (await ctx.client.post(f"{BASE}/reindex", headers=admin)).json() == {
        "reembedded": [],
        "chunks_written": 0,
    }


async def test_forced_reindex_and_single_document_reembed(
    ctx: Ctx, admin: dict[str, str], fake_embedder: FakeEmbedder
) -> None:
    await create(ctx, admin, slug="doc-a")
    await create(ctx, admin, slug="doc-b")
    before = fake_embedder.documents_embedded

    forced = (
        await ctx.client.post(f"{BASE}/reindex", params={"force": "true"}, headers=admin)
    ).json()
    assert forced["reembedded"] == ["doc-a", "doc-b"] and fake_embedder.documents_embedded > before

    single = await ctx.client.post(f"{BASE}/documents/doc-a/reembed", headers=admin)
    assert (
        single.status_code == 200
        and single.json()["slug"] == "doc-a"
        and single.json()["stale"] is False
    )
    assert (
        await ctx.client.post(f"{BASE}/documents/none/reembed", headers=admin)
    ).status_code == 404
    actions = {
        r[0] for r in await ctx.fetch("SELECT action FROM audit_logs WHERE action LIKE 'kb.%'")
    }
    assert {"kb.create", "kb.reindex", "kb.reembed"} <= actions


async def test_a_corrupted_chunk_set_is_repaired_by_a_forced_reembed(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    await create(ctx, admin)
    await ctx.execute("DELETE FROM kb_chunks")
    assert (await ctx.client.get(f"{BASE}/documents/extra-hours", headers=admin)).json()[
        "chunks"
    ] == 0
    repaired = (
        await ctx.client.post(f"{BASE}/documents/extra-hours/reembed", headers=admin)
    ).json()
    assert repaired["chunks"] >= 1


# --- search preview ----------------------------------------------------------------------------------------


async def test_the_search_preview_shows_what_the_assistant_would_retrieve(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    await create(ctx, admin, slug="hours-doc")
    await create(
        ctx,
        admin,
        slug="parking-doc",
        title="Parking",
        category="practice",
        body="Free parking is in the lot beside the building.\n\n## Short answer\nParking is free.",
    )
    response = await ctx.client.get(
        f"{BASE}/search", params={"q": "where is the parking lot", "k": 2}, headers=admin
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits[0]["slug"] == "parking-doc" and len(hits) == 2
    assert set(hits[0]) == {"slug", "title", "category", "score", "chunk_index", "text"}
    assert hits[0]["score"] >= hits[1]["score"]


async def test_the_search_preview_validates_its_parameters(ctx: Ctx, admin: dict[str, str]) -> None:
    client = ctx.client
    assert (await client.get(f"{BASE}/search", headers=admin)).status_code == 422
    assert (await client.get(f"{BASE}/search", params={"q": ""}, headers=admin)).status_code == 422
    assert (
        await client.get(f"{BASE}/search", params={"q": "x", "k": 50}, headers=admin)
    ).status_code == 422
    assert (
        await client.get(f"{BASE}/search", params={"q": "x" * 501}, headers=admin)
    ).status_code == 422


async def test_a_missing_embedder_reports_the_service_as_unavailable(
    ctx: Ctx, admin: dict[str, str]
) -> None:
    ctx.app.state.embedder = None
    response = await ctx.client.get(f"{BASE}/search", params={"q": "hours"}, headers=admin)
    assert response.status_code == 503 and response.json()["code"] == "embeddings_unavailable"
    assert (await create(ctx, admin)).status_code == 503
