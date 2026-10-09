"""The chat assistant: start a conversation, send messages, give feedback."""

import hmac
import json
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.v1.booking_deps import Appointments, Availability, Guests
from app.chat.metrics import chat_metrics
from app.chat.replies import Choice
from app.chat.router import OPTION_PREFIX, ChatRouter, TurnResult
from app.chat.state import SessionState
from app.core.crypto import sha256_hex
from app.core.deps import (
    AppSettings,
    CurrentUser,
    RedisDep,
    Session,
    get_current_user,
    require_roles,
)
from app.core.errors import AppError
from app.core.rate_limit import chat_rule, ip_rate_limit
from app.db.enums import ChatRole, UserRole
from app.db.models import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageOut,
    ChatMetrics,
    ChatReplyOut,
    CreateSessionResponse,
    FeedbackRequest,
    LinkOut,
    QuickReplyOut,
    SendMessageRequest,
    SessionOut,
)

router = APIRouter(prefix="/chat", tags=["chat"])
admin_router = APIRouter(prefix="/admin/chat", tags=["chat"])

chat_limit = Depends(ip_rate_limit(chat_rule))
LOCK_SECONDS = 60
STREAM_WORDS = 3  # words per streamed chunk


async def optional_user(request: Request, db: Session) -> CurrentUser | None:
    """The signed in user, or None for anyone anonymous or holding an unusable token."""
    if "authorization" not in request.headers:
        return None
    try:
        return await get_current_user(request, db)
    except AppError:
        return None


OptionalUser = Annotated[CurrentUser | None, Depends(optional_user)]
ChatToken = Annotated[str | None, Header(alias="X-Chat-Token")]
AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


def get_chat_router(
    request: Request,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
    appointments: Appointments,
    availability: Availability,
    guests: Guests,
) -> ChatRouter:
    return ChatRouter(
        db=db,
        settings=settings,
        redis=redis,
        embedder=request.app.state.embedder,
        gateway=getattr(request.app.state, "llm", None),
        appointments=appointments,
        availability=availability,
        guests=guests,
    )


Chat = Annotated[ChatRouter, Depends(get_chat_router)]


def session_not_found() -> AppError:
    return AppError("not_found", "Conversation not found.", 404)


async def load_session(db: Session, session_id: uuid.UUID, token: str | None) -> ChatSession:
    """The conversation, provided the caller holds its secret token."""
    session = await db.get(ChatSession, session_id)
    expected = session.anon_token_hash if session and session.anon_token_hash else ""
    given = sha256_hex(token) if token else ""
    matches = hmac.compare_digest(expected.encode(), given.encode())
    if session is None or not token or not matches or session.ended_at is not None:
        raise session_not_found()
    return session


def reply_out(result: TurnResult) -> ChatReplyOut:
    reply = result.reply
    return ChatReplyOut(
        message_id=result.assistant_message_id,
        text=reply.text,
        route=reply.route,
        intent=reply.intent,
        quick_replies=[QuickReplyOut(**q.__dict__) for q in reply.quick_replies],
        links=[LinkOut(**link.__dict__) for link in reply.links],
        input_hint=reply.input_hint,
        picker=reply.picker,
        degraded=reply.degraded,
        flow=result.flow,
        step=result.step,
    )


@router.post(
    "/sessions", response_model=CreateSessionResponse, status_code=201, dependencies=[chat_limit]
)
async def create_session(db: Session, chat: Chat, user: OptionalUser) -> CreateSessionResponse:
    token = secrets.token_urlsafe(32)
    session = ChatSession(
        user_id=user.id if user else None, anon_token_hash=sha256_hex(token), state={}
    )
    db.add(session)
    await db.flush()
    result = await chat.open_session(session)
    return CreateSessionResponse(
        session_id=session.id, session_token=token, greeting=reply_out(result)
    )


