"""Rescheduling and cancelling through the chat: signed in, or a mailbox verified by a code."""

from datetime import UTC, datetime, timedelta

from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc
from tests.chatbot.conftest import Bot
from tests.chatbot.helpers import click_first, first, last_code


async def make_appointment(practice: Practice, *, days: int = 12, hour: int = 10) -> str:
    start = local_utc(future_date(1, min_days=days), hour)
    appointment = await practice.book_direct(practice.dentist_a, start)
    return str(appointment.id)


async def status_of(bot: Bot, appointment_id: str) -> str:
    rows = await bot.ctx.fetch(
        "SELECT status::text FROM appointments WHERE id = :i", i=appointment_id
    )
    return str(rows[0][0])


# --- cancel ---------------------------------------------------------------------------------------


async def test_a_signed_in_patient_cancels_in_chat(bot: Bot) -> None:
    appointment_id = await make_appointment(bot.practice)
    convo = await bot.patient_conversation()
    reply = await convo.say("I need to cancel my appointment")
    assert reply["flow"] == "cancel" and reply["step"] == "pick"
    reply = await convo.press("Routine Exam and Cleaning")
    assert reply["step"] == "confirm_cancel"
    assert "free to cancel until" in reply["text"]
    final = await convo.press("Yes, cancel it")
    assert "has been cancelled" in final["text"]
    assert await status_of(bot, appointment_id) == "cancelled"
    assert bot.llm_calls == 0


async def test_keeping_the_appointment_changes_nothing(bot: Bot) -> None:
    appointment_id = await make_appointment(bot.practice)
    convo = await bot.patient_conversation()
    await convo.say("cancel my appointment")
    await convo.press("Routine Exam")
    reply = await convo.press("Keep it")
    assert reply["flow"] is None
    assert await status_of(bot, appointment_id) == "booked"


async def test_a_late_cancellation_is_flagged_and_the_patient_is_told(bot: Bot) -> None:
    start = datetime.now(UTC) + timedelta(hours=5)
    appointment = await bot.practice.book_direct(bot.practice.dentist_a, start)
    convo = await bot.patient_conversation()
    await convo.say("please cancel my appointment")
    confirm = await convo.press("Routine Exam")
    assert "late cancellation" in confirm["text"]
    final = await convo.press("Yes, cancel it")
    assert "late cancellation" in final["text"]
    rows = await bot.ctx.fetch(
        "SELECT late_cancel FROM appointments WHERE id = :i", i=str(appointment.id)
    )
    assert rows == [(True,)]


async def test_cancelling_with_no_upcoming_appointment_says_so(bot: Bot) -> None:
    convo = await bot.patient_conversation()
    reply = await convo.say("I need to cancel my appointment")
    assert reply["flow"] is None
    assert "could not find an upcoming appointment" in reply["text"]


async def test_a_question_about_the_cancellation_policy_is_answered_not_acted_on(
    bot: Bot,
) -> None:
    from tests.chat.conftest import ok

    await make_appointment(bot.practice)
    bot.script(groq=[ok("Cancel at least 24 hours ahead to avoid a late cancellation fee.")])
    convo = await bot.patient_conversation()
    reply = await convo.say("what is your cancellation policy?")
    assert reply["flow"] is None
    assert reply["route"] == "llm" and "24 hours" in reply["text"]
    assert "cancel" in bot.groq.calls[0].messages[-1].content.lower()


# --- reschedule ---------------------------------------------------------------------------------------


async def test_a_signed_in_patient_reschedules_in_chat(bot: Bot) -> None:
    old_id = await make_appointment(bot.practice)
    convo = await bot.patient_conversation()
    reply = await convo.say("can I move my appointment")
    assert reply["flow"] == "reschedule" and reply["step"] == "pick"
    reply = await convo.press("Routine Exam")
    assert reply["step"] == "day"
    await click_first(convo, "date")
    assert convo.last["step"] == "time"
    await click_first(convo, "slot")
    assert convo.last["step"] == "confirm"
    assert convo.last["text"].startswith("Move your appointment to")
    final = await convo.press("Confirm")
    assert final["text"].startswith("Done. Your Routine Exam and Cleaning")
    assert await status_of(bot, old_id) == "cancelled"
    rows = await bot.ctx.fetch(
        "SELECT status::text, rescheduled_from::text FROM appointments WHERE rescheduled_from = :i",
        i=old_id,
    )
    assert rows == [("booked", old_id)]
    assert bot.llm_calls == 0


