"""Streamlit UX 헬퍼 및 파이프라인 진행 콜백."""

import anthropic
import httpx
import pytest

from core.models import AgentUsage, AnalysisRequest, CompanyInfo, SynthesisResult
from core.orchestrator import ANALYST_AGENTS, PHILOSOPHY_AGENTS, run_pipeline
from core.ux import format_usage_caption, format_user_error, upsert_history
from tests.test_orchestrator_harness import _empty_collect, _ok


def test_format_user_error_api_key():
    assert format_user_error(RuntimeError("ANTHROPIC_API_KEY missing")) == (
        "API 키를 확인해주세요"
    )
    req = httpx.Request("POST", "https://api.anthropic.com")
    resp = httpx.Response(401, request=req)
    auth = anthropic.AuthenticationError("invalid x-api-key", response=resp, body=None)
    assert format_user_error(auth) == "API 키를 확인해주세요"


def test_format_user_error_rate_limit():
    req = httpx.Request("POST", "https://api.anthropic.com")
    resp = httpx.Response(429, request=req)
    err = anthropic.RateLimitError("rate limited", response=resp, body=None)
    assert format_user_error(err) == "요청이 너무 많습니다. 잠시 후 다시 시도해주세요"


def test_format_user_error_network():
    err = httpx.ConnectError("connection refused")
    assert format_user_error(err) == "네트워크 연결을 확인해주세요"


def test_format_user_error_fallback_includes_hint():
    msg = format_user_error(RuntimeError("알 수 없는 오류"))
    assert "알 수 없는 오류" in msg
    assert "quick" in msg


def test_format_usage_caption():
    usage = AgentUsage(input_tokens=1200, output_tokens=340, estimated_cost_usd=0.0126)
    assert format_usage_caption(usage) == "토큰: 1200+340 | 예상 비용: $0.013"


def test_upsert_history_overwrites_and_caps():
    company = CompanyInfo(name="삼성전자", stock_code="005930")
    result = SynthesisResult(
        company=company,
        overall_score=7.0,
        consensus="매수",
        key_points=["p"],
        analyst_results=[],
        philosophy_results=[],
        executive_summary="요약",
    )
    history: dict = {}
    upsert_history(history, company, result)
    assert list(history) == ["삼성전자"]

    for i in range(12):
        name = f"기업{i}"
        upsert_history(
            history,
            CompanyInfo(name=name),
            result.model_copy(update={"company": CompanyInfo(name=name)}),
            max_items=10,
        )
    assert len(history) == 10
    assert "삼성전자" not in history


@pytest.mark.asyncio
async def test_pipeline_reports_progress(monkeypatch: pytest.MonkeyPatch):
    async def fake_run_agent(agent_name: str, **kwargs):
        return _ok(agent_name)

    monkeypatch.setattr("core.orchestrator._collect_data", _empty_collect)
    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)

    stages: list[str] = []
    await run_pipeline(
        AnalysisRequest(company=CompanyInfo(name="테스트")),
        on_progress=stages.append,
    )
    assert stages[0] == "📡 데이터 수집 중..."
    assert f"실무 분석 에이전트 {len(ANALYST_AGENTS)}개" in stages[1]
    assert f"투자 철학 에이전트 {len(PHILOSOPHY_AGENTS)}개" in stages[2]
    assert stages[3] == "📝 리포트 합성 중..."
