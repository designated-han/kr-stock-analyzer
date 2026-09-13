"""결과 화면용 순수 계산 헬퍼 (Streamlit 의존 없음)."""

from __future__ import annotations

from core.models import SynthesisResult

SNOWFLAKE_CATEGORY_MAP = {
    "financial": "재무건전성",
    "industry": "성장성",
    "technical": "기술적 분석",
    "risk": "리스크",
    "buffett": "밸류에이션",
    "lynch": "성장성",
    "economist": "거시환경",
    "dalio": "거시환경",
}

SNOWFLAKE_AXIS_ORDER = [
    "재무건전성",
    "성장성",
    "밸류에이션",
    "리스크",
    "기술적 분석",
    "거시환경",
]

_MARKET_ALIASES = {
    "Y": "KOSPI",
    "KOSPI": "KOSPI",
    "유가": "KOSPI",
    "유가증권": "KOSPI",
    "K": "KOSDAQ",
    "KOSDAQ": "KOSDAQ",
    "코스닥": "KOSDAQ",
    "N": "KONEX",
    "KONEX": "KONEX",
    "코넥스": "KONEX",
}


def detect_market(row: dict | None, fallback: str = "KOSPI") -> str:
    """DART 행/기업개황에서 시장을 판별합니다."""
    if not row:
        return fallback
    raw = str(row.get("corp_cls") or row.get("market") or "").strip().upper()
    if raw in _MARKET_ALIASES:
        return _MARKET_ALIASES[raw]
    raw_kr = str(row.get("corp_cls") or row.get("market") or "").strip()
    return _MARKET_ALIASES.get(raw_kr, fallback)


def resolve_market(selected: str, row: dict | None = None) -> str:
    """사용자가 고른 시장 또는 자동감지를 확정합니다.

    아직 판별할 수 없으면 '자동감지'를 유지해 파이프라인이 DART 개황으로 채웁니다.
    """
    chosen = (selected or "").strip()
    if chosen and chosen != "자동감지":
        return chosen
    detected = detect_market(row, "")
    return detected or "자동감지"


def validate_analysis_inputs(name: str, stock_code: str, corp_code: str) -> str | None:
    """입력 검증. 문제 없으면 None, 있으면 한글 메시지."""
    if not (name or "").strip():
        return "기업명을 입력해주세요."
    code = (stock_code or "").strip()
    if code and (not code.isdigit() or len(code) != 6):
        return "종목코드는 6자리 숫자여야 합니다. (예: 005930)"
    corp = (corp_code or "").strip()
    if corp and (not corp.isdigit() or len(corp) != 8):
        return "DART 기업코드는 8자리 숫자여야 합니다. (예: 00126380)"
    return None


def snowflake_scores(result: SynthesisResult) -> dict[str, float]:
    """에이전트 점수를 스노우플레이크 축 평균으로 묶습니다. 리스크는 반전."""
    buckets: dict[str, list[float]] = {}
    for item in result.analyst_results + result.philosophy_results:
        category = SNOWFLAKE_CATEGORY_MAP.get(item.agent, "기타")
        score = (10 - item.score) if item.agent == "risk" else item.score
        buckets.setdefault(category, []).append(score)
    ordered: dict[str, float] = {}
    for axis in SNOWFLAKE_AXIS_ORDER:
        values = buckets.get(axis)
        if values:
            ordered[axis] = sum(values) / len(values)
    for extra, values in buckets.items():
        if extra not in ordered:
            ordered[extra] = sum(values) / len(values)
    return ordered


def score_accent(score: float) -> str:
    if score >= 7:
        return "#4CAF50"
    if score >= 4:
        return "#FFC107"
    return "#F44336"


def quick_stats(result: SynthesisResult) -> dict[str, str]:
    all_results = result.analyst_results + result.philosophy_results
    if not all_results:
        return {
            "종합 점수": f"{result.overall_score:.1f}/10",
            "투자 의견": result.consensus.value,
            "참여 에이전트": "0개",
            "식별 리스크": "0건",
            "의견 일치": f"{len(result.agreements)}건",
            "의견 충돌": f"{len(result.conflicts)}건",
        }
    best = max(all_results, key=lambda r: r.score)
    worst = min(all_results, key=lambda r: r.score)
    return {
        "종합 점수": f"{result.overall_score:.1f}/10",
        "투자 의견": result.consensus.value,
        "참여 에이전트": f"{len(all_results)}개",
        "최고 점수": f"{best.score:.1f} ({best.agent})",
        "최저 점수": f"{worst.score:.1f} ({worst.agent})",
        "식별 리스크": f"{sum(len(r.risks) for r in all_results)}건",
        "의견 일치": f"{len(result.agreements)}건",
        "의견 충돌": f"{len(result.conflicts)}건",
    }


def progress_fraction(message: str) -> float | None:
    stages = {
        "📡 데이터 수집 중...": 0.1,
        "실무 분석 에이전트": 0.4,
        "투자 철학 에이전트": 0.7,
        "📝 리포트 합성 중...": 0.9,
    }
    for key, pct in stages.items():
        if key in message:
            return pct
    return None
