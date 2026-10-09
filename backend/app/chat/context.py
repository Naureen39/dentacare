"""What earlier conversation goes to the model: the last few turns and a short summary.

The summary is built by cutting down old messages with rules, never by asking a model.
"""

import re
from collections.abc import Sequence

from app.chat.budget import estimate_tokens, limit_to_tokens
from app.chat.safety import neutralize_delimiters
from app.chat.types import Message

HISTORY_TURNS = 4  # a turn is one visitor message and the assistant's reply
SUMMARY_AFTER_TURNS = 8
SUMMARY_MAX_TOKENS = 80
MESSAGE_MAX_TOKENS = 50  # each remembered message is cut to this size
SUMMARY_WORDS_PER_MESSAGE = 10


def recent_history(rows: Sequence[tuple[str, str]], turns: int = HISTORY_TURNS) -> list[Message]:
    """The last ``turns`` exchanges as user and assistant messages, oldest first.

    ``rows`` are (role, content) in order and must not include the message being answered.
    """
    kept = [(role, text) for role, text in rows if role in ("user", "assistant") and text.strip()]
    messages: list[Message] = []
    users_seen = 0
    for role, text in reversed(kept):
        if role == "user":
            users_seen += 1
            if users_seen > turns:
                break
        messages.append(Message("user" if role == "user" else "assistant", text))
    messages.reverse()
    while messages and messages[0].role != "user":  # never start on an orphaned reply
        messages.pop(0)
    return [
        Message(m.role, limit_to_tokens(neutralize_delimiters(m.content), MESSAGE_MAX_TOKENS))
        for m in messages
    ]


def fit_history(history: list[Message], budget_tokens: int) -> list[Message]:
    """Drop the oldest exchanges until the history fits ``budget_tokens``."""
    kept = list(history)
    while kept and sum(estimate_tokens(m.content) for m in kept) > budget_tokens:
        kept.pop(0)
        while kept and kept[0].role != "user":
            kept.pop(0)
    return kept


def rolling_summary(older_user_messages: Sequence[str]) -> str:
    """A short note of what the visitor asked earlier, made by trimming each old message."""
    pieces = []
    for message in older_user_messages:
        words = re.sub(r"\s+", " ", message).strip().split(" ")
        pieces.append(" ".join(words[:SUMMARY_WORDS_PER_MESSAGE]).rstrip(".,;:!?"))
    if not pieces:
        return ""
    text = "Earlier the visitor asked: " + "; ".join(pieces) + "."
    # Keep the newest pieces when the note is too long.
    while estimate_tokens(text) > SUMMARY_MAX_TOKENS and len(pieces) > 1:
        pieces.pop(0)
        text = "Earlier the visitor asked: " + "; ".join(pieces) + "."
    return limit_to_tokens(text, SUMMARY_MAX_TOKENS)
