"""Token use over 50 sample conversations.

The providers are scripted, so this cannot say what a real model will use. It measures what the
application decides: how many conversations and turns reach a model at all, and what they cost
when every model call is as large as its purpose allows (700 prompt and 160 completion tokens, the
ceilings of the budget table). The real provider averages need API keys and are reported
separately in docs/chatbot-quality.md.
"""

from app.db.enums import UserRole
from tests.auth.conftest import unique_email
from tests.chat.conftest import ok
from tests.chatbot.conftest import Bot
from tests.chatbot.test_api_and_metrics import CORPUS

FOLLOW_UPS = [
    ("what are your opening hours", "thanks a lot"),
    ("where are you located", "is there parking"),
    ("how much is a porcelain crown", "do you offer payment plans"),
    ("hello", "what is your cancellation policy"),
    ("does a root canal hurt", "thanks a lot"),
    ("is there parking", "are you open on sunday"),
    ("how long does teeth whitening last", "thanks a lot"),
    ("hi there", "what are your prices"),
    ("can I pay with HSA", "thanks a lot"),
    ("what are your opening hours", "where are you located"),
    ("how do I brush properly", "thanks a lot"),
    ("do you offer payment plans", "can I pay with HSA"),
    ("hello", "how much is a porcelain crown"),
    ("are you open on sunday", "thanks a lot"),
    ("what is your cancellation policy", "thanks a lot"),
    ("where are you located", "what are your opening hours"),
    ("what are your prices", "thanks a lot"),
    ("hello", "does a root canal hurt"),
    ("is there parking", "thanks a lot"),
    ("how long does teeth whitening last", "what are your prices"),
    ("hi there", "where are you located"),
    ("how do I brush properly", "does a root canal hurt"),
    ("what is the capital of France", "thanks a lot"),
    ("tell me a joke", "hello"),
    ("I lost a filling", "thanks a lot"),
]


async def test_fifty_conversations_stay_inside_the_token_gates(bot: Bot) -> None:
    bot.script(groq=[ok("Most people feel little discomfort.", prompt=700, completion=160)] * 200)
    for message in CORPUS:
        await (await bot.conversation()).say(message)
    for first, second in FOLLOW_UPS:
        convo = await bot.conversation()
        await convo.say(first)
        await convo.say(second)

    admin_email = unique_email("admin")
    await bot.ctx.create_user(admin_email, UserRole.ADMIN)
    headers = bot.ctx.auth(await bot.ctx.access_token(admin_email))
    response = await bot.ctx.client.get("/api/v1/admin/chat/metrics?days=7", headers=headers)
    assert response.status_code == 200, response.text
    metrics = response.json()

    conversations = len(CORPUS) + len(FOLLOW_UPS)
    assert conversations == 50
    assert metrics["turns"] >= len(CORPUS) + 2 * len(FOLLOW_UPS)
    assert metrics["zero_llm_share"] >= 0.70, metrics
    average = metrics["tokens_per_conversation"]
    assert average is not None and average < 1200, metrics
    # Every counted model call is one the scripted provider really received.
    assert metrics["llm_calls"] == len(bot.groq.calls) + len(bot.gemini.calls)
