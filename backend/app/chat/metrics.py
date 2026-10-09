"""Numbers about the assistant for the admin dashboard: how many turns needed no model, what a
conversation cost in tokens, how far booking conversations got, and what went unanswered."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ChatRole, ChatRoute
from app.db.models import ChatMessage, ChatSession, LlmUsage
from app.schemas.chat import ChatMetrics, ProviderShare, UnansweredQuestion

OPENING_INTENT = "session_open"
TOP_UNANSWERED = 10


async def chat_metrics(db: AsyncSession, days: int) -> ChatMetrics:
    since = datetime.now(UTC) - timedelta(days=days)

    session_ids = select(ChatSession.id).where(ChatSession.created_at >= since)
    conversations = (
        await db.execute(
            select(func.count(func.distinct(ChatMessage.session_id))).where(
                ChatMessage.role == ChatRole.USER, ChatMessage.session_id.in_(session_ids)
            )
        )
    ).scalar_one()

    reply = (ChatMessage.role == ChatRole.ASSISTANT) & (
        func.coalesce(ChatMessage.intent, "") != OPENING_INTENT
    )
    turns, zero_turns, llm_calls = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(ChatMessage.llm_calls == 0),
                func.coalesce(func.sum(ChatMessage.llm_calls), 0),
            ).where(reply, ChatMessage.session_id.in_(session_ids))
        )
    ).one()

    usage_rows = (
        await db.execute(
            select(
                LlmUsage.provider,
                func.count(),
                func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0),
            )
            .where(LlmUsage.session_id.in_(session_ids))
            .group_by(LlmUsage.provider)
            .order_by(LlmUsage.provider)
        )
    ).all()
    tokens = sum(int(row[2]) for row in usage_rows)

    funnel = {}
    for stage in ("started", "slot_chosen", "confirmed"):
        funnel[stage] = (
            await db.execute(
                select(func.count()).where(
                    ChatSession.created_at >= since,
                    ChatSession.state["funnel"][stage].as_boolean().is_(True),
                )
            )
        ).scalar_one()

    booked_tokens = (
        await db.execute(
            select(func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0))
            .join(ChatSession, ChatSession.id == LlmUsage.session_id)
            .where(
                ChatSession.created_at >= since,
                ChatSession.state["funnel"]["confirmed"].as_boolean().is_(True),
            )
        )
    ).scalar_one()

    handoffs = (
        await db.execute(
            select(func.count()).where(
                ChatMessage.route == ChatRoute.HANDOFF,
                ChatMessage.session_id.in_(session_ids),
            )
        )
    ).scalar_one()
    up, down = (
        await db.execute(
            select(
                func.count().filter(ChatMessage.feedback == 1),
                func.count().filter(ChatMessage.feedback == -1),
            ).where(ChatMessage.session_id.in_(session_ids))
        )
    ).one()

    question = func.lower(ChatMessage.content)
    unanswered = (
        await db.execute(
            select(question, func.count())
            .where(
                ChatMessage.role == ChatRole.USER,
                ChatMessage.intent == "unanswered",
                ChatMessage.session_id.in_(session_ids),
            )
            .group_by(question)
            .order_by(func.count().desc(), question)
            .limit(TOP_UNANSWERED)
        )
    ).all()

    return ChatMetrics(
        days=days,
        conversations=conversations,
        turns=turns,
        zero_llm_turns=zero_turns,
        zero_llm_share=round(zero_turns / turns, 4) if turns else None,
        llm_calls=int(llm_calls),
        tokens=tokens,
        tokens_per_conversation=round(tokens / conversations, 1) if conversations else None,
        tokens_per_booking=round(int(booked_tokens) / funnel["confirmed"], 1)
        if funnel["confirmed"]
        else None,
        funnel_started=funnel["started"],
        funnel_slot_chosen=funnel["slot_chosen"],
        funnel_confirmed=funnel["confirmed"],
        handoffs=handoffs,
        feedback_up=up,
        feedback_down=down,
        providers=[
            ProviderShare(provider=p, calls=int(c), tokens=int(t)) for p, c, t in usage_rows
        ],
        unanswered=[UnansweredQuestion(question=q, count=int(c)) for q, c in unanswered],
    )