@router.get("/sessions/{session_id}", response_model=SessionOut, dependencies=[chat_limit])
async def get_session(
    session_id: uuid.UUID, db: Session, x_chat_token: ChatToken = None
) -> SessionOut:
    session = await load_session(db, session_id, x_chat_token)
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    state = SessionState.load(session.state)
    messages = []
    for row in rows:
        payload: dict[str, Any] = row.payload or {}
        rating = {1: "up", -1: "down"}.get(row.feedback or 0)
        messages.append(
            ChatMessageOut(
                id=row.id,
                role=row.role,
                content=row.content.removeprefix(OPTION_PREFIX),
                intent=row.intent,
                route=row.route,
                quick_replies=[QuickReplyOut(**q) for q in payload.get("quick_replies", [])],
                links=[LinkOut(**link) for link in payload.get("links", [])],
                input_hint=payload.get("input_hint"),
                picker=payload.get("picker"),
                feedback=rating,
                created_at=row.created_at,
            )
        )
    return SessionOut(
        id=session.id,
        created_at=session.created_at,
        flow=state.flow.name if state.flow else None,
        step=state.flow.step if state.flow else None,
        messages=messages,
    )


async def _lock(redis: Redis, session_id: uuid.UUID) -> str:
    """One message at a time per conversation, so two quick clicks cannot interleave."""
    token = secrets.token_hex(8)
    if not await redis.set(f"chat:lock:{session_id}", token, nx=True, ex=LOCK_SECONDS):
        raise AppError("chat_busy", "Please wait for the previous reply.", 409)
    return token


async def _unlock(redis: Redis, session_id: uuid.UUID, token: str) -> None:
    key = f"chat:lock:{session_id}"
    if await redis.get(key) == token:
        await redis.delete(key)


def _event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(out: ChatReplyOut) -> AsyncIterator[str]:
    """Send the finished reply as it would arrive from a streaming model: a header event,
    the text in small pieces, then the complete reply with its buttons."""
    yield _event("meta", {"message_id": str(out.message_id), "route": out.route.value})
    words = out.text.split(" ")
    for i in range(0, len(words), STREAM_WORDS):
        piece = " ".join(words[i : i + STREAM_WORDS])
        yield _event("delta", {"text": piece + (" " if i + STREAM_WORDS < len(words) else "")})
    yield _event("done", json.loads(out.model_dump_json()))


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatReplyOut,
    responses={200: {"content": {"text/event-stream": {}}}},
    dependencies=[chat_limit],
)
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    db: Session,
    chat: Chat,
    redis: RedisDep,
    user: OptionalUser,
    x_chat_token: ChatToken = None,
) -> Any:
    session = await load_session(db, session_id, x_chat_token)
    lock = await _lock(redis, session.id)
    try:
        choice = (
            Choice(body.choice.kind, body.choice.value, body.choice.label) if body.choice else None
        )
        result = await chat.handle(session, body.text, choice, user)
    finally:
        await _unlock(redis, session.id, lock)
    out = reply_out(result)
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            _stream(out),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return out


@router.post("/sessions/{session_id}/feedback", status_code=204, dependencies=[chat_limit])
async def give_feedback(
    session_id: uuid.UUID, body: FeedbackRequest, db: Session, x_chat_token: ChatToken = None
) -> None:
    session = await load_session(db, session_id, x_chat_token)
    message = (
        await db.execute(
            select(ChatMessage).where(
                ChatMessage.id == body.message_id,
                ChatMessage.session_id == session.id,
                ChatMessage.role == ChatRole.ASSISTANT,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise AppError("not_found", "Message not found.", 404)
    message.feedback = 1 if body.rating == "up" else -1
    await db.commit()


@admin_router.get("/metrics", response_model=ChatMetrics)
async def metrics(
    _: AdminUser, db: Session, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> ChatMetrics:
    """Zero model share, tokens per conversation, booking funnel and unanswered questions."""
    return await chat_metrics(db, days)
