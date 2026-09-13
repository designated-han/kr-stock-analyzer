"""결과 화면 계산 헬퍼."""

from core.display import (
    detect_market,
    progress_fraction,
    quick_stats,
    resolve_market,
    snowflake_scores,
    validate_analysis_inputs,
)
from core.models import (
    AgentResult,
    CompanyInfo,
    ConsensusOpinion,
    Conviction,
    Risk,
    SynthesisResult,
)


def test_validate_analysis_inputs():
    assert validate_analysis_inputs("", "", "") == "기업명을 입력해주세요."
    assert "6자리" in (validate_analysis_inputs("삼성", "5930", "") or "")
    assert "8자리" in (validate_analysis_inputs("삼성", "005930", "123") or "")
    assert validate_analysis_inputs("삼성전자", "005930", "00126380") is None
    assert validate_analysis_inputs("삼성전자", "", "") is None


def test_detect_and_resolve_market():
    assert detect_market({"corp_cls": "Y"}) == "KOSPI"
    assert detect_market({"corp_cls": "K"}) == "KOSDAQ"
    assert detect_market({"market": "코스닥"}) == "KOSDAQ"
    assert detect_market({}, "KOSPI") == "KOSPI"
    assert resolve_market("KOSDAQ", {"corp_cls": "Y"}) == "KOSDAQ"
    assert resolve_market("자동감지", {"corp_cls": "K"}) == "KOSDAQ"
    assert resolve_market("자동감지", {}) == "자동감지"


def test_snowflake_averages_and_inverts_risk():
    result = SynthesisResult(
        company=CompanyInfo(name="테스트"),
        overall_score=6.0,
        consensus=ConsensusOpinion.HOLD,
        key_points=[],
        analyst_results=[
            AgentResult(agent="financial", score=8.0, conviction=Conviction.POSITIVE, summary="s"),
            AgentResult(agent="industry", score=6.0, conviction=Conviction.NEUTRAL, summary="s"),
            AgentResult(agent="risk", score=3.0, conviction=Conviction.NEGATIVE, summary="s"),
            AgentResult(agent="technical", score=5.0, conviction=Conviction.NEUTRAL, summary="s"),
        ],
        philosophy_results=[
            AgentResult(agent="buffett", score=7.0, conviction=Conviction.POSITIVE, summary="s"),
            AgentResult(agent="lynch", score=8.0, conviction=Conviction.POSITIVE, summary="s"),
        ],
        executive_summary="요약",
    )
    scores = snowflake_scores(result)
    assert scores["재무건전성"] == 8.0
    assert scores["성장성"] == 7.0  # (6 + 8) / 2
    assert scores["밸류에이션"] == 7.0
    assert scores["리스크"] == 7.0  # 10 - 3
    assert scores["기술적 분석"] == 5.0
    assert list(scores)[:5] == [
        "재무건전성",
        "성장성",
        "밸류에이션",
        "리스크",
        "기술적 분석",
    ]


def test_quick_stats_and_progress():
    result = SynthesisResult(
        company=CompanyInfo(name="테스트"),
        overall_score=7.5,
        consensus=ConsensusOpinion.BUY,
        key_points=["p"],
        analyst_results=[
            AgentResult(
                agent="financial",
                score=8.0,
                conviction=Conviction.POSITIVE,
                summary="s",
                risks=[Risk(title="환율", description="d", severity=3, probability=3)],
            )
        ],
        philosophy_results=[
            AgentResult(agent="buffett", score=6.0, conviction=Conviction.NEUTRAL, summary="s")
        ],
        agreements=["성장"],
        conflicts=["가격"],
        executive_summary="요약",
    )
    stats = quick_stats(result)
    assert stats["종합 점수"] == "7.5/10"
    assert stats["최고 점수"] == "8.0 (financial)"
    assert stats["최저 점수"] == "6.0 (buffett)"
    assert stats["식별 리스크"] == "1건"
    assert progress_fraction("📊 실무 분석 에이전트 5개 실행 중...") == 0.4
    assert progress_fraction("📡 데이터 수집 중...") == 0.1
