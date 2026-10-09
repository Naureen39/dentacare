"""The real Groq and Gemini provider classes, driven through their SDKs against fake HTTP.

These tests show exactly what is sent on the wire and how every kind of response is mapped,
without needing API keys.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import httpx2
import openai
import pytest

from app.chat.llm_gateway import GeminiProvider, GroqProvider, build_providers
from app.chat.types import Message, ProviderError, ProviderErrorKind
from app.core.config import Settings

SYSTEM = "SYSTEM PROMPT"
SCHEMA = {
    "type": "object",
    "properties": {"service": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    "required": ["service"],
    "additionalProperties": False,
}
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"


def groq_body(
    content: str | None = "Hello there.", *, finish: str = "stop", cached: int | None = 64
) -> dict[str, Any]:
    usage: dict[str, Any] = {"prompt_tokens": 100, "completion_tokens": 7, "total_tokens": 107}
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": GROQ_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": usage,
    }


class GroqRig:
    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response], **kwargs: Any) -> None:
        self.requests: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            return respond(request)

        client = openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
        self.provider = GroqProvider(
            "test-groq-key", kwargs.pop("model", GROQ_MODEL), GROQ_URL, http_client=client, **kwargs
        )

    @property
    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[-1].content)
        return body

    async def run(self, **kwargs: Any):  # type: ignore[no-untyped-def]
        options: dict[str, Any] = {
            "max_tokens": 80,
            "json_schema": None,
            "schema_name": "reply",
            "timeout": 8.0,
        }
        options.update(kwargs)
        return await self.provider.complete(SYSTEM, [Message("user", "hi")], **options)


# --- Groq: the request -----------------------------------------------------------------------------


async def test_groq_request_uses_the_openai_compatible_endpoint_and_a_bearer_key() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body()))
    await rig.run()
    request = rig.requests[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-groq-key"
    assert request.method == "POST"


async def test_groq_request_has_the_static_system_prompt_first_and_low_temperature() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body()))
    await rig.run()
    body = rig.body
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    assert body["messages"][1] == {"role": "user", "content": "hi"}
    assert body["temperature"] == 0.2 and body["model"] == GROQ_MODEL


async def test_groq_reasoning_model_uses_low_effort_hides_reasoning_and_adds_headroom() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body()), reasoning_headroom=100)
    await rig.run(max_tokens=80)
    body = rig.body
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert body["max_completion_tokens"] == 180  # 80 visible tokens plus room for reasoning
    assert "reasoning_format" not in body  # not supported by these models


async def test_groq_models_without_reasoning_get_no_reasoning_parameters() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body()), model="some/other-model")
    await rig.run(max_tokens=80)
    body = rig.body
    assert "reasoning_effort" not in body and "include_reasoning" not in body
    assert body["max_completion_tokens"] == 80


async def test_groq_structured_output_asks_for_a_strict_json_schema() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body('{"service": null}')))
    await rig.run(json_schema=SCHEMA, schema_name="Extracted")
    assert rig.body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Extracted", "strict": True, "schema": SCHEMA},
    }


async def test_groq_requests_never_carry_tools_or_streaming() -> None:
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body()))
    await rig.run()
    body = rig.body
    assert not ({"tools", "tool_choice", "functions", "stream", "parallel_tool_calls"} & set(body))


# --- Groq: the response ----------------------------------------------------------------------------------


async def test_groq_response_is_mapped_with_cached_tokens_and_headers() -> None:
    headers = {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-limit-tokens": "8000"}
    rig = GroqRig(lambda r: httpx2.Response(200, json=groq_body("Hi!"), headers=headers))
    response = await rig.run()
    assert (
        response.text,
        response.prompt_tokens,
        response.completion_tokens,
        response.cached_tokens,
    ) == ("Hi!", 100, 7, 64)
    assert response.finish_reason == "stop"
    assert response.headers["x-ratelimit-remaining-tokens"] == "7000"


async def test_groq_response_without_cache_details_or_content_is_handled() -> None:
    rig = GroqRig(
        lambda r: httpx2.Response(200, json=groq_body(None, finish="length", cached=None))
    )
    response = await rig.run()
    assert (
        response.text == "" and response.cached_tokens == 0 and response.finish_reason == "length"
    )


# --- Groq: errors ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, ProviderErrorKind.RATE_LIMITED),
        (500, ProviderErrorKind.SERVER_ERROR),
        (502, ProviderErrorKind.SERVER_ERROR),
        (503, ProviderErrorKind.SERVER_ERROR),
        (401, ProviderErrorKind.AUTH),
        (403, ProviderErrorKind.AUTH),
        (400, ProviderErrorKind.BAD_REQUEST),
        (404, ProviderErrorKind.BAD_REQUEST),
        (422, ProviderErrorKind.BAD_REQUEST),
    ],
)
async def test_groq_http_errors_are_classified_and_never_retried_by_the_sdk(
    status: int, kind: ProviderErrorKind
) -> None:
    rig = GroqRig(lambda r: httpx2.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderError) as raised:
        await rig.run()
    assert raised.value.kind is kind and raised.value.status_code == status
    assert len(rig.requests) == 1  # failover is the gateway's job, so the SDK must not retry


async def test_groq_429_carries_retry_after_and_the_rate_limit_headers() -> None:
    headers = {
        "retry-after": "2",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "1.5s",
    }
    rig = GroqRig(
        lambda r: httpx2.Response(429, json={"error": {"message": "slow down"}}, headers=headers)
    )
    with pytest.raises(ProviderError) as raised:
        await rig.run()
    assert raised.value.retry_after == 2.0
    assert raised.value.headers["x-ratelimit-remaining-tokens"] == "0"


async def test_groq_timeouts_and_connection_failures_are_classified() -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as timed_out:
        await GroqRig(slow).run()
    with pytest.raises(ProviderError) as unreachable:
        await GroqRig(down).run()
    assert timed_out.value.kind is ProviderErrorKind.TIMEOUT
    assert unreachable.value.kind is ProviderErrorKind.CONNECTION


# --- Gemini ------------------------------------------------------------------------------------------------


def gemini_body(
    text: str = "Hello there.", *, finish: str = "STOP", thoughts: int = 0
) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": finish}
        ],
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 9,
            "thoughtsTokenCount": thoughts,
            "cachedContentTokenCount": 30,
            "totalTokenCount": 129 + thoughts,
        },
    }


class GeminiRig:
    def __init__(self, respond: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> None:
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return respond(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.provider = GeminiProvider(
            "test-gemini-key", "gemini-test-model", http_client=client, **kwargs
        )

    @property
    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[-1].content)
        return body

    async def run(self, messages: list[Message] | None = None, **kwargs: Any):  # type: ignore[no-untyped-def]
        options: dict[str, Any] = {
            "max_tokens": 80,
            "json_schema": None,
            "schema_name": "reply",
            "timeout": 8.0,
        }
        options.update(kwargs)
        return await self.provider.complete(SYSTEM, messages or [Message("user", "hi")], **options)


async def test_gemini_request_targets_the_model_with_the_key_in_a_header() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body()))
    await rig.run()
    request = rig.requests[0]
    assert (
        str(request.url)
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test-model:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "test-gemini-key"


async def test_gemini_request_maps_the_prompt_roles_and_generation_settings() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body()))
    await rig.run(
        [Message("user", "Hi"), Message("assistant", "Hello"), Message("user", "Prices?")]
    )
    body = rig.body
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM
    assert [(c["role"], c["parts"][0]["text"]) for c in body["contents"]] == [
        ("user", "Hi"),
        ("model", "Hello"),
        ("user", "Prices?"),
    ]
    config = body["generationConfig"]
    assert config["temperature"] == 0.2 and config["maxOutputTokens"] == 80
    assert "responseMimeType" not in config
    assert not ({"tools", "toolConfig"} & set(body))


async def test_gemini_structured_output_requests_json_with_the_schema() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body('{"service": null}')))
    await rig.run(json_schema=SCHEMA)
    config = rig.body["generationConfig"]
    assert (
        config["responseMimeType"] == "application/json" and config["responseJsonSchema"] == SCHEMA
    )


async def test_gemini_thinking_is_switched_off_by_default_and_can_be_left_alone() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body()))
    await rig.run()
    assert rig.body["generationConfig"]["thinkingConfig"] == {"thinking_budget": 0}
    untouched = GeminiRig(lambda r: httpx.Response(200, json=gemini_body()), thinking_budget=-1)
    await untouched.run()
    assert "thinkingConfig" not in untouched.body["generationConfig"]


async def test_gemini_response_is_mapped_and_thinking_tokens_count_as_output() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body("Hi!", thoughts=11)))
    response = await rig.run()
    assert (
        response.text,
        response.prompt_tokens,
        response.completion_tokens,
        response.cached_tokens,
    ) == ("Hi!", 120, 20, 30)
    assert response.finish_reason == "STOP"


async def test_gemini_truncation_is_reported_as_max_tokens() -> None:
    rig = GeminiRig(lambda r: httpx.Response(200, json=gemini_body("partial", finish="MAX_TOKENS")))
    assert (await rig.run()).finish_reason == "MAX_TOKENS"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, ProviderErrorKind.RATE_LIMITED),
        (500, ProviderErrorKind.SERVER_ERROR),
        (503, ProviderErrorKind.SERVER_ERROR),
        (401, ProviderErrorKind.AUTH),
        (403, ProviderErrorKind.AUTH),
        (400, ProviderErrorKind.BAD_REQUEST),
    ],
)
async def test_gemini_http_errors_are_classified(status: int, kind: ProviderErrorKind) -> None:
    body = {"error": {"code": status, "message": "problem", "status": "ERROR"}}
    rig = GeminiRig(lambda r: httpx.Response(status, json=body))
    with pytest.raises(ProviderError) as raised:
        await rig.run()
    assert raised.value.kind is kind and raised.value.status_code == status


async def test_gemini_429_reads_the_suggested_retry_delay() -> None:
    body = {
        "error": {
            "code": 429,
            "message": "Quota exceeded. Please retry in 27.5s.",
            "status": "RESOURCE_EXHAUSTED",
        }
    }
    rig = GeminiRig(lambda r: httpx.Response(429, json=body))
    with pytest.raises(ProviderError) as raised:
        await rig.run()
    assert raised.value.kind is ProviderErrorKind.RATE_LIMITED and raised.value.retry_after == 27.5


async def test_gemini_timeouts_and_connection_failures_are_classified() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as timed_out:
        await GeminiRig(slow).run()
    with pytest.raises(ProviderError) as unreachable:
        await GeminiRig(down).run()
    assert timed_out.value.kind is ProviderErrorKind.TIMEOUT
    assert unreachable.value.kind is ProviderErrorKind.CONNECTION


# --- configuration and structure ----------------------------------------------------------------------------


def test_providers_exist_only_when_a_key_and_model_are_configured() -> None:
    assert build_providers(Settings(env="test", groq_api_key="", gemini_api_key="")) == {}
    only_groq = build_providers(Settings(env="test", groq_api_key="k", groq_model="m"))
    assert list(only_groq) == ["groq"] and only_groq["groq"].model == "m"
    no_model = build_providers(Settings(env="test", gemini_api_key="k", gemini_model=""))
    assert no_model == {}
    both = build_providers(
        Settings(env="test", groq_api_key="k", gemini_api_key="k", gemini_model="g")
    )
    assert set(both) == {"groq", "gemini"}


def test_the_default_groq_endpoint_and_model_match_the_plan() -> None:
    settings = Settings(env="test")
    assert settings.groq_base_url == "https://api.groq.com/openai/v1"
    assert settings.groq_model == "openai/gpt-oss-20b"
    assert settings.gemini_reset_tz == "America/Los_Angeles"


def test_only_the_gateway_module_imports_a_model_sdk() -> None:
    """The gateway is the single place that talks to a language model."""
    root = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if (
            "import openai" in text
            or "from openai" in text
            or "from google import genai" in text
            or "import google.genai" in text
            or "from google.genai" in text
        ):
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == ["chat/llm_gateway.py"]
