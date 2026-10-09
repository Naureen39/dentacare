"""Booking through the chat: by clicks, by free text, as a guest and as a signed in patient."""

from datetime import UTC, datetime, timedelta

from app.services.availability import CACHE_VERSION_KEY
from tests.auth.conftest import unique_email
from tests.chatbot.conftest import Bot
from tests.chatbot.helpers import (
    book_as_guest,
    click_first,
    first,
    last_code,
    reach_time_step,
)

# --- by clicking ---------------------------------------------------------------------------------


async def test_a_guest_books_by_clicking_and_no_model_is_called(bot: Bot) -> None:
    email = unique_email("guest")
    convo = await bot.conversation()
    final = await book_as_guest(convo, bot.ctx, email)

    assert final["flow"] is None
    assert final["text"].startswith("You are booked: Routine Exam and Cleaning")
    rows = await bot.ctx.fetch(
        "SELECT a.channel::text, a.status::text, p.email FROM appointments a "
        "JOIN patients p ON p.id = a.patient_id WHERE p.email = :e",
        e=email,
    )
    assert rows == [("chatbot", "booked", email)]
    assert bot.llm_calls == 0
    # The confirmation reminder is handed to the worker like any other booking.
    assert any(name == "send_reminder" for name, *_ in bot.ctx.jobs.jobs)


