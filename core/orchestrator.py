"""파이프라인 오케스트레이터.

4계층 파이프라인을 실행합니다:
  1. 데이터 수집 (병렬)
  2. 실무 분석 (병렬)
  3. 투자 철학 평가 (병렬)
  4. 리포트 합성
"""

import asyncio
import json
import logging
import time

from core.agent_runner import run_agent
from core.config import settings
from core.models import AnalysisRequest, AgentResult, SynthesisResult

logger = logging.getLogger(__name__)

# 계층별 에이전트 정의
ANALYST_AGENTS = ["financial", "industry", "risk", "technical", "economist"]
PHILOSOPHY_AGENTS = ["buffett", "lynch", "dalio"]
SYNTHESIS_AGENT = "synthesizer"


async def run_pipeline(request: AnalysisRequest) -> SynthesisResult:
    """전체 분석 파이프라인을 실행합니다.

    Args:
        request: 분석 요청 (기업 정보 + 분석 깊이)

    Returns:
        SynthesisResult: 최종 합성 결과
    """
    company = request.company
    start = time.time()
    logger.info(f"=== 분석 시작: {company.name} ({company.stock_code}) ===")

    # ── 1단계: 데이터 수집 ──────────────────────────────────
    # 현재는 에이전트가 직접 데이터를 참조하도록 메시지에 포함.
    # Phase 2에서 별도 데이터 수집 에이전트로 분리 예정.
    user_message = _build_company_message(request)

    # ── 2단계: 실무 분석 (병렬) ─────────────────────────────
    logger.info("[Layer 2] 실무 분석 시작")
    analyst_results = await _run_layer(
        agents=ANALYST_AGENTS,
        user_message=user_message,
        model=settings.claude_model_default,
        context="",
    )
    analyst_context = _summarize_results(analyst_results)
    logger.info(f"[Layer 2] 완료 — {len(analyst_results)}개 에이전트")

    # ── 3단계: 투자 철학 평가 (병렬) ───────────────────────
    logger.info("[Layer 3] 투자 철학 평가 시작")
    philosophy_results = await _run_layer(
        agents=PHILOSOPHY_AGENTS,
        user_message=user_message,
        model=settings.claude_model_quality,
        context=analyst_context,
    )
    logger.info(f"[Layer 3] 완료 — {len(philosophy_results)}개 에이전트")

    # ── 4단계: 리포트 합성 ──────────────────────────────────
    logger.info("[Layer 4] 리포트 합성 시작")
    all_context = _build_synthesis_context(analyst_results, philosophy_results)
    synthesis_result = await run_agent(
        agent_name=SYNTHESIS_AGENT,
        user_message=user_message,
        model=settings.claude_model_quality,
        context=all_context,
    )

    elapsed = time.time() - start
    logger.info(f"=== 분석 완료: {company.name} — {elapsed:.1f}초 ===")

    # 최종 결과 조립
    return SynthesisResult(
        company=company,
        overall_score=synthesis_result.score,
        consensus=_map_conviction_to_consensus(synthesis_result.conviction),
        key_points=_extract_key_points(synthesis_result),
        analyst_results=analyst_results,
        philosophy_results=philosophy_results,
        agreements=_extract_list(synthesis_result.raw_analysis, "agreements"),
        conflicts=_extract_list(synthesis_result.raw_analysis, "conflicts"),
        executive_summary=synthesis_result.summary,
    )


async def _run_layer(
    agents: list[str],
    user_message: str,
    model: str,
    context: str,
) -> list[AgentResult]:
    """에이전트 계층을 병렬 실행합니다."""
    semaphore = asyncio.Semaphore(settings.max_concurrent_agents)

    async def _guarded(agent_name: str) -> AgentResult | None:
        async with semaphore:
            try:
                return await run_agent(
                    agent_name=agent_name,
                    user_message=user_message,
                    model=model,
                    context=context,
                )
            except Exception as e:
                logger.error(f"[{agent_name}] 실패: {e}")
                return None

    tasks = [_guarded(name) for name in agents]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def _build_company_message(request: AnalysisRequest) -> str:
    """분석 요청에서 에이전트에 전달할 메시지를 생성합니다."""
    c = request.company
    lines = [
        f"# 분석 대상: {c.name}",
        f"- 종목코드: {c.stock_code}",
        f"- 시장: {c.market}",
    ]
    if c.industry:
        lines.append(f"- 업종: {c.industry}")
    if c.ceo:
        lines.append(f"- 대표이사: {c.ceo}")
    if c.corp_code:
        lines.append(f"- DART 기업코드: {c.corp_code}")
    lines.append(f"\n분석 깊이: {request.depth}")
    return "\n".join(lines)


def _summarize_results(results: list[AgentResult]) -> str:
    """이전 계층 결과를 다음 계층의 컨텍스트로 요약합니다."""
    summaries = []
    for r in results:
        summaries.append(
            f"### {r.agent} (점수: {r.score}/10, 확신도: {r.conviction.value})\n"
            f"{r.summary}\n"
        )
        if r.risks:
            top_risks = sorted(r.risks, key=lambda x: x.severity * x.probability, reverse=True)[:3]
            risk_lines = [f"- {risk.title} (심각도:{risk.severity}, 확률:{risk.probability})" for risk in top_risks]
            summaries.append("주요 리스크:\n" + "\n".join(risk_lines) + "\n")
    return "\n".join(summaries)


def _build_synthesis_context(
    analyst_results: list[AgentResult],
    philosophy_results: list[AgentResult],
) -> str:
    """합성 에이전트를 위한 전체 컨텍스트를 구성합니다."""
    parts = ["## 실무 분석 결과\n"]
    parts.append(_summarize_results(analyst_results))
    parts.append("\n## 투자 철학 평가 결과\n")
    parts.append(_summarize_results(philosophy_results))

    # 점수 통계
    all_scores = [r.score for r in analyst_results + philosophy_results]
    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        parts.append(f"\n## 점수 통계\n- 평균: {avg:.1f}/10\n- 범위: {min(all_scores)}~{max(all_scores)}")

    return "\n".join(parts)


def _map_conviction_to_consensus(conviction) -> str:
    """확신도를 컨센서스 의견으로 매핑합니다."""
    mapping = {
        "strong_positive": "적극 매수",
        "positive": "매수",
        "neutral": "관망",
        "negative": "매도",
        "strong_negative": "적극 매도",
    }
    return mapping.get(conviction.value, "관망")


def _extract_key_points(result: AgentResult) -> list[str]:
    """합성 결과에서 핵심 포인트를 추출합니다."""
    # evidence에서 상위 3~5개 claim 추출
    points = [e.claim for e in result.evidence[:5]]
    if not points:
        points = [result.summary]
    return points


def _extract_list(raw_analysis: str, section: str) -> list[str]:
    """raw_analysis에서 특정 섹션의 리스트를 추출합니다."""
    # JSON 내 리스트 파싱 시도
    try:
        data = json.loads(raw_analysis)
        if section in data and isinstance(data[section], list):
            return data[section]
    except (json.JSONDecodeError, TypeError):
        pass

    # 텍스트에서 섹션 파싱 (폴백)
    items = []
    in_section = False
    for line in raw_analysis.split("\n"):
        if section.lower() in line.lower() and (":" in line or "#" in line):
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if stripped.startswith(("-", "•", "*")):
                items.append(stripped.lstrip("-•* ").strip())
            elif stripped and not stripped.startswith(("#", "[")):
                continue
            elif stripped.startswith("#"):
                break
    return items
