"""DART search_company: ZIP/XML 파싱, 캐시, 이름/종목코드 검색."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from data import dart_client
from data.dart_client import DartClient

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list>
    <corp_code>00126380</corp_code>
    <corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code>
    <modify_date>20240301</modify_date>
  </list>
  <list>
    <corp_code>00164779</corp_code>
    <corp_name>삼성전자우</corp_name>
    <stock_code>005935</stock_code>
    <modify_date>20240301</modify_date>
  </list>
  <list>
    <corp_code>00401731</corp_code>
    <corp_name>삼성SDI</corp_name>
    <stock_code>006400</stock_code>
    <modify_date>20240301</modify_date>
  </list>
  <list>
    <corp_code>09999999</corp_code>
    <corp_name>삼성비상장테스트</corp_name>
    <stock_code></stock_code>
    <modify_date>20240101</modify_date>
  </list>
</result>
"""


def _zip_xml(xml: str = SAMPLE_XML) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dart_client, "CACHE_PATH", tmp_path / "corp_codes.json")
    dart_client._CORP_INDEX = None
    yield
    dart_client._CORP_INDEX = None


def _client_with_zip(monkeypatch: pytest.MonkeyPatch, xml: str = SAMPLE_XML) -> DartClient:
    payload = _zip_xml(xml)

    async def fake_fetch(self) -> bytes:
        fake_fetch.calls += 1
        return payload

    fake_fetch.calls = 0
    monkeypatch.setattr(DartClient, "_fetch_corp_code_zip", fake_fetch)
    client = DartClient(api_key="test-key")
    client._fetch_calls = lambda: fake_fetch.calls  # type: ignore[method-assign]
    return client


@pytest.mark.asyncio
async def test_search_exact_name_returns_immediately(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_zip(monkeypatch)
    hits = await client.search_company("삼성전자")
    assert len(hits) == 1
    assert hits[0]["corp_code"] == "00126380"
    assert hits[0]["stock_code"] == "005930"
    assert hits[0]["corp_name"] == "삼성전자"


@pytest.mark.asyncio
async def test_search_partial_name_caps_at_10(monkeypatch: pytest.MonkeyPatch):
    entries = []
    for i in range(15):
        entries.append(
            f"""  <list>
    <corp_code>{i:08d}</corp_code>
    <corp_name>테스트기업{i:02d}</corp_name>
    <stock_code>{i:06d}</stock_code>
    <modify_date>20240301</modify_date>
  </list>"""
        )
    xml = '<?xml version="1.0" encoding="UTF-8"?><result>\n' + "\n".join(entries) + "\n</result>"
    client = _client_with_zip(monkeypatch, xml)
    hits = await client.search_company("테스트기업")
    assert len(hits) == 10


@pytest.mark.asyncio
async def test_search_by_stock_code(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_zip(monkeypatch)
    hits = await client.search_company("005930")
    assert len(hits) == 1
    assert hits[0]["corp_name"] == "삼성전자"
    # 앞에 0이 없는 코드도 매칭
    hits2 = await client.search_company("5930")
    assert hits2[0]["corp_code"] == "00126380"


@pytest.mark.asyncio
async def test_partial_prefers_listed_companies(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_zip(monkeypatch)
    hits = await client.search_company("삼성")
    assert hits[0]["stock_code"]  # 상장 우선
    names = [h["corp_name"] for h in hits]
    assert "삼성전자" in names


@pytest.mark.asyncio
async def test_cache_avoids_second_download(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_zip(monkeypatch)
    await client.search_company("삼성전자")
    dart_client._CORP_INDEX = None
    client2 = DartClient(api_key="test-key")
    # 같은 fake_fetch가 클래스에 패치되어 있음
    hits = await client2.search_company("삼성전자")
    assert hits[0]["corp_code"] == "00126380"
    assert client._fetch_calls() == 1
    assert dart_client.CACHE_PATH.exists()
    cached = json.loads(dart_client.CACHE_PATH.read_text(encoding="utf-8"))
    assert cached[0]["corp_code"] == "00126380"


@pytest.mark.asyncio
async def test_expired_cache_redownloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client_with_zip(monkeypatch)
    await client.search_company("삼성전자")
    path = dart_client.CACHE_PATH
    old = time.time() - 8 * 24 * 3600
    path.touch()
    # touch 후 mtime이 now가 되므로 다시 과거로 설정
    import os

    os.utime(path, (old, old))
    dart_client._CORP_INDEX = None
    await DartClient(api_key="test-key").search_company("삼성SDI")
    assert client._fetch_calls() == 2


@pytest.mark.asyncio
async def test_no_api_key_returns_empty():
    client = DartClient(api_key="")
    assert await client.search_company("삼성전자") == []


@pytest.mark.asyncio
async def test_resolve_company_stock_code_before_name(monkeypatch: pytest.MonkeyPatch):
    client = _client_with_zip(monkeypatch)
    hits = await client.resolve_company(name="삼성SDI", stock_code="005930")
    assert hits[0]["corp_name"] == "삼성전자"


@pytest.mark.asyncio
async def test_resolve_company_skips_search_when_corp_code_given(
    monkeypatch: pytest.MonkeyPatch,
):
    client = _client_with_zip(monkeypatch)
    hits = await client.resolve_company(
        name="아무거나", stock_code="", corp_code="00126380"
    )
    assert hits == [
        {
            "corp_code": "00126380",
            "corp_name": "아무거나",
            "stock_code": "",
            "modify_date": "",
        }
    ]
    assert client._fetch_calls() == 0
