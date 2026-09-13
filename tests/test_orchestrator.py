"""오케스트레이터 헬퍼: 컨센서스 매핑, 메시지/요약 포맷, 리스트 추출."""

import json

import pytest

from core.models import (
    AgentResult,
    AnalysisRequest,
    CompanyInfo,
    ConsensusOpinion,
    Conviction,
    Evidence,
    Risk,
)
from core.orchestrator import (
    _build_company_message,
    _extract_list,
    _map_conviction_to_consensus,
    _summarize_results,
)


@pytest.mark.parametrize(
    "conviction,consensus",
    [
        (Conviction.STRONG_POSITIVE, ConsensusOpinion.STRONG_BUY),
        (Conviction.POSITIVE, ConsensusOpinion.BUY),
        (Conviction.NEUTRAL, ConsensusOpinion.HOLD),
        (Conviction.NEGATIVE, ConsensusOpinion.SELL),
        (Conviction.STRONG_NEGATIVE, ConsensusOpinion.STRONG_SELL),
    ],
)
def test_map_conviction_to_consensus(conviction: Conviction, consensus: ConsensusOpinion):
    result = _map_conviction_to_consensus(conviction)
    assert result is consensus
    assert isinstance(result, ConsensusOpinion)


def test_unknown_conviction_maps_to_hold():
    class Fake:
        value = "maybe"

    assert _map_conviction_to_consensus(Fake()) is ConsensusOpinion.HOLD


def test_build_company_message_format(analysis_request: AnalysisRequest):
    msg = _build_company_message(analysis_request, {})
    assert msg.startswith("# 분석 대상: 삼성전자")
    assert "- 종목코드: 005930" in msg
    assert "- 시장: KOSPI" in msg
    assert "- 업종: 반도체" in msg
    assert "- 대표이사: 한종희" in msg
    assert "- DART 기업코드: 00126380" in msg
    assert "분석 깊이: standard" in msg
    assert "외부 데이터 수집 불가" in msg
    assert "## DART 공시 데이터" not in msg
    assert "## 최근 뉴스" not in msg


def test_build_company_message_omits_optional_fields():
    request = AnalysisRequest(
        company=CompanyInfo(name="테스트", stock_code="000000", market="KOSDAQ"),
        depth="quick",
    )
    msg = _build_company_message(request)
    assert "- 업종:" not in msg
    assert "- 대표이사:" not in msg
    assert "- DART 기업코드:" not in msg
    assert "분석 깊이: quick" in msg


def test_build_company_message_includes_dart_and_news(analysis_request: AnalysisRequest):
    collected = {
        "dart": {"company_info": {"corp_name": "삼성전자", "stock_code": "005930"}},
        "news": {
            "news": [
                {"title": "호실적", "pubDate": "어제", "description": "매출 증가"},
            ]
        },
    }
    msg = _build_company_message(analysis_request, collected)
    assert "## DART 공시 데이터" in msg
    assert "## 최근 뉴스" in msg
    assert "호실적" in msg
    assert "외부 데이터 수집 불가" not in msg


def test_summarize_results_format(agent_result: AgentResult, empty_agent_result: AgentResult):
    extra = AgentResult(
        agent="industry",
        score=3.0,
        conviction=Conviction.NEGATIVE,
        summary="업황 둔화",
        evidence=[Evidence(claim="점유율", data="하락", source="뉴스")],
        risks=[
            Risk(title="경쟁", description="후발주자", severity=4, probability=4),
            Risk(title="일회성", description="약함", severity=1, probability=1),
        ],
    )
    text = _summarize_results([agent_result, extra, empty_agent_result])
    assert "### [financial] 점수: 7.5/10 | 확신도: positive" in text
    assert "**결론**: 재무 구조가 양호합니다." in text
    assert "**핵심 근거**:" in text
    assert "- ROE 우수: 18%" in text
    assert "**주요 리스크**:" in text
    assert "[3×4=12] 환율" in text
    assert "- (근거 없음)" in text
    assert "**요약 통계**:" in text
    assert "최고 7.5 (financial)" in text
    assert "최저 3.0 (industry)" in text
    assert "**의견 분포**:" in text


def test_summarize_results_empty_list():
    assert _summarize_results([]) == "(이전 계층 분석 결과가 없습니다.)"


def test_extract_list_from_json():
    raw = json.dumps(
        {"agreements": ["성장성", "수익성"], "conflicts": ["밸류에이션"]},
        ensure_ascii=False,
    )
    assert _extract_list(raw, "agreements") == ["성장성", "수익성"]
    assert _extract_list(raw, "conflicts") == ["밸류에이션"]


def test_extract_list_from_markdown_section():
    raw = """
## 종합
본문

## agreements
- 성장성 지속
- 현금흐름 양호

## conflicts
- 고평가 논란
"""
    assert _extract_list(raw, "agreements") == ["성장성 지속", "현금흐름 양호"]
    assert _extract_list(raw, "conflicts") == ["고평가 논란"]


def test_extract_list_missing_section_returns_empty():
    assert _extract_list("그냥 텍스트", "agreements") == []
    assert _extract_list('{"other": [1]}', "agreements") == []
