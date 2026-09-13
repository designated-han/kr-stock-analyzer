"""데이터 수집 계층: DART/Naver 병렬 수집, 포맷, 메시지 주입."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core.models import AgentResult, AnalysisRequest, CompanyInfo, Conviction
from core.orchestrator import (
    _build_company_message,
    _collect_data,
    _latest_bsns_year,
    run_pipeline,
)
from data.formatter import format_dart_data, format_news_data


def _request(**kwargs) -> AnalysisRequest:
    company = CompanyInfo(
        name=kwargs.get("name", "삼성전자"),
        stock_code=kwargs.get("stock_code", "005930"),
        corp_code=kwargs.get("corp_code", ""),
        market="KOSPI",
    )
    return AnalysisRequest(company=company, depth=kwargs.get("depth", "standard"))


# ── bsns_year ─────────────────────────────────────────────


def test_bsns_year_before_april_uses_year_minus_2():
    assert _latest_bsns_year(datetime(2026, 3, 31)) == "2024"


def test_bsns_year_from_april_uses_year_minus_1():
    assert _latest_bsns_year(datetime(2026, 4, 1)) == "2025"


# ── _collect_data ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_collect_data_skips_when_keys_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.orchestrator.settings.dart_api_key", "")
    monkeypatch.setattr("core.orchestrator.settings.naver_client_id", "")
    result = await _collect_data(_request(corp_code="00126380"))
    assert result == {}


@pytest.mark.asyncio
async def test_collect_data_skips_dart_without_corp_code(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.orchestrator.settings.dart_api_key", "dart-key")
    monkeypatch.setattr("core.orchestrator.settings.naver_client_id", "")
    result = await _collect_data(_request(corp_code=""))
    assert result == {}


@pytest.mark.asyncio
async def test_collect_data_runs_dart_and_news(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.orchestrator.settings.dart_api_key", "dart-key")
    monkeypatch.setattr("core.orchestrator.settings.naver_client_id", "naver-id")

    dart_mock = AsyncMock(return_value={"company_info": {"corp_name": "삼성전자"}})
    news_mock = AsyncMock(return_value={"news": [{"title": "실적"}]})

    class FakeDart:
        def __init__(self):
            self.collect_all = dart_mock

    class FakeNaver:
        def __init__(self):
            self.collect_company_news = news_mock

    monkeypatch.setattr("core.orchestrator.DartClient", FakeDart)
    monkeypatch.setattr("core.orchestrator.NaverClient", FakeNaver)

    result = await _collect_data(_request(corp_code="00126380"))
    assert result["dart"]["company_info"]["corp_name"] == "삼성전자"
    assert result["news"]["news"][0]["title"] == "실적"
    dart_mock.assert_awaited_once()
    year = dart_mock.await_args.args[1]
    assert year == _latest_bsns_year()
    news_mock.assert_awaited_once()
    assert news_mock.await_args.kwargs["keywords"] == ["실적", "전망", "투자"]


@pytest.mark.asyncio
async def test_collect_data_exception_becomes_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.orchestrator.settings.dart_api_key", "dart-key")
    monkeypatch.setattr("core.orchestrator.settings.naver_client_id", "")

    class FakeDart:
        async def collect_all(self, corp_code, bsns_year):
            raise RuntimeError("timeout")

    monkeypatch.setattr("core.orchestrator.DartClient", FakeDart)
    result = await _collect_data(_request(corp_code="00126380"))
    assert result == {"dart": {}}


# ── formatter ─────────────────────────────────────────────


SAMPLE_DART = {
    "company_info": {
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "ceo_nm": "한종희",
        "adres": "수원",
        "est_dt": "19690113",
        "hm_url": "www.samsung.com",
    },
    "financial_statements": {
        "list": [
            {
                "account_nm": "자산총계",
                "thstrm_amount": "455905980000000",
                "frmtrm_amount": "400000000000000",
            },
            {
                "account_nm": "매출액",
                "thstrm_amount": "300000000000000",
                "frmtrm_amount": "280000000000000",
            },
            {
                "account_nm": "잡손실",
                "thstrm_amount": "1",
                "frmtrm_amount": "1",
            },
        ]
    },
    "financial_ratios": {
        "list": [
            {"idx_nm": "ROE", "idx_val": "15.2"},
            {"idx_nm": "부채비율", "idx_val": "40.1"},
        ]
    },
    "major_shareholders": {
        "list": [
            {
                "nm": "이재용",
                "relate": "최대주주",
                "trmend_posesn_stock_qota_rt": "8.13",
            }
        ]
    },
    "dividend_info": {
        "list": [
            {"se": "현금배당성향(%)", "thstrm": "20", "frmtrm": "18"},
        ]
    },
}


def test_format_dart_data_keeps_all_sections_and_key_accounts():
    md = format_dart_data(SAMPLE_DART)
    for heading in ("기업 개황", "재무제표 주요 계정", "재무비율", "최대주주", "배당"):
        assert heading in md
    assert "삼성전자" in md
    assert "자산총계" in md
    assert "매출액" in md
    assert "잡손실" not in md  # 핵심 계정만
    assert "ROE" in md
    assert "이재용" in md
    assert "현금배당성향" in md


def test_format_dart_data_empty_shows_na():
    md = format_dart_data({})
    assert md.count("N/A") >= 5
    assert "기업 개황" in md
    assert "재무제표 주요 계정" in md
    assert "재무비율" in md
    assert "최대주주" in md
    assert "배당" in md


def test_format_news_data_caps_at_15():
    items = [
        {
            "title": f"뉴스{i}",
            "pubDate": "Mon, 01 Sep 2026 09:00:00 +0900",
            "description": f"요약{i} " + ("길게 " * 40),
        }
        for i in range(20)
    ]
    md = format_news_data({"news": items})
    assert md.count("뉴스") == 15
    assert "뉴스15" not in md
    assert "뉴스0" in md


# ── message / pipeline ────────────────────────────────────


def test_build_company_message_includes_formatted_data():
    news = {"news": [{"title": "호실적", "pubDate": "어제", "description": "매출"}]}
    msg = _build_company_message(
        _request(corp_code="00126380"),
        {"dart": SAMPLE_DART, "news": news},
    )
    assert "## DART 공시 데이터" in msg
    assert "## 최근 뉴스" in msg
    assert "삼성전자" in msg
    assert "호실적" in msg
    assert "분석 깊이: standard" in msg
    assert "일반 지식" not in msg


def test_build_company_message_warns_when_empty():
    msg = _build_company_message(_request(), {})
    assert "외부 데이터 수집 불가" in msg


@pytest.mark.asyncio
async def test_pipeline_injects_collected_data(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, str] = {}

    async def fake_collect(request):
        return {
            "dart": SAMPLE_DART,
            "news": {"news": [{"title": "호실적", "pubDate": "어제", "description": "매출"}]},
        }

    async def fake_run_agent(agent_name: str, user_message: str = "", **kwargs):
        captured[agent_name] = user_message
        return AgentResult(
            agent=agent_name,
            score=6.5,
            conviction=Conviction.POSITIVE,
            summary="ok",
        )

    monkeypatch.setattr("core.orchestrator._collect_data", fake_collect)
    monkeypatch.setattr("core.orchestrator.run_agent", fake_run_agent)
    monkeypatch.setattr("core.orchestrator.ANALYST_AGENTS", ["financial"])
    monkeypatch.setattr("core.orchestrator.PHILOSOPHY_AGENTS", ["buffett"])

    await run_pipeline(_request(corp_code="00126380"))
    assert "## DART 공시 데이터" in captured["financial"]
    assert "호실적" in captured["buffett"]
