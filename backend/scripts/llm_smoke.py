"""Manual check of the LLM gateway against the real providers.

Usage (from the backend directory, with keys in the environment or in .env):

    uv run python -m scripts.llm_smoke                  # every provider that has a key
    uv run python -m scripts.llm_smoke --provider groq  # one provider

For each provider it sends a plain question twice (the second call should report cached prompt
tokens on Groq), then a structured extraction request, and prints provider, model, tokens,
cached tokens and latency. The exit code is 0 only when every selected provider answered with
a real model reply and valid structured output. Nothing is written to the database.

Run it before launch and whenever a model name or key changes, and re-check the limits page
of each provider: free tier limits change and are stored in app_settings.
"""

import argparse
import asyncio
import sys

from pydantic import BaseModel
from redis.asyncio import Redis

from app.chat.budget import Purpose
from app.chat.llm_gateway import LlmGateway
from app.chat.types import LlmResult, Message
from app.core.config import Settings, get_settings

QUESTION = "Context: The clinic is open Monday to Friday from 8:00 AM to 6:00 PM.\nQuestion: When are you open?"


class SmokeExtraction(BaseModel):
    service: str | None
    dentist: str | None
    date_expr: str | None
    time_pref: str | None


def describe(label: str, result: LlmResult) -> str:
    if result.degraded:
        return f"  {label:<10} FAILED (no model answered; the gateway returned its fallback)"
    return (
        f"  {label:<10} ok  provider={result.provider} model={result.model} "
        f"prompt={result.prompt_tokens} completion={result.completion_tokens} "
        f"cached={result.cached_tokens} latency={result.latency_ms} ms\n"
        f"             reply: {result.text[:160]!r}"
    )


async def check_provider(gateway: LlmGateway, name: str) -> bool:
    print(f"{name} ({gateway.providers[name].model})")
    ok = True
    for label in ("plain", "plain again"):
        result = await gateway.complete(
            [Message("user", QUESTION)], 160, purpose=Purpose.FAQ_ANSWER, force_provider=name
        )
        print(describe(label, result))
        ok = ok and not result.degraded
    extraction = await gateway.complete(
        [Message("user", "Book a cleaning next Tuesday morning with Dr Patel.")],
        80,
        SmokeExtraction,
        purpose=Purpose.ENTITY_EXTRACTION,
        force_provider=name,
    )
    print(describe("structured", extraction))
    if extraction.parsed is not None:
        print(f"             parsed: {extraction.parsed.model_dump()}")
    return ok and not extraction.degraded and extraction.parsed is not None


async def run(gateway: LlmGateway, only: str | None = None) -> int:
    names = [n for n in ("groq", "gemini") if n in gateway.providers and only in (None, n)]
    if not names:
        print(
            "No provider is configured. Set GROQ_API_KEY and GROQ_MODEL, or GEMINI_API_KEY and GEMINI_MODEL."
        )
        return 2
    results = [await check_provider(gateway, name) for name in names]
    print("PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


async def main(settings: Settings, only: str | None) -> int:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return await run(LlmGateway(settings=settings, redis=redis), only)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["groq", "gemini"])
    sys.exit(asyncio.run(main(get_settings(), parser.parse_args().provider)))
