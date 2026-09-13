"""헤르메스 엔지니어링: 공통 프롬프트, depth 주입, 구조화 컨텍스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_runner import DEPTH_INSTRUCTIONS, PROMPTS_DIR, run_agent
from core.models import AgentResult, Conviction, Evidence, Risk
from core.orchestrator import _summarize_results
from tests.test_agent_runner import VALID_JSON, _api_response

COMMON_HEADINGS = [
    "## 분석 프로세스",
    "## 데이터 부족 시 행동 규칙",
    "## 점수 기준 (Score Calibration)",
]

AGENT_PROMPTS = [
    "financial",
    "industry",
    "risk",
    "technical",
    "economist",
    "buffett",
    "lynch",
    "dalio",
    "synthesizer",
]


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


@pytest.mark.parametrize("agent_name", AGENT_PROMPTS)
def test_prompt_has_common_hermes_sections(agent_name: str):
    text = (PROMPTS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
    for heading in COMMON_HEADINGS:
        assert heading in text, f"{agent_name}.md 에 {heading} 없음"
    # 공통 섹션은 파일 하단에 위치
    assert text.rfind("## 분석 프로세스") > 100


def test_synthesizer_has_weight_range_and_fewshot():
    text = (PROMPTS_DIR / "synthesizer.md").read_text(encoding="utf-8")
    assert "[데이터 부족]" in text
    assert "가중치를 절반" in text
    assert "모든 에이전트가 6점 이상이면" in text
    assert "모든 에이전트가 4점 이하" in text
    assert "Few-shot" in text or "few-shot" in text or "출력 예시" in text
    assert '"agent": "synthesizer"' in text


def test_summarize_results_is_structured():
    results = [
        AgentResult(
            agent="financial",
            score=7.5,
            conviction=Conviction.POSITIVE,
            summary="수익성 양호",
            evidence=[
                Evidence(claim="ROE", data="18%", source="DART"),
                Evidence(claim="부채비율", data="40%", source="DART"),
            ],
            risks=[
                Risk(title="환율", description="수출", severity=3, probability=4),
                Risk(title="일회성", description="처분이익", severity=2, probability=2),
            ],
        ),
        AgentResult(
            agent="risk",
            score=3.0,
            conviction=Conviction.NEGATIVE,
            summary="지배구조 리스크",
            evidence=[Evidence(claim="순환출자", data="존재", source="공시")],
        ),
    ]
    text = _summarize_results(results)
    assert "[financial]" in text
    assert "점수: 7.5/10" in text
    assert "**결론**:" in text
    assert "**핵심 근거**:" in text
    assert "ROE: 18%" in text
    assert "**주요 리스크**:" in text
    assert "[3×4=12]" in text
    assert "**요약 통계**:" in text
    assert "평균 5.2" in text
    assert "최고 7.5 (financial)" in text
    assert "최저 3.0 (risk)" in text
    assert "**의견 분포**:" in text
    assert "긍정 1명" in text
    assert "부정 1명" in text


def test_summarize_results_empty():
    assert "결과가 없습니다" in _summarize_results([])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "depth,snippet",
    [
        ("quick", DEPTH_INSTRUCTIONS["quick"]),
        ("deep", DEPTH_INSTRUCTIONS["deep"]),
        ("standard", DEPTH_INSTRUCTIONS["standard"]),
    ],
)
async def test_depth_injected_into_system_prompt(
    mock_create: AsyncMock, depth: str, snippet: str
):
    mock_create.return_value = _api_response(VALID_JSON)
    await run_agent("financial", "삼성전자", depth=depth)
    system_text = mock_create.await_args.kwargs["system"][0]["text"]
    assert snippet in system_text
    assert "## 분석 깊이" in system_text
