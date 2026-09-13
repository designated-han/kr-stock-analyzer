"""테스트 공통 fixture."""

import pytest

from core.config import settings
from core.models import (
    AgentResult,
    AgentUsage,
    AnalysisRequest,
    CompanyInfo,
    Conviction,
    Evidence,
    Risk,
)


@pytest.fixture(autouse=True)
def _ensure_anthropic_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` 없이도 run_agent 가드가 통과하도록 더미 키를 넣습니다."""
    if not settings.anthropic_api_key:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


@pytest.fixture
def company_info() -> CompanyInfo:
    return CompanyInfo(
        name="삼성전자",
        corp_code="00126380",
        stock_code="005930",
        industry="반도체",
        ceo="한종희",
        established="19690113",
        market="KOSPI",
    )


@pytest.fixture
def analysis_request(company_info: CompanyInfo) -> AnalysisRequest:
    return AnalysisRequest(company=company_info, depth="standard")


@pytest.fixture
def sample_evidence() -> Evidence:
    return Evidence(claim="ROE 우수", data="18%", source="DART")


@pytest.fixture
def sample_risk() -> Risk:
    return Risk(title="환율", description="수출 비중 높음", severity=3, probability=4)


@pytest.fixture
def agent_result(sample_evidence: Evidence, sample_risk: Risk) -> AgentResult:
    return AgentResult(
        agent="financial",
        score=7.5,
        conviction=Conviction.POSITIVE,
        summary="재무 구조가 양호합니다.",
        evidence=[sample_evidence],
        risks=[sample_risk],
        raw_analysis="상세 분석 텍스트",
        usage=AgentUsage(
            input_tokens=100,
            output_tokens=50,
            model="claude-sonnet-4-20250514",
            estimated_cost_usd=0.001,
        ),
    )


@pytest.fixture
def empty_agent_result() -> AgentResult:
    return AgentResult(
        agent="risk",
        score=5.0,
        conviction=Conviction.NEUTRAL,
        summary="중립 평가입니다.",
        evidence=[],
        risks=[],
    )
