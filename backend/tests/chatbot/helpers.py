"""Small helpers shared by the conversation tests."""

import re
from typing import Any

from tests.auth.conftest import Ctx
from tests.chatbot.conftest import Conversation, reply_named


def first(reply: dict[str, Any], kind: str) -> dict[str, str]:
    """The first button of the given kind."""
    for option in reply["quick_replies"]:
        if option["kind"] == kind:
            return dict(option)
    raise AssertionError(f"no {kind} button in {[q['label'] for q in reply['quick_replies']]}")


def kinds(reply: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in reply["quick_replies"]]


def last_code(ctx: Ctx) -> str:
    match = re.search(r"code is (\d{6})", ctx.mailer.outbox[-1].body)
    assert match, ctx.mailer.outbox[-1].body
    return match.group(1)


async def click_first(convo: Conversation, kind: str) -> dict[str, Any]:
    option = first(convo.last, kind)
    return await convo.click(option["kind"], option["value"], option["label"])


async def reach_time_step(
    convo: Conversation, service: str = "Cleaning", dentist: str = "No preference"
) -> dict[str, Any]:
    """Click through service, dentist and day, and stop at the list of times."""
    await convo.press("Book an appointment")
    await convo.press(service)
    if convo.last["step"] == "dentist":
        await convo.press(dentist)
    assert convo.last["step"] == "day", convo.last
    await click_first(convo, "date")
    assert convo.last["step"] == "time", convo.last
    return convo.last


async def book_as_guest(convo: Conversation, ctx: Ctx, email: str) -> dict[str, Any]:
    """The whole guest booking by clicks and short answers. Returns the final reply."""
    await reach_time_step(convo)
    await click_first(convo, "slot")
    assert convo.last["step"] == "name"
    await convo.say("Jordan Lee")
    await convo.say(email)
    await convo.press("Skip")
    await convo.press("I agree")
    assert convo.last["step"] == "confirm"
    await convo.press("Confirm")
    assert convo.last["step"] == "otp"
    return await convo.say(last_code(ctx))


__all__ = [
    "book_as_guest",
    "click_first",
    "first",
    "kinds",
    "last_code",
    "reach_time_step",
    "reply_named",
]
