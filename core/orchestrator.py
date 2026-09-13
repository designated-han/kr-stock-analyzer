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
from collections.abc import Callable
from datetime import datetime
from typing import Any

import anthropic

from core.agent_runner import fallback_agent_result, run_agent
from core.config import settings
from core.display import detect_market
from core.models import (
    AgentResult,
    AgentUsage,
    AnalysisRequest,
    ConsensusOpinion,
    SynthesisResult,
)
from data.dart_client import DartClient
from data.formatter import format_dart_data, format_news_data
from data.naver_client import NaverClient

logger = logging.getLogger(__name__)

# 계층별 에이전트 정의
ANALYST_AGENTS = ["financial", "industry", "risk", "technical", "economist"]
PHILOSOPHY_AGENTS = ["buffett", "lynch", "dalio"]
SYNTHESIS_AGENT = "synthesizer"


async def run_pipeline(
    request: AnalysisRequest,
    on_progress: Callable[[str], None] | None = None,
) -> SynthesisResult:
    """전체 분석 파이프라인을 실행합니다.

    Args:
        request: 분석 요청 (기업 정보 + 분석 깊이)
        on_progress: 단계별 상태 메시지 콜백 (Streamlit st.status 등)

    Returns:
        SynthesisResult: 최종 합성 결과
    """
    company = request.company
    start = time.time()
    logger.info(f"=== 분석 시작: {company.name} ({company.stock_code}) ===")

    def _progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    # ── 1단계: 데이터 수집 ──────────────────────────────────
    _progress("📡 데이터 수집 중...")
    logger.info("[Layer 1] 데이터 수집 시작")
    collected = await _collect_data(request)
    if company.market in {"", "자동감지"}:
        info = (collected.get("dart") or {}).get("company_info") or {}
        company.market = detect_market(info, "KOSPI")
    user_message = _build_company_message(request, collected)
    logger.info(
        f"[Layer 1] 완료 — dart={'있음' if collected.get('dart') else '없음'}, "
        f"news={'있음' if collected.get('news') else '없음'}"
    )

    # ── 2단계: 실무 분석 (병렬) ─────────────────────────────
    _progress(f"📊 실무 분석 에이전트 {len(ANALYST_AGENTS)}개 실행 중...")
    logger.info("[Layer 2] 실무 분석 시작")
    analyst_results = await _run_layer(
        agents=ANALYST_AGENTS,
        user_message=user_message,
        model=settings.claude_model_default,
        context="",
        depth=request.depth,
    )
    analyst_context = _summarize_results(analyst_results)
    logger.info(f"[Layer 2] 완료 — {len(analyst_results)}개 에이전트")

    # ── 3단계: 투자 철학 평가 (병렬) ───────────────────────
    _progress(f"🧠 투자 철학 에이전트 {len(PHILOSOPHY_AGENTS)}개 실행 중...")
    logger.info("[Layer 3] 투자 철학 평가 시작")
    philosophy_results = await _run_layer(
        agents=PHILOSOPHY_AGENTS,
        user_message=user_message,
        model=settings.claude_model_quality,
        context=analyst_context,
        depth=request.depth,
    )
    logger.info(f"[Layer 3] 완료 — {len(philosophy_results)}개 에이전트")

    # ── 4단계: 리포트 합성 ──────────────────────────────────
    _progress("📝 리포트 합성 중...")
    logger.info("[Layer 4] 리포트 합성 시작")
    all_context = _build_synthesis_context(analyst_results, philosophy_results)
    synth_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    synthesis_result = await run_agent(
        agent_name=SYNTHESIS_AGENT,
        user_message=user_message,
        model=settings.claude_model_quality,
        context=all_context,
        depth=request.depth,
        client=synth_client,
    )

    elapsed = time.time() - start
    pipeline_usage = AgentUsage.aggregate(
        [r.usage for r in [*analyst_results, *philosophy_results, synthesis_result] if r.usage],
        elapsed_seconds=elapsed,
    )
    logger.info(
        f"=== 분석 완료: {company.name} — {elapsed:.1f}초 | "
        f"토큰 in={pipeline_usage.input_tokens} "
        f"out={pipeline_usage.output_tokens} "
        f"cache_r={pipeline_usage.cache_read_tokens} "
        f"cache_w={pipeline_usage.cache_creation_tokens} "
        f"비용 ${pipeline_usage.estimated_cost_usd:.4f} ==="
    )

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
        usage=pipeline_usage,
        collected_data=collected,
    )


async def _run_layer(
    agents: list[str],
    user_message: str,
    model: str,
    context: str,
    depth: str = "standard",
) -> list[AgentResult]:
    """에이전트 계층을 병렬 실행합니다."""
    semaphore = asyncio.Semaphore(settings.max_concurrent_agents)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _guarded(agent_name: str) -> AgentResult:
        async with semaphore:
            try:
                return await run_agent(
                    agent_name=agent_name,
                    user_message=user_message,
                    model=model,
                    context=context,
                    depth=depth,
                    client=client,
                )
            except anthropic.AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"[{agent_name}] 실패: {e}")
                return fallback_agent_result(agent_name, e)

    tasks = [_guarded(name) for name in agents]
    results = await asyncio.gather(*tasks)
    return list(results)


