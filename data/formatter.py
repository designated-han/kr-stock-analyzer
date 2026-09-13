"""수집된 DART/Naver 원시 데이터를 에이전트용 Markdown으로 변환합니다."""

from __future__ import annotations

from typing import Any

# 토큰 절약을 위해 재무제표에서 추출할 핵심 계정만 유지
KEY_ACCOUNTS = [
    "자산총계",
    "부채총계",
    "자본총계",
    "매출액",
    "영업이익",
    "당기순이익",
    "영업활동현금흐름",
    "투자활동현금흐름",
    "재무활동현금흐름",
    "유형자산",
    "현금및현금성자산",
]

COMPANY_FIELDS = [
    ("corp_name", "회사명"),
    ("stock_code", "종목코드"),
    ("ceo_nm", "대표이사"),
    ("adres", "주소"),
    ("est_dt", "설립일"),
    ("hm_url", "홈페이지"),
    ("induty_code", "업종코드"),
    ("acc_mt", "결산월"),
]

MAX_RATIOS = 12
MAX_SHAREHOLDERS = 5
MAX_DIVIDEND_ROWS = 8
MAX_NEWS = 15
SUMMARY_LEN = 80


def format_dart_data(dart_data: dict[str, Any] | None) -> str:
    """DART collect_all 결과를 Markdown 표로 변환합니다. 빈 값은 N/A."""
    data = dart_data or {}
    parts = [
        _format_company_info(data.get("company_info") or {}),
        _format_financial_statements(data.get("financial_statements") or {}),
        _format_financial_ratios(data.get("financial_ratios") or {}),
        _format_shareholders(data.get("major_shareholders") or {}),
        _format_dividend(data.get("dividend_info") or {}),
    ]
    return "\n\n".join(parts)


def format_news_data(news_data: dict[str, Any] | list | None) -> str:
    """뉴스 헤드라인 + 날짜 + 1줄 요약을 최대 15건 출력합니다."""
    if isinstance(news_data, list):
        items = news_data
    else:
        items = (news_data or {}).get("news") or []

    if not items:
        return "- N/A"

    lines: list[str] = []
    for item in items[:MAX_NEWS]:
        title = _na(item.get("title"))
        date = _na(item.get("pubDate") or item.get("date"))
        summary = _one_line(item.get("description") or item.get("summary") or "")
        lines.append(f"- **{title}** ({date}): {summary}")
    return "\n".join(lines)


def _format_company_info(payload: dict[str, Any]) -> str:
    lines = ["### 기업 개황", "", "| 항목 | 값 |", "|---|---|"]
    for key, label in COMPANY_FIELDS:
        lines.append(f"| {label} | {_pretty_value(payload.get(key))} |")
    return "\n".join(lines)


def _format_financial_statements(payload: dict[str, Any]) -> str:
    lines = [
        "### 재무제표 주요 계정",
        "",
        "| 계정 | 당기 | 전기 |",
        "|---|---|---|",
    ]
    rows = _as_list(payload)
    picked = _pick_accounts(rows)
    if not picked:
        for name in KEY_ACCOUNTS:
            lines.append(f"| {name} | N/A | N/A |")
        return "\n".join(lines)

    for name in KEY_ACCOUNTS:
        row = picked.get(name)
        if row is None:
            lines.append(f"| {name} | N/A | N/A |")
            continue
        current = _fmt_amount(row.get("thstrm_amount"))
        prior = _fmt_amount(row.get("frmtrm_amount"))
        lines.append(f"| {name} | {current} | {prior} |")
    return "\n".join(lines)


def _format_financial_ratios(payload: dict[str, Any]) -> str:
    lines = ["### 재무비율", "", "| 지표 | 값 |", "|---|---|"]
    rows = _as_list(payload)[:MAX_RATIOS]
    if not rows:
        lines.append("| N/A | N/A |")
        return "\n".join(lines)
    for row in rows:
        name = _na(row.get("idx_nm") or row.get("idx_cl_nm") or row.get("account_nm"))
        value = _na(row.get("idx_val") or row.get("thstrm") or row.get("idx_value"))
        lines.append(f"| {name} | {value} |")
    return "\n".join(lines)


def _format_shareholders(payload: dict[str, Any]) -> str:
    lines = [
        "### 최대주주",
        "",
        "| 성명 | 관계 | 지분율(%) |",
        "|---|---|---|",
    ]
    rows = _as_list(payload)[:MAX_SHAREHOLDERS]
    if not rows:
        lines.append("| N/A | N/A | N/A |")
        return "\n".join(lines)
    for row in rows:
        name = _na(row.get("nm") or row.get("name"))
        relate = _na(row.get("relate") or row.get("relation"))
        ratio = _na(
            row.get("trmend_posesn_stock_qota_rt")
            or row.get("bsis_posesn_stock_qota_rt")
        )
        lines.append(f"| {name} | {relate} | {ratio} |")
    return "\n".join(lines)


def _format_dividend(payload: dict[str, Any]) -> str:
    lines = [
        "### 배당",
        "",
        "| 항목 | 당기 | 전기 |",
        "|---|---|---|",
    ]
    rows = _as_list(payload)[:MAX_DIVIDEND_ROWS]
    if not rows:
        lines.append("| N/A | N/A | N/A |")
        return "\n".join(lines)
    for row in rows:
        se = _na(row.get("se") or row.get("item"))
        current = _na(row.get("thstrm"))
        prior = _na(row.get("frmtrm"))
        lines.append(f"| {se} | {current} | {prior} |")
    return "\n".join(lines)


def _pick_accounts(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """핵심 계정명과 매칭되는 첫 행을 고릅니다."""
    picked: dict[str, dict[str, Any]] = {}
    for key in KEY_ACCOUNTS:
        for row in rows:
            name = str(row.get("account_nm") or "").replace(" ", "")
            if key in name or name in key:
                picked[key] = row
                break
    return picked


def _as_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("list")
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def _fmt_amount(raw: Any) -> str:
    if raw in (None, "", "-", "0"):
        if raw == "0":
            return "0"
        return "N/A"
    try:
        number = int(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return str(raw)
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:,.1f}억원"
    return f"{number:,}"


def _pretty_value(raw: Any) -> str:
    text = _na(raw)
    if text == "N/A":
        return text
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _one_line(text: str) -> str:
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return "N/A"
    if len(cleaned) > SUMMARY_LEN:
        return cleaned[: SUMMARY_LEN - 1] + "…"
    return cleaned


def _na(value: Any) -> str:
    if value in (None, "", "-"):
        return "N/A"
    return str(value).strip()
