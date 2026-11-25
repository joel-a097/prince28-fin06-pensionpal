import httpx
import pytest

from pensionpal.llm.gateway import (
    CircuitBreaker,
    FakeLLM,
    LLMError,
    LLMGateway,
    LLMResult,
    LLMUnavailable,
    OpenAICompatProvider,
    Reply,
    cost_inr,
    estimate_tokens,
)

MESSAGES = [{"role": "user", "content": "hello"}]


def test_cost_inr_and_unknown_model():
    assert cost_inr("openai/gpt-oss-20b", 1_000_000, 1_000_000, 95) == 35.625
    assert cost_inr("unlisted", 100, 100, 95) == 0


def test_estimate_tokens_has_minimum_one():
    assert estimate_tokens("") == 1
    assert estimate_tokens("12345678") == 2


def test_breaker_starts_closed_and_opens_after_threshold():
    breaker = CircuitBreaker(threshold=2, cooldown=30)
    assert breaker.state == "closed" and breaker.allow()
    breaker.failure()
    assert breaker.state == "closed"
    breaker.failure()
    assert breaker.state == "open" and not breaker.allow()


def test_breaker_half_open_success_closes():
    now = [0.0]
    breaker = CircuitBreaker(threshold=1, cooldown=30, clock=lambda: now[0])
    breaker.failure()
    now[0] = 30
    assert breaker.state == "half-open" and breaker.allow()
    breaker.success()
    assert breaker.state == "closed" and breaker.failures == 0


@pytest.mark.asyncio
async def test_generate_uses_first_provider_and_records_usage():
    rows = []

    async def record(row):
        rows.append(row)

    gateway = LLMGateway([FakeLLM("gemini", "flash", ["answer"])], recorder=record)
    result = await gateway.generate(MESSAGES)
    assert result.text == "answer"
    assert result.provider == "gemini" and not result.fallback_used
    assert rows[0]["status"] == "ok" and rows[0]["tokens_in"] == 12


@pytest.mark.asyncio
async def test_retryable_error_retries_and_respects_retry_after():
    waits = []
    provider = FakeLLM(
        "gemini", script=[LLMError("busy", retryable=True, retry_after=2), "ok"]
    )
    gateway = LLMGateway([provider], sleep=lambda delay: _append(waits, delay))
    result = await gateway.generate(MESSAGES)
    assert result.text == "ok" and result.attempts == 2
    assert waits == [2]


async def _append(values, value):
    values.append(value)


@pytest.mark.asyncio
async def test_retry_wait_is_capped():
    waits = []
    provider = FakeLLM(
        "gemini", script=[LLMError("busy", retryable=True, retry_after=200), "ok"]
    )
    await LLMGateway(
        [provider], sleep=lambda delay: _append(waits, delay), max_attempts=2
    ).generate(MESSAGES)
    assert waits == [20]


@pytest.mark.asyncio
async def test_nonretryable_error_falls_back_without_retry():
    primary = FakeLLM("gemini", script=[LLMError("bad key", retryable=False)])
    fallback = FakeLLM("groq", script=["backup"])
    result = await LLMGateway([primary, fallback]).generate(MESSAGES)
    assert primary.calls == 1
    assert result.text == "backup" and result.fallback_used


@pytest.mark.asyncio
async def test_retryable_error_falls_back_after_attempts():
    primary = FakeLLM(
        "gemini",
        script=[LLMError("busy", retryable=True), LLMError("busy", retryable=True)],
    )
    fallback = FakeLLM("groq", script=["backup"])
    result = await LLMGateway([primary, fallback], sleep=_no_wait).generate(MESSAGES)
    assert primary.calls == 2 and result.provider == "groq"


async def _no_wait(_delay):
    return None


@pytest.mark.asyncio
async def test_open_breaker_skips_provider():
    primary = FakeLLM("gemini")
    fallback = FakeLLM("groq", script=["backup"])
    gateway = LLMGateway([primary, fallback])
    gateway.breakers["gemini"].failure()
    gateway.breakers["gemini"].failure()
    gateway.breakers["gemini"].failure()
    result = await gateway.generate(MESSAGES)
    assert primary.calls == 0 and result.fallback_used