def _latest_bsns_year(now: datetime | None = None) -> str:
    """사업보고서 제출 시점을 고려한 최신 사업연도.

    12월 결산 기업의 사업보고서는 보통 3월 말까지 제출되므로,
    4월 이전에는 전전년, 그 외에는 전년을 사용합니다.
    """
    current = now or datetime.now()
    year = current.year - 2 if current.month < 4 else current.year - 1
    return str(year)


async def _collect_data(request: AnalysisRequest) -> dict[str, Any]:
    """1단계: DART + Naver 데이터를 병렬 수집합니다.

    API 키가 없거나 corp_code가 없으면 해당 소스를 건너뜁니다.
    개별 수집 실패는 빈 dict로 대체하고 파이프라인을 계속 진행합니다.
    """
    tasks: dict[str, Any] = {}
    dart: DartClient | None = None

    if request.company.corp_code and settings.dart_api_key:
        dart = DartClient()
        bsns_year = _latest_bsns_year()
        logger.info(
            f"[Layer 1] DART 수집 "
            f"(corp_code={request.company.corp_code}, year={bsns_year})"
        )
        tasks["dart"] = dart.collect_all(request.company.corp_code, bsns_year)
    elif request.company.corp_code and not settings.dart_api_key:
        logger.info("[Layer 1] DART API 키 없음 — 건너뜀")
    elif not request.company.corp_code:
        logger.info("[Layer 1] corp_code 없음 — DART 건너뜀")

    if settings.naver_client_id:
        naver = NaverClient()
        logger.info(f"[Layer 1] Naver 뉴스 수집 ({request.company.name})")
        tasks["news"] = naver.collect_company_news(
            request.company.name, keywords=["실적", "전망", "투자"]
        )
    else:
        logger.info("[Layer 1] Naver API 키 없음 — 건너뜀")

    try:
        if not tasks:
            return {}

        keys = list(tasks.keys())
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        collected: dict[str, Any] = {}
        for key, value in zip(keys, results, strict=True):
            if isinstance(value, Exception):
                logger.error(f"[Layer 1] {key} 수집 실패: {value}")
                collected[key] = {}
            else:
                collected[key] = value
        return collected
    finally:
        if dart is not None:
            close = getattr(dart, "close", None)
            if close is not None:
                maybe = close()
                if asyncio.iscoroutine(maybe):
                    await maybe


def _build_company_message(
    request: AnalysisRequest,
    collected: dict[str, Any] | None = None,
) -> str:
    """분석 요청과 수집 데이터를 에이전트 메시지로 조립합니다."""
    collected = collected or {}
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

    has_dart = bool(collected.get("dart"))
    has_news = bool(collected.get("news"))

    if has_dart:
        lines.append("\n## DART 공시 데이터\n")
        lines.append(format_dart_data(collected["dart"]))

    if has_news:
        lines.append("\n## 최근 뉴스\n")
        lines.append(format_news_data(collected["news"]))

    if not has_dart and not has_news:
        lines.append("\n⚠️ 외부 데이터 수집 불가. 일반 지식 기반으로 분석해주세요.")

    lines.append(f"\n분석 깊이: {request.depth}")
    return "\n".join(lines)


def _summarize_results(results: list[AgentResult]) -> str:
    """이전 계층 결과를 구조화된 형태로 다음 계층에 전달합니다."""
    if not results:
        return "(이전 계층 분석 결과가 없습니다.)"

    sections: list[str] = []
    for r in results:
        lines = [
            f"### [{r.agent}] 점수: {r.score}/10 | 확신도: {r.conviction.value}",
            f"**결론**: {r.summary}",
            "**핵심 근거**:",
        ]
        if r.evidence:
            for ev in r.evidence[:3]:
                lines.append(f"- {ev.claim}: {ev.data}")
        else:
            lines.append("- (근거 없음)")

        if r.risks:
            lines.append("**주요 리스크**:")
            top = sorted(
                r.risks,
                key=lambda x: x.severity * x.probability,
                reverse=True,
            )[:2]
            for risk in top:
                score = risk.severity * risk.probability
                lines.append(
                    f"- [{risk.severity}×{risk.probability}={score}] {risk.title}"
                )

        sections.append("\n".join(lines))

    scores = [r.score for r in results]
    best = max(results, key=lambda r: r.score)
    worst = min(results, key=lambda r: r.score)
    n_pos = sum(1 for r in results if r.score >= 6)
    n_neu = sum(1 for r in results if 4 <= r.score < 6)
    n_neg = sum(1 for r in results if r.score < 4)
    stats = (
        "\n---\n"
        f"**요약 통계**: 평균 {sum(scores) / len(scores):.1f} | "
        f"최고 {best.score} ({best.agent}) | "
        f"최저 {worst.score} ({worst.agent})\n"
        f"**의견 분포**: 긍정 {n_pos}명, 중립 {n_neu}명, 부정 {n_neg}명"
    )
    return "\n\n".join(sections) + "\n" + stats


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


def _map_conviction_to_consensus(conviction) -> ConsensusOpinion:
    """확신도를 컨센서스 의견으로 매핑합니다."""
    mapping = {
        "strong_positive": ConsensusOpinion.STRONG_BUY,
        "positive": ConsensusOpinion.BUY,
        "neutral": ConsensusOpinion.HOLD,
        "negative": ConsensusOpinion.SELL,
        "strong_negative": ConsensusOpinion.STRONG_SELL,
    }
    return mapping.get(conviction.value, ConsensusOpinion.HOLD)


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
