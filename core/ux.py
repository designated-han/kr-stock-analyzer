"""Streamlit UX 헬퍼: 에러 문구, 사용량 캡션, 최근 분석 캐시."""

from __future__ import annotations

from typing import Any

from core.models import AgentUsage, CompanyInfo, SynthesisResult

HISTORY_LIMIT = 10
QUICK_HINT = "문제가 계속되면 깊이를 'quick'으로 변경해보세요"


def format_user_error(error: BaseException) -> str:
    """예외를 사용자 친화적 한글로 바꿉니다."""
    text = str(error)
    lowered = text.lower()
    kind = type(error).__name__.lower()
    combined = f"{kind} {lowered}"

    if _is_api_key_error(error, combined):
        return "API 키를 확인해주세요"
    if _is_rate_limit_error(error, combined):
        return "요청이 너무 많습니다. 잠시 후 다시 시도해주세요"
    if _is_network_error(error, combined):
        return "네트워크 연결을 확인해주세요"
    return f"{text}\n{QUICK_HINT}"


def format_usage_caption(usage: AgentUsage) -> str:
    """토큰/비용 한 줄 요약."""
    return (
        f"토큰: {usage.input_tokens}+{usage.output_tokens} | "
        f"예상 비용: ${usage.estimated_cost_usd:.3f}"
    )


def upsert_history(
    history: dict[str, Any],
    company: CompanyInfo,
    result: SynthesisResult,
    *,
    max_items: int = HISTORY_LIMIT,
) -> dict[str, Any]:
    """기업명 키로 최근 분석 결과를 저장합니다. 같은 기업은 맨 뒤로 갱신."""
    key = company.name
    history.pop(key, None)
    history[key] = {"result": result, "company": company}
    while len(history) > max_items:
        oldest = next(iter(history))
        history.pop(oldest)
    return history


def _is_api_key_error(error: BaseException, combined: str) -> bool:
    name = type(error).__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return True
    markers = (
        "anthropic_api_key",
        "api key",
        "api_key",
        "x-api-key",
        "invalid api",
        "authentication",
    )
    return any(marker in combined for marker in markers)


def _is_rate_limit_error(error: BaseException, combined: str) -> bool:
    if type(error).__name__ == "RateLimitError":
        return True
    return "rate limit" in combined or "429" in combined or "too many requests" in combined


def _is_network_error(error: BaseException, combined: str) -> bool:
    name = type(error).__name__
    if name in {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "NetworkError",
        "APIConnectionError",
        "APITimeoutError",
    }:
        return True
    return any(
        marker in combined
        for marker in (
            "connection refused",
            "network is unreachable",
            "name or service not known",
            "failed to establish a new connection",
            "temporarily unavailable",
        )
    )