@pytest.mark.asyncio
async def test_provider_failures_are_each_recorded():
    rows = []

    async def record(row):
        rows.append(row)

    primary = FakeLLM("gemini", script=[LLMError("bad key", retryable=False)])
    fallback = FakeLLM("groq", script=["ok"])
    await LLMGateway([primary, fallback], recorder=record).generate(MESSAGES)
    assert [(r["provider"], r["status"]) for r in rows] == [
        ("gemini", "error"),
        ("groq", "ok"),
    ]
    assert rows[0]["tokens_in"] == rows[0]["tokens_out"] == 0
    assert rows[0]["cost_inr"] == 0 and rows[0]["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_recorder_failure_does_not_break_answer():
    async def broken(_row):
        raise RuntimeError("database down")

    result = await LLMGateway(
        [FakeLLM("gemini", script=["still answers"])], recorder=broken
    ).generate(MESSAGES)
    assert result.text == "still answers"


@pytest.mark.asyncio
async def test_missing_provider_usage_is_estimated():
    class NoUsage(FakeLLM):
        async def generate(self, messages, *, temperature=0.2):
            return Reply("some words", 0, 0)

    result = await LLMGateway([NoUsage("gemini")]).generate(MESSAGES)
    assert result.tokens_in >= 1 and result.tokens_out >= 1


@pytest.mark.asyncio
async def test_stream_yields_pieces_and_final_usage():
    events = [
        event
        async for event in LLMGateway(
            [FakeLLM("gemini", script=["hello there"])]
        ).stream(MESSAGES)
    ]
    assert events[:-1] == ["hello ", "there "]
    assert isinstance(events[-1], LLMResult)
    assert events[-1].tokens_out == 2


@pytest.mark.asyncio
async def test_stream_falls_back_before_any_piece():
    primary = FakeLLM("gemini", script=[LLMError("down", retryable=False)])
    fallback = FakeLLM("groq", script=["backup answer"])
    events = [event async for event in LLMGateway([primary, fallback]).stream(MESSAGES)]
    assert events[-1].provider == "groq" and events[-1].fallback_used


@pytest.mark.asyncio
async def test_stream_does_not_switch_after_partial_answer():
    primary = FakeLLM(
        "gemini",
        script=[("partial", LLMError("cut off", retryable=True))],
    )
    fallback = FakeLLM("groq", script=["must not be shown"])
    stream = LLMGateway([primary, fallback]).stream(MESSAGES)
    assert await anext(stream) == "Half "
    with pytest.raises(LLMUnavailable, match="failed mid-answer"):
        async for _ in stream:
            pass
    assert fallback.calls == 0


async def anext(stream):
    return await stream.__anext__()


@pytest.mark.asyncio
async def test_empty_gateway_is_unavailable():
    with pytest.raises(LLMUnavailable, match="no LLM provider"):
        await LLMGateway([]).generate(MESSAGES)


@pytest.mark.asyncio
async def test_openai_compatible_provider_builds_chat_body():
    provider = OpenAICompatProvider("test", "https://example.test/v1/", "secret", "m")
    assert provider._url == "https://example.test/v1/chat/completions"
    assert provider._body(MESSAGES, 0.3, True)["stream_options"] == {
        "include_usage": True
    }
    await provider.aclose()


def test_http_error_retry_classification():
    assert (
        OpenAICompatProvider._error(
            httpx.Response(429, headers={"retry-after": "3"})
        ).retry_after
        == 3
    )
    assert OpenAICompatProvider._error(httpx.Response(500)).retryable
    assert not OpenAICompatProvider._error(httpx.Response(401)).retryable


@pytest.mark.asyncio
async def test_real_http_adapter_parses_reply_without_external_network():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        "test", "https://example.test/v1", "secret", "m", client=client
    )
    reply = await provider.generate(MESSAGES)
    assert (reply.text, reply.tokens_in, reply.tokens_out) == ("hello", 4, 1)
    await client.aclose()


@pytest.mark.asyncio
async def test_real_http_adapter_parses_stream_and_usage_without_network():
    body = (
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n'
        "data: [DONE]\n\n"
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, text=body))
    )
    provider = OpenAICompatProvider(
        "test", "https://example.test/v1", "secret", "m", client=client
    )
    usage = Reply()
    pieces = [piece async for piece in provider.stream(MESSAGES, usage)]
    assert pieces == ["Hi"]
    assert (usage.tokens_in, usage.tokens_out) == (3, 1)
    await client.aclose()


@pytest.mark.asyncio
async def test_build_gateway_omits_unconfigured_providers(settings):
    from pensionpal.llm.gateway import build_gateway

    settings.gemini_api_key = ""
    settings.groq_api_key = ""
    assert build_gateway(settings).providers == []
