"""_map_conviction_to_consensus 타입/매핑 검증."""

from core.models import ConsensusOpinion, Conviction, CompanyInfo, SynthesisResult
from core.orchestrator import _map_conviction_to_consensus


def test_maps_conviction_to_consensus_enum():
    expected = {
        Conviction.STRONG_POSITIVE: ConsensusOpinion.STRONG_BUY,
        Conviction.POSITIVE: ConsensusOpinion.BUY,
        Conviction.NEUTRAL: ConsensusOpinion.HOLD,
        Conviction.NEGATIVE: ConsensusOpinion.SELL,
        Conviction.STRONG_NEGATIVE: ConsensusOpinion.STRONG_SELL,
    }
    for conviction, consensus in expected.items():
        result = _map_conviction_to_consensus(conviction)
        assert isinstance(result, ConsensusOpinion)
        assert result is consensus
        assert result.value  # display label exists


def test_unknown_conviction_defaults_to_hold():
    class Fake:
        value = "unknown"

    assert _map_conviction_to_consensus(Fake()) is ConsensusOpinion.HOLD


def test_synthesis_result_accepts_mapped_consensus():
    company = CompanyInfo(name="테스트")
    consensus = _map_conviction_to_consensus(Conviction.POSITIVE)
    result = SynthesisResult(
        company=company,
        overall_score=7.0,
        consensus=consensus,
        key_points=["포인트"],
        analyst_results=[],
        philosophy_results=[],
        executive_summary="요약",
    )
    assert result.consensus is ConsensusOpinion.BUY
    assert result.consensus.value == "매수"
