"""agent_runner 하네스: JSON 추출, 재시도, 타임아웃, 폴백, 사용량."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from core.agent_runner import (
    JSON_RETRY_INSTRUCTION,
    _extract_json,
    fallback_agent_result,
    load_prompt,
    run_agent,
)
from core.models import AgentResult, AgentUsage, Conviction

VALID_JSON = json.dumps(
    {
        "agent": "financial",
        "score": 7.5,
        "conviction": "positive",
        "summary": "양호한 재무 구조",
        "evidence": [],
        "risks": [],
        "raw_analysis": "상세",
    },
    ensure_ascii=False,
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status_code: int, message: str) -> anthropic.APIStatusError:
    response = httpx.Response(status_code, request=_request())
    return cls(message, response=response, body=None)


def _api_response(
    text: str,
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 10,
    cache_creation: int = 20,
) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.usage = MagicMock(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )
    return response


@pytest.fixture
def mock_create(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    create = AsyncMock()
    client = MagicMock()
    client.messages.create = create
    monkeypatch.setattr(
        "core.agent_runner.anthropic.AsyncAnthropic",
        lambda *args, **kwargs: client,
    )
    monkeypatch.setattr("core.agent_runner.load_prompt", lambda name: "system prompt")
    return create


# ── JSON 추출 ─────────────────────────────────────────────


def test_extract_json_from_pure_object():
    assert json.loads(_extract_json(VALID_JSON))["score"] == 7.5


def test_extract_json_with_surrounding_text():
    text = f"분석 결과입니다.\n{VALID_JSON}\n감사합니다."
    assert json.loads(_extract_json(text))["summary"] == "양호한 재무 구조"


def test_extract_json_from_markdown_fence():
    text = f"```json\n{VALID_JSON}\n```"
    assert json.loads(_extract_json(text))["agent"] == "financial"


def test_extract_json_nested_fence_inside_string():
    payload = {
        "agent": "financial",
        "score": 6,
        "conviction": "neutral",
        "summary": "요약",
        "evidence": [],
        "risks": [],
        "raw_analysis": "문서 예: ```json\n{\"x\": 1}\n``` 참고",
    }
    inner = json.dumps(payload, ensure_ascii=False)
    text = f"서론\n```json\n{inner}\n```\n후기"
    parsed = json.loads(_extract_json(text))
    assert parsed["raw_analysis"].startswith("문서 예:")
    assert parsed["score"] == 6


def test_extract_json_prefers_last_fenced_block():
    first = (
        '{"agent": "noise", "score": 1, "conviction": "negative",'
        ' "summary": "x", "evidence": [], "risks": []}'
    )
    text = f"```\n{first}\n```\n최종:\n```json\n{VALID_JSON}\n```"
    assert json.loads(_extract_json(text))["score"] == 7.5


@pytest.mark.parametrize("agent_name", ["financial", "buffett", "synthesizer"])
def test_load_prompt_existing_agent(agent_name: str):
    text = load_prompt(agent_name)
    assert text.strip()
    assert "출력" in text or "분석" in text


def test_load_prompt_missing_agent():
    with pytest.raises(FileNotFoundError, match="프롬프트 파일 없음"):
        load_prompt("does_not_exist")


# ── 폴백 ──────────────────────────────────────────────────


def test_fallback_agent_result_shape():
    result = fallback_agent_result("risk", RuntimeError("boom"))
    assert result.agent == "risk"
    assert result.score == 5.0
    assert result.conviction is Conviction.NEUTRAL
    assert result.summary == "[risk] 분석 실패: boom"
    assert result.evidence == []
    assert result.risks == []


# ── 사용량 집계 ───────────────────────────────────────────


def test_agent_usage_merge_and_cost():
    a = AgentUsage(
        input_tokens=1_000_000,
        output_tokens=0,
        model="claude-sonnet-4-20250514",
        estimated_cost_usd=3.0,
    )
    b = AgentUsage(
        input_tokens=0,
        output_tokens=1_000_000,
        cache_read_tokens=100,
        cache_creation_tokens=50,
        model="claude-sonnet-4-20250514",
        estimated_cost_usd=15.0,
        elapsed_seconds=2.0,
    )
    merged = a.merge(b)
    assert merged.input_tokens == 1_000_000
    assert merged.output_tokens == 1_000_000
    assert merged.cache_read_tokens == 100
    assert merged.cache_creation_tokens == 50
    assert merged.estimated_cost_usd == 18.0
    assert merged.elapsed_seconds == 2.0


# ── run_agent 시나리오 ────────────────────────────────────


@pytest.mark.asyncio
async def test_run_agent_reuses_provided_client(monkeypatch: pytest.MonkeyPatch):
    create = AsyncMock(return_value=_api_response(VALID_JSON))
    provided = MagicMock()
    provided.messages.create = create
    ctor = MagicMock()
    monkeypatch.setattr("core.agent_runner.anthropic.AsyncAnthropic", ctor)
    monkeypatch.setattr("core.agent_runner.load_prompt", lambda name: "system prompt")
    monkeypatch.setattr("core.agent_runner.settings.anthropic_api_key", "test-key")

    result = await run_agent("financial", "삼성전자", client=provided)

    assert result.score == 7.5
    ctor.assert_not_called()
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agent_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.agent_runner.settings.anthropic_api_key", "")
    with pytest.raises(anthropic.AuthenticationError, match="ANTHROPIC_API_KEY"):
        await run_agent("financial", "삼성전자")


@pytest.mark.parametrize(
    "depth,max_tokens",
    [("quick", 2048), ("standard", 4096), ("deep", 8192)],
)
@pytest.mark.asyncio
async def test_run_agent_max_tokens_follows_depth(
    mock_create: AsyncMock, depth: str, max_tokens: int
):
    mock_create.return_value = _api_response(VALID_JSON)
    await run_agent("financial", "삼성전자", depth=depth)
    assert mock_create.await_args.kwargs["max_tokens"] == max_tokens


@pytest.mark.asyncio
async def test_run_agent_success_attaches_usage(mock_create: AsyncMock):
    mock_create.return_value = _api_response(VALID_JSON)
    result = await run_agent("financial", "삼성전자")

    assert result.score == 7.5
    assert result.usage is not None
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50
    assert result.usage.cache_read_tokens == 10
    assert result.usage.cache_creation_tokens == 20
    assert result.usage.estimated_cost_usd > 0
    assert result.usage.elapsed_seconds >= 0
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_uses_exponential_backoff(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("core.agent_runner.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 2)

    mock_create.side_effect = [
        _status_error(anthropic.RateLimitError, 429, "rate limited"),
        _status_error(anthropic.RateLimitError, 429, "rate limited"),
        _api_response(VALID_JSON),
    ]

    result = await run_agent("financial", "삼성전자")
    assert result.score == 7.5
    assert sleeps == [1.0, 2.0]
    assert mock_create.await_count == 3


@pytest.mark.asyncio
async def test_server_error_is_retried(mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.agent_runner.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 2)
    mock_create.side_effect = [
        _status_error(anthropic.InternalServerError, 500, "oops"),
        _api_response(VALID_JSON),
    ]
    result = await run_agent("financial", "삼성전자")
    assert result.score == 7.5
    assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_authentication_error_is_not_retried(mock_create: AsyncMock):
    mock_create.side_effect = _status_error(anthropic.AuthenticationError, 401, "bad key")
    with pytest.raises(anthropic.AuthenticationError):
        await run_agent("financial", "삼성전자")
    assert mock_create.await_count == 1


@pytest.mark.asyncio
async def test_run_agent_parse_error_then_success(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 2)
    mock_create.side_effect = [
        _api_response("설명만 있고 JSON이 없습니다"),
        _api_response(f"```json\n{VALID_JSON}\n```"),
    ]
    result = await run_agent("financial", "삼성전자")
    assert result.score == 7.5
    assert result.conviction is Conviction.POSITIVE
    assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_run_agent_parse_error_exhausted_returns_fallback(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 0)
    mock_create.return_value = _api_response("not json at all")
    result = await run_agent("financial", "삼성전자")
    assert result.score == 5.0
    assert result.conviction is Conviction.NEUTRAL
    assert "[financial] 분석 실패:" in result.summary


@pytest.mark.asyncio
async def test_json_parse_retry_sends_json_only_instruction(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 2)
    mock_create.side_effect = [
        _api_response("이건 JSON이 아닙니다"),
        _api_response(VALID_JSON),
    ]
    result = await run_agent("financial", "삼성전자")
    assert result.score == 7.5
    assert mock_create.await_count == 2

    second_call_messages = mock_create.await_args_list[1].kwargs["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert JSON_RETRY_INSTRUCTION in second_call_messages[-1]["content"]


@pytest.mark.asyncio
async def test_exhausted_retries_return_fallback(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("core.agent_runner.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("core.agent_runner.settings.max_retries", 1)
    mock_create.side_effect = _status_error(anthropic.InternalServerError, 500, "down")

    result = await run_agent("industry", "삼성전자")
    assert result.score == 5.0
    assert result.conviction is Conviction.NEUTRAL
    assert "[industry] 분석 실패:" in result.summary
    assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_agent_timeout_returns_fallback(
    mock_create: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    async def hang(*args, **kwargs):
        import asyncio

        await asyncio.sleep(5)

    mock_create.side_effect = hang
    monkeypatch.setattr("core.agent_runner.settings.agent_timeout", 0.05)

    result = await run_agent("technical", "삼성전자")
    assert isinstance(result, AgentResult)
    assert result.score == 5.0
    assert "실패" in result.summary
    assert result.usage is not None
    assert result.usage.elapsed_seconds > 0
