"""DART API 응답 파싱 및 collect_all 부분 실패."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data.dart_client import DartClient

COMPANY_OK = {
    "status": "000",
    "message": "정상",
    "corp_name": "삼성전자",
    "corp_code": "00126380",
    "stock_code": "005930",
}

FS_OK = {
    "status": "000",
    "message": "정상",
    "list": [
        {"account_nm": "매출액", "thstrm_amount": "300000000000000"},
        {"account_nm": "자산총계", "thstrm_amount": "455905980000000"},
    ],
}

NOT_FOUND = {
    "status": "013",
    "message": "조회된 데이타가 없습니다.",
}


def _json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    return response


def _patch_httpx_get(monkeypatch: pytest.MonkeyPatch, payload: dict) -> AsyncMock:
    response = _json_response(payload)
    get = AsyncMock(return_value=response)
    instance = MagicMock()
    instance.get = get
    instance.is_closed = False
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "data.dart_client.httpx.AsyncClient",
        lambda *args, **kwargs: instance,
    )
    return get


@pytest.mark.asyncio
async def test_get_company_info_parses_success(monkeypatch: pytest.MonkeyPatch):
    get = _patch_httpx_get(monkeypatch, COMPANY_OK)
    client = DartClient(api_key="test-key")

    data = await client.get_company_info("00126380")

    assert data["corp_name"] == "삼성전자"
    assert data["stock_code"] == "005930"
    assert data["status"] == "000"
    get.assert_awaited_once()
    url = get.await_args.args[0]
    params = get.await_args.kwargs["params"]
    assert url.endswith("/company.json")
    assert params["crtfc_key"] == "test-key"
    assert params["corp_code"] == "00126380"


@pytest.mark.asyncio
async def test_get_financial_statements_parses_account_list(monkeypatch: pytest.MonkeyPatch):
    _patch_httpx_get(monkeypatch, FS_OK)
    client = DartClient(api_key="test-key")

    data = await client.get_financial_statements("00126380", "2024")

    names = [row["account_nm"] for row in data["list"]]
    assert names == ["매출액", "자산총계"]
    assert data["list"][0]["thstrm_amount"] == "300000000000000"


@pytest.mark.asyncio
async def test_get_returns_empty_when_status_is_not_ok(monkeypatch: pytest.MonkeyPatch):
    _patch_httpx_get(monkeypatch, NOT_FOUND)
    client = DartClient(api_key="test-key")

    assert await client.get_company_info("00000000") == {}
    assert await client.get_financial_ratios("00000000", "2024") == {}


@pytest.mark.asyncio
async def test_get_reuses_shared_httpx_client(monkeypatch: pytest.MonkeyPatch):
    get = AsyncMock(return_value=_json_response(COMPANY_OK))
    instance = MagicMock()
    instance.get = get
    instance.is_closed = False
    instance.close = AsyncMock()
    created = MagicMock(return_value=instance)
    monkeypatch.setattr("data.dart_client.httpx.AsyncClient", created)

    client = DartClient(api_key="test-key")
    await client.get_company_info("00126380")
    await client.get_financial_ratios("00126380", "2024")
    assert created.call_count == 1
    assert get.await_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_collect_all_keeps_success_when_one_endpoint_fails():
    client = DartClient(api_key="test-key")
    client.get_company_info = AsyncMock(return_value=COMPANY_OK)
    client.get_financial_statements = AsyncMock(side_effect=RuntimeError("timeout"))
    client.get_financial_ratios = AsyncMock(return_value={"status": "000", "list": []})
    client.get_disclosures = AsyncMock(return_value={"status": "000", "list": []})
    client.get_major_shareholders = AsyncMock(return_value={"status": "000"})
    client.get_dividend_info = AsyncMock(return_value={"status": "000"})

    collected = await client.collect_all("00126380", "2024")

    assert collected["company_info"]["corp_name"] == "삼성전자"
    assert collected["financial_statements"] == {}
    assert collected["financial_ratios"] == {"status": "000", "list": []}
    assert collected["disclosures"] == {"status": "000", "list": []}
    assert collected["major_shareholders"] == {"status": "000"}
    assert collected["dividend_info"] == {"status": "000"}
    assert set(collected) == {
        "company_info",
        "financial_statements",
        "financial_ratios",
        "disclosures",
        "major_shareholders",
        "dividend_info",
    }