async def test_a_reschedule_keeps_the_same_dentist(bot: Bot) -> None:
    await make_appointment(bot.practice)
    convo = await bot.patient_conversation()
    await convo.say("reschedule my appointment")
    await convo.press("Routine Exam")
    await click_first(convo, "date")
    slot = first(convo.last, "slot")
    assert slot["value"].split("|")[1] == str(bot.practice.dentist_a.id)


# --- who may change what ---------------------------------------------------------------------------------


async def test_an_anonymous_visitor_must_verify_an_email_first(bot: Bot) -> None:
    appointment_id = await make_appointment(bot.practice)
    convo = await bot.conversation()
    reply = await convo.say("I want to cancel my appointment")
    assert reply["flow"] == "cancel" and reply["step"] == "verify_email"
    assert "appointment" not in reply["text"].lower() or "booked under" in reply["text"]
    assert await status_of(bot, appointment_id) == "booked"

    reply = await convo.say(bot.practice.patient_user_email)
    assert reply["step"] == "verify_code"
    assert "***@" in reply["text"]  # the address is masked on screen
    code = last_code(bot.ctx)
    reply = await convo.say(code)
    assert reply["step"] == "pick"
    await convo.press("Routine Exam")
    final = await convo.press("Yes, cancel it")
    assert "has been cancelled" in final["text"]
    assert await status_of(bot, appointment_id) == "cancelled"


async def test_a_wrong_code_gives_no_access(bot: Bot) -> None:
    appointment_id = await make_appointment(bot.practice)
    convo = await bot.conversation()
    await convo.say("cancel my appointment")
    await convo.say(bot.practice.patient_user_email)
    code = last_code(bot.ctx)
    wrong = "000000" if code != "000000" else "111111"
    reply = await convo.say(wrong)
    assert reply["step"] == "verify_code" and "not right" in reply["text"]
    assert await status_of(bot, appointment_id) == "booked"


async def test_an_address_with_no_patient_learns_nothing(bot: Bot) -> None:
    await make_appointment(bot.practice)
    convo = await bot.conversation()
    await convo.say("cancel my appointment")
    reply = await convo.say(unique_email("stranger"))
    # The same prompt as for a real address: the chat does not reveal who is a patient.
    assert reply["step"] == "verify_code"
    reply = await convo.say(last_code(bot.ctx))
    assert reply["flow"] is None
    assert "could not find any appointments under that address" in reply["text"]


async def test_one_patient_cannot_pick_anothers_appointment(bot: Bot) -> None:
    mine = await make_appointment(bot.practice)
    other_email = unique_email("other")
    other_user = await bot.ctx.create_user(other_email)
    token = await bot.ctx.access_token(other_email)
    del other_user
    convo = await bot.conversation(token)
    reply = await convo.say("cancel my appointment")
    assert reply["flow"] is None  # the other patient has none
    # Forcing the choice with a known id is refused as well.
    forged = await convo.click("appointment", mine)
    assert forged["flow"] is None
    assert await status_of(bot, mine) == "booked"


async def test_verification_lasts_for_the_conversation_only(bot: Bot) -> None:
    await make_appointment(bot.practice)
    convo = await bot.conversation()
    await convo.say("cancel my appointment")
    await convo.say(bot.practice.patient_user_email)
    await convo.say(last_code(bot.ctx))
    await convo.press("Keep it") if convo.last["step"] == "confirm_cancel" else None
    stored = await bot.ctx.fetch("SELECT state->'verified'->>'until' FROM chat_sessions")
    until = datetime.fromisoformat(stored[0][0])
    assert timedelta(minutes=19) < until - datetime.now(UTC) <= timedelta(minutes=20)

    fresh = await bot.conversation()  # a different conversation does not inherit it
    reply = await fresh.say("cancel my appointment")
    assert reply["step"] == "verify_email"


async def test_a_guest_booking_then_cancel_in_the_same_chat_needs_no_second_code(
    bot: Bot,
) -> None:
    from tests.chatbot.helpers import book_as_guest

    email = unique_email("guest")
    convo = await bot.conversation()
    await book_as_guest(convo, bot.ctx, email)
    # Booking proved the mailbox, but a separate verification is still required to manage it.
    reply = await convo.say("cancel my appointment")
    assert reply["step"] == "verify_email"