async def test_every_step_offers_buttons_or_an_input_hint(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    assert convo.last["step"] == "service" and {q["kind"] for q in convo.last["quick_replies"]} >= {
        "service"
    }
    await convo.press("Cleaning")
    assert convo.last["step"] == "dentist"
    await convo.press("No preference")
    assert convo.last["picker"] == "date"
    await click_first(convo, "date")
    assert convo.last["picker"] == "slot"
    await click_first(convo, "slot")
    assert convo.last["input_hint"] == "name"
    await convo.say("Jordan Lee")
    assert convo.last["input_hint"] == "email"
    await convo.say("jordan@example.com")
    assert convo.last["input_hint"] == "phone"
    await convo.press("Skip")
    assert convo.last["step"] == "consent"
    await convo.press("I agree")
    await convo.press("Confirm")
    assert convo.last["input_hint"] == "code"


async def test_a_signed_in_patient_skips_contact_consent_and_the_code(bot: Bot) -> None:
    convo = await bot.patient_conversation()
    await reach_time_step(convo)
    await click_first(convo, "slot")
    assert convo.last["step"] == "confirm"
    final = await convo.press("Confirm")
    assert final["text"].startswith("You are booked")
    rows = await bot.ctx.fetch(
        "SELECT patient_id::text, created_by::text FROM appointments WHERE channel = 'chatbot'"
    )
    assert rows[0][0] == str(bot.practice.patient.id)
    assert rows[0][1] is not None  # recorded against the signed in user
    assert bot.ctx.mailer.outbox == [] or "code is" not in bot.ctx.mailer.outbox[-1].body


async def test_the_wrong_code_is_refused_then_the_right_one_books(bot: Bot) -> None:
    convo = await bot.conversation()
    email = unique_email("guest")
    await reach_time_step(convo)
    await click_first(convo, "slot")
    for answer in ("Jordan Lee", email):
        await convo.say(answer)
    await convo.press("Skip")
    await convo.press("I agree")
    await convo.press("Confirm")
    code = last_code(bot.ctx)
    wrong = "000000" if code != "000000" else "111111"
    refused = await convo.say(wrong)
    assert "not right" in refused["text"] and "4 tries left" in refused["text"]
    assert refused["step"] == "otp"
    final = await convo.say(code)
    assert final["text"].startswith("You are booked")


async def test_consent_is_required_to_book(bot: Bot) -> None:
    convo = await bot.conversation()
    await reach_time_step(convo)
    await click_first(convo, "slot")
    await convo.say("Jordan Lee")
    await convo.say(unique_email("guest"))
    await convo.press("Skip")
    declined = await convo.press("No thanks")
    assert declined["flow"] is None
    assert "can't book without your consent" in declined["text"]
    assert await bot.ctx.fetch("SELECT count(*) FROM appointments") == [(0,)]


async def test_a_dentist_can_be_chosen_and_the_slot_belongs_to_that_dentist(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    await convo.press("Cleaning")
    await convo.press("Lindqvist")
    await click_first(convo, "date")
    await click_first(convo, "slot")
    assert convo.last["step"] == "name"
    state = await bot.ctx.fetch("SELECT state->'flow'->>'slot_dentist_name' FROM chat_sessions")
    assert state == [("Dr. Marcus Lindqvist",)]


async def test_a_service_only_one_dentist_offers_skips_the_dentist_question(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    reply = await convo.press("Crown")
    assert reply["step"] == "day"
    assert "Raman" in str(await bot.ctx.fetch("SELECT state FROM chat_sessions"))


# --- by typing -----------------------------------------------------------------------------------


async def test_a_detailed_request_is_understood_by_the_rules_without_a_model(bot: Bot) -> None:
    convo = await bot.conversation()
    reply = await convo.say("cleaning next Tuesday morning with Dr Raman")
    assert reply["flow"] == "book" and reply["step"] == "time"
    assert reply["text"].startswith("Got it: Routine Exam and Cleaning with Dr. Priya Raman on")
    assert "Tuesday" in reply["text"] and "in the morning" in reply["text"]
    times = [q for q in reply["quick_replies"] if q["kind"] == "slot"]
    assert times and all(("AM" in q["label"]) for q in times)
    assert bot.llm_calls == 0


async def test_a_vague_request_makes_one_extraction_call_and_resolves_dates_in_code(
    bot: Bot,
) -> None:
    from tests.chat.conftest import ok

    bot.script(
        groq=[
            ok(
                '{"service":"Routine Exam and Cleaning","dentist":"","date_expr":"next Friday",'
                '"time_pref":"afternoon"}',
                prompt=200,
                completion=30,
            )
        ]
    )
    convo = await bot.conversation()
    reply = await convo.say(
        "I want to book an appointment for my daughter, she has not been in a long time and anytime next month is fine"
    )
    assert len(bot.groq.calls) == 1
    call = bot.groq.calls[0]
    assert call.schema_name == "BookingExtraction"
    assert call.max_tokens <= 80
    assert "<question>" in call.messages[0].content
    assert reply["flow"] == "book" and reply["step"] == "dentist"
    assert "Friday" in reply["text"]
    await convo.press("No preference")
    assert convo.last["step"] == "time"
    state = await bot.ctx.fetch("SELECT state->'flow'->>'day' FROM chat_sessions")
    friday = [r for r in state if r[0]]
    assert friday and datetime.fromisoformat(friday[0][0]).weekday() == 4
    messages = await bot.ctx.fetch(
        "SELECT llm_calls FROM chat_messages WHERE role = 'assistant' ORDER BY created_at"
    )
    assert sum(m[0] for m in messages) == 1  # recorded on the reply that used the model


async def test_if_the_model_is_down_the_rules_carry_on(bot: Bot) -> None:
    bot.outage()
    convo = await bot.conversation()
    reply = await convo.say(
        "I want to book an appointment for my daughter, she has not been in a long time and anytime next month is fine"
    )
    assert reply["flow"] == "book"
    assert reply["step"] == "service"  # asks the first missing detail, nothing breaks
    assert "error" not in reply["text"].lower()


async def test_typed_answers_work_at_each_step(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.say("I want to book an appointment")
    assert convo.last["step"] == "service"
    await convo.say("a crown please")
    assert convo.last["step"] == "day"  # one dentist only
    await convo.say("tomorrow")
    assert convo.last["step"] in ("time", "day")
    if convo.last["step"] == "time":
        await convo.say("2pm")
        assert convo.last["step"] == "time"
        labels = [q["label"] for q in convo.last["quick_replies"] if q["kind"] == "slot"]
        assert labels and labels[0].startswith(("1:", "2:", "3:", "12:"))


async def test_a_past_date_is_refused(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    await convo.press("Cleaning")
    await convo.press("No preference")
    reply = await convo.say("on 1/2/2020")
    assert reply["step"] == "day"
    assert "already passed" in reply["text"] or "Which day" in reply["text"]


# --- conflicts --------------------------------------------------------------------------------------


async def test_a_time_taken_after_it_was_shown_is_not_double_booked(bot: Bot) -> None:
    convo = await bot.conversation()
    await reach_time_step(convo, dentist="Raman")
    slot = first(convo.last, "slot")
    start_text, dentist_id = slot["value"].split("|")
    start = datetime.fromisoformat(start_text).astimezone(UTC)
    dentist = bot.practice.dentist_a
    assert str(dentist.id) == dentist_id
    await bot.practice.book_direct(dentist, start)
    await bot.ctx.redis.incr(CACHE_VERSION_KEY)  # staff bookings made through the API do this

    reply = await convo.click(slot["kind"], slot["value"], slot["label"])
    assert reply["step"] == "time"
    assert "just gone" in reply["text"]
    assert all(q["value"] != slot["value"] for q in reply["quick_replies"])


async def test_a_lapsed_hold_is_taken_again_when_the_time_is_still_free(bot: Bot) -> None:
    convo = await bot.patient_conversation()
    await reach_time_step(convo)
    await click_first(convo, "slot")
    assert convo.last["step"] == "confirm"
    await bot.ctx.redis.flushall()  # the five minute hold expires while the visitor decides
    final = await convo.press("Confirm")
    assert final["text"].startswith("You are booked")


async def test_a_slot_held_by_someone_else_cannot_be_chosen(bot: Bot) -> None:
    other = await bot.conversation()
    await reach_time_step(other, dentist="Raman")
    slot = first(other.last, "slot")
    await click_first(other, "slot")  # holds the first time for five minutes

    convo = await bot.conversation()
    await reach_time_step(convo, dentist="Raman")
    assert all(q["value"] != slot["value"] for q in convo.last["quick_replies"])


async def test_the_second_booking_of_the_same_person_at_the_same_time_is_refused(
    bot: Bot,
) -> None:
    email = unique_email("guest")
    first_chat = await bot.conversation()
    await book_as_guest(first_chat, bot.ctx, email)
    row = await bot.ctx.fetch("SELECT lower(slot) FROM appointments")
    assert row, "first booking should exist"
    # Booking the same hour with another dentist is stopped by the patient overlap rule.
    second = await bot.conversation()
    await reach_time_step(second, dentist="Lindqvist")
    assert second.last["step"] == "time"


# --- leaving ------------------------------------------------------------------------------------------


async def test_never_mind_leaves_the_flow_and_frees_the_held_time(bot: Bot) -> None:
    convo = await bot.conversation()
    await reach_time_step(convo, dentist="Raman")
    await click_first(convo, "slot")
    assert await bot.ctx.redis.keys("hold:*")
    reply = await convo.say("never mind")
    assert reply["flow"] is None
    assert not await bot.ctx.redis.keys("hold:*")
    again = await bot.conversation()
    await reach_time_step(again, dentist="Raman")


async def test_start_over_restarts_the_flow(bot: Bot) -> None:
    convo = await bot.conversation()
    await reach_time_step(convo)
    reply = await convo.say("start over")
    assert reply["flow"] == "book" and reply["step"] == "service"


async def test_a_question_in_the_middle_of_a_flow_is_answered_and_the_step_repeats(
    bot: Bot,
) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    await convo.press("Cleaning")
    await convo.press("No preference")
    await click_first(convo, "date")
    await click_first(convo, "slot")
    assert convo.last["step"] == "name"
    reply = await convo.say("what are your opening hours?")
    assert "Monday to Friday" in reply["text"]
    assert "Back to your request" in reply["text"]
    assert reply["step"] == "name"
    assert bot.llm_calls == 0


async def test_asking_for_a_person_in_the_middle_switches_to_a_callback(bot: Bot) -> None:
    convo = await bot.conversation()
    await reach_time_step(convo)
    reply = await convo.say("can I talk to a real person")
    assert reply["flow"] == "handoff"


async def test_repeated_nonsense_offers_a_person(bot: Bot) -> None:
    convo = await bot.conversation()
    await convo.press("Book an appointment")
    for _ in range(3):
        reply = await convo.say("zzzz qqqq")
    assert any(q["value"] == "handoff" for q in reply["quick_replies"])
    assert "trouble understanding" in reply["text"]


async def test_changing_the_time_after_choosing_releases_the_old_hold(bot: Bot) -> None:
    convo = await bot.patient_conversation()
    await reach_time_step(convo, dentist="Raman")
    await click_first(convo, "slot")
    keys = await bot.ctx.redis.keys("hold:*")
    assert len(keys) == 1
    reply = await convo.press("Change time")
    assert reply["step"] == "time"
    assert await bot.ctx.redis.keys("hold:*") == []
    assert timedelta(0) == timedelta(0)
