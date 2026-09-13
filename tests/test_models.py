"""AgentResult / enum / 점수 범위 검증."""

import json

import pytest
from pydantic import ValidationError

from core.models import AgentResult, ConsensusOpinion, Conviction


def test_agent_result_roundtrip_dict(agent_result: AgentResult):
    dumped = agent_result.model_dump(mode="json")
    restored = AgentResult.model_validate(dumped)
    assert restored == agent_result
    assert dumped["conviction"] == "positive"
    assert dumped["score"] == 7.5


def test_agent_result_roundtrip_json(agent_result: AgentResult):
    payload = agent_result.model_dump_json()
    restored = AgentResult.model_validate_json(payload)
    assert restored.agent == "financial"
    assert restored.conviction is Conviction.POSITIVE
    parsed = json.loads(payload)
    assert parsed["evidence"][0]["claim"] == "ROE 우수"
    assert parsed["risks"][0]["severity"] == 3


def test_conviction_enum_values():
    expected = {
        "strong_positive": Conviction.STRONG_POSITIVE,
        "positive": Conviction.POSITIVE,
        "neutral": Conviction.NEUTRAL,
        "negative": Conviction.NEGATIVE,
        "strong_negative": Conviction.STRONG_NEGATIVE,
    }
    for value, member in expected.items():
        assert Conviction(value) is member
        assert member.value == value


def test_agent_result_accepts_conviction_string():
    result = AgentResult(
        agent="buffett",
        score=8.0,
        conviction="strong_positive",
        summary="경제적 해자",
    )
    assert result.conviction is Conviction.STRONG_POSITIVE


def test_consensus_opinion_enum_values():
    expected = {
        "적극 매수": ConsensusOpinion.STRONG_BUY,
        "매수": ConsensusOpinion.BUY,
        "관망": ConsensusOpinion.HOLD,
        "매도": ConsensusOpinion.SELL,
        "적극 매도": ConsensusOpinion.STRONG_SELL,
    }
    for value, member in expected.items():
        assert ConsensusOpinion(value) is member
        assert member.value == value


@pytest.mark.parametrize("score", [1.0, 5.5, 10.0])
def test_score_within_range_is_valid(score: float):
    result = AgentResult(
        agent="financial",
        score=score,
        conviction=Conviction.NEUTRAL,
        summary="범위 안",
    )
    assert result.score == score


@pytest.mark.parametrize("score", [0, 0.9, 10.01, 11, -1])
def test_score_out_of_range_raises(score: float):
    with pytest.raises(ValidationError):
        AgentResult(
            agent="financial",
            score=score,
            conviction=Conviction.NEUTRAL,
            summary="범위 밖",
        )


def test_empty_evidence_and_risks_are_valid():
    result = AgentResult(
        agent="industry",
        score=6.0,
        conviction=Conviction.POSITIVE,
        summary="근거 없이 요약만",
    )
    assert result.evidence == []
    assert result.risks == []
    restored = AgentResult.model_validate(result.model_dump())
    assert restored.evidence == []
    assert restored.risks == []
