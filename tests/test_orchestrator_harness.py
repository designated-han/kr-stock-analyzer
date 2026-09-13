"""오케스트레이터 하네스: 폴백 유지, 파이프라인 사용량 집계."""

import pytest

from core.models import AgentResult, AgentUsage, AnalysisRequest, CompanyInfo, Conviction
from core.orchestrator import _run_layer, run_pipeline


async def _empty_collect(request) -> dict:
    """빈 데이터 수집 결과. `orchestrator._collect_data(request)`와 시그니처를 맞춥니다."""
    return {}


def _ok(agent: str, input_tokens: int = 100) -> AgentResult:
    """성공적인 에이전트 결과를 반환합니다."""
    return AgentResult(
        agent=agent,
        score=7.0,
        conviction=Conviction.POSITIVE,
        summary=f"{agent} 요약",
        usage=AgentUsage(
            input_tokens=input_tokens,
            output_tokens=20,
            model="claude-sonnet-4-20250514",
            estimated_cost_usd=0.01,
            elapsed_seconds=1.0,
        ),
    )


def _fail(agent: str) -> AgentResult:
    return AgentResult(
        agent=agent,
        score=5.0,
        conviction=Conviction.NEUTRAL,
        summary=f"[{agent}] 분석 실패: boom",
        usage=AgentUsage(elapsed_seconds=0.2),
    )


@pytest.mark.asyncio
async def test_run_layer_shares_one_client(monkeypatch: pytest.MonkeyPatch):
    seen: list[object] = []
    shared = object()

    async def fake_run_agent(agent_name: str, **kwargs) -> AgentResult:
        seen.append(kwargs.get("client"))
        return _ok(agent_name)

    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    monkeypatch.setattr(
        "core.orchestrator.anthropic.AsyncAnthropic",
        lambda *args, **kwargs: shared,
    )

    await _run_layer(
        agents=["financial", "risk"],
        user_message="msg",
        model="claude-sonnet-4-20250514",
        context="",
    )
    assert seen == [shared, shared]


@pytest.mark.asyncio
async def test_run_layer_keeps_fallback_results(monkeypatch: pytest.MonkeyPatch):
    async def fake_run_agent(agent_name: str, **kwargs) -> AgentResult:
        if agent_name == "risk":
            return _fail("risk")
        return _ok(agent_name)

    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    results = await _run_layer(
        agents=["financial", "risk"],
        user_message="msg",
        model="claude-sonnet-4-20250514",
        context="",
    )
    assert [r.agent for r in results] == ["financial", "risk"]
    assert "실패" in results[1].summary


@pytest.mark.asyncio
async def test_pipeline_aggregates_token_usage(monkeypatch: pytest.MonkeyPatch):
    async def fake_run_agent(agent_name: str, **kwargs) -> AgentResult:
        if agent_name == "synthesizer":
            return AgentResult(
                agent="synthesizer",
                score=6.5,
                conviction=Conviction.POSITIVE,
                summary="종합 의견",
                raw_analysis='{"agreements": ["성장"], "conflicts": []}',
                usage=AgentUsage(
                    input_tokens=50,
                    output_tokens=10,
                    estimated_cost_usd=0.02,
                    model="claude-sonnet-4-20250514",
                ),
            )
        return _ok(agent_name, input_tokens=100)

    monkeypatch.setattr("core.orchestrator._collect_data", _empty_collect)
    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    monkeypatch.setattr("core.orchestrator.ANALYST_AGENTS", ["financial"])
    monkeypatch.setattr("core.orchestrator.PHILOSOPHY_AGENTS", ["buffett"])

    result = await run_pipeline(
        AnalysisRequest(company=CompanyInfo(name="테스트", stock_code="000000"))
    )

    assert result.usage is not None
    # financial + buffett + synthesizer
    assert result.usage.input_tokens == 250
    assert result.usage.output_tokens == 50
    assert result.usage.estimated_cost_usd == pytest.approx(0.04)
    assert result.usage.elapsed_seconds >= 0
    assert len(result.analyst_results) == 1
    assert len(result.philosophy_results) == 1
    assert result.collected_data == {}


@pytest.mark.asyncio
async def test_pipeline_detects_market_from_collected_dart(monkeypatch: pytest.MonkeyPatch):
    async def fake_collect(request):
        return {"dart": {"company_info": {"corp_cls": "K", "corp_name": "테스트"}}}

    async def fake_run_agent(agent_name: str, **kwargs) -> AgentResult:
        return _ok(agent_name)

    monkeypatch.setattr("core.orchestrator._collect_data", fake_collect)
    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    monkeypatch.setattr("core.orchestrator.ANALYST_AGENTS", ["financial"])
    monkeypatch.setattr("core.orchestrator.PHILOSOPHY_AGENTS", ["buffett"])

    result = await run_pipeline(
        AnalysisRequest(company=CompanyInfo(name="테스트", market="자동감지"))
    )
    assert result.company.market == "KOSDAQ"
    assert result.collected_data["dart"]["company_info"]["corp_cls"] == "K"


@pytest.mark.asyncio
async def test_pipeline_passes_depth_to_agents(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, str] = {}

    async def fake_run_agent(agent_name: str, **kwargs) -> AgentResult:
        seen[agent_name] = kwargs.get("depth", "")
        if agent_name == "synthesizer":
            return AgentResult(
                agent="synthesizer",
                score=6.5,
                conviction=Conviction.POSITIVE,
                summary="종합",
            )
        return _ok(agent_name)

    monkeypatch.setattr("core.orchestrator._collect_data", _empty_collect)
    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    monkeypatch.setattr("core.orchestrator.ANALYST_AGENTS", ["financial"])
    monkeypatch.setattr("core.orchestrator.PHILOSOPHY_AGENTS", ["buffett"])

    await run_pipeline(
        AnalysisRequest(
            company=CompanyInfo(name="테스트", stock_code="000000"),
            depth="deep",
        )
    )
    assert seen["financial"] == "deep"
    assert seen["buffett"] == "deep"
    assert seen["synthesizer"] == "deep"
