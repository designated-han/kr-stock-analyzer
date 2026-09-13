"""DART Open API 클라이언트.

전자공시시스템(DART)에서 기업 정보, 재무제표, 공시 데이터를 조회합니다.
API 문서: https://opendart.fss.or.kr/guide/main.do
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
TIMEOUT = 30.0
CORP_CODE_TIMEOUT = 90.0
CACHE_PATH = Path(__file__).parent / "corp_codes.json"
CACHE_TTL = timedelta(days=7)
MAX_PARTIAL_HITS = 10

# 프로세스 내 인덱스. 테스트에서 None으로 리셋한다.
_CORP_INDEX: list[dict[str, str]] | None = None


class DartClient:
    """DART Open API 클라이언트."""

    def __init__(self, api_key: str | None = None):
        self.api_key = settings.dart_api_key if api_key is None else api_key
        self._client: httpx.AsyncClient | None = None
        if not self.api_key:
            logger.warning("DART API 키가 설정되지 않았습니다.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.close()

    async def __aenter__(self) -> DartClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def search_company(self, query: str) -> list[dict[str, str]]:
        """기업명 또는 종목코드로 기업 코드를 검색합니다.

        - 종목코드(최대 6자리 숫자): 완전 일치
        - 기업명 완전 일치: 해당 항목만 즉시 반환
        - 기업명 부분 일치: 상장사 우선, 최대 10건
        """
        needle = (query or "").strip()
        if not needle:
            return []

        index = await self._get_corp_index()
        if not index:
            return []

        if needle.isdigit() and len(needle) <= 6:
            code = needle.zfill(6)
            hits = [row for row in index if row.get("stock_code") == code]
            return hits[:MAX_PARTIAL_HITS]

        exact = [row for row in index if row.get("corp_name") == needle]
        if exact:
            return exact[:MAX_PARTIAL_HITS]

        partial = [row for row in index if needle in row.get("corp_name", "")]
        partial.sort(
            key=lambda row: (
                0 if row.get("stock_code") else 1,
                len(row.get("corp_name", "")),
                row.get("corp_name", ""),
            )
        )
        return partial[:MAX_PARTIAL_HITS]

    async def resolve_company(
        self,
        name: str = "",
        stock_code: str = "",
        corp_code: str = "",
    ) -> list[dict[str, str]]:
        """분석 입력에서 corp_code 후보를 찾습니다.

        corp_code가 있으면 검색하지 않습니다.
        stock_code가 있으면 종목코드 역조회를 이름 검색보다 우선합니다.
        """
        name = (name or "").strip()
        stock_code = (stock_code or "").strip()
        corp_code = (corp_code or "").strip()
        if corp_code:
            return [
                {
                    "corp_code": corp_code,
                    "corp_name": name,
                    "stock_code": stock_code,
                    "modify_date": "",
                }
            ]
        if stock_code:
            hits = await self.search_company(stock_code)
            if hits:
                return hits
        if name:
            return await self.search_company(name)
        return []

    async def _get_corp_index(self) -> list[dict[str, str]]:
        """캐시 또는 다운로드에서 기업코드 인덱스를 로드합니다."""
        global _CORP_INDEX
        if _CORP_INDEX is not None:
            return _CORP_INDEX

        if _cache_is_fresh(CACHE_PATH):
            loaded = _read_cache(CACHE_PATH)
            if loaded is not None:
                _CORP_INDEX = loaded
                logger.info(f"DART 기업코드 캐시 사용 ({len(loaded)}건)")
                return loaded

        if not self.api_key:
            stale = _read_cache(CACHE_PATH)
            if stale is not None:
                _CORP_INDEX = stale
                logger.warning("DART API 키 없음 — 만료/기존 캐시를 사용합니다.")
                return stale
            return []

        try:
            zip_bytes = await self._fetch_corp_code_zip()
            rows = _parse_corp_zip(zip_bytes)
            _write_cache(CACHE_PATH, rows)
            _CORP_INDEX = rows
            logger.info(f"DART 기업코드 갱신 완료 ({len(rows)}건)")
            return rows
        except Exception as e:
            logger.error(f"DART 기업코드 다운로드 실패: {e}")
            stale = _read_cache(CACHE_PATH)
            if stale is not None:
                _CORP_INDEX = stale
                logger.warning("기존 캐시로 검색을 계속합니다.")
                return stale
            return []

    async def _fetch_corp_code_zip(self) -> bytes:
        """corpCode.xml ZIP을 다운로드합니다."""
        url = f"{BASE_URL}/corpCode.xml"
        client = await self._get_client()
        response = await client.get(
            url,
            params={"crtfc_key": self.api_key},
            timeout=CORP_CODE_TIMEOUT,
        )
        response.raise_for_status()
        return response.content

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        """DART API GET 요청."""
        params = params or {}
        params["crtfc_key"] = self.api_key

        client = await self._get_client()
        response = await client.get(f"{BASE_URL}/{endpoint}.json", params=params)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "000":
            msg = data.get("message", "알 수 없는 오류")
            logger.warning(f"DART API 오류 [{endpoint}]: {msg}")
            return {}
        return data

    async def get_company_info(self, corp_code: str) -> dict:
        """기업 개황 정보를 조회합니다."""
        return await self._get("company", {"corp_code": corp_code})

    async def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",  # 사업보고서
        fs_div: str = "CFS",  # 연결재무제표
    ) -> dict:
        """재무제표 주요 계정을 조회합니다.

        Args:
            corp_code: 기업코드
            bsns_year: 사업연도 (예: "2024")
            reprt_code: 보고서 코드 (11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기)
            fs_div: 재무제표 구분 (CFS=연결, OFS=별도)
        """
        return await self._get(
            "fnlttSinglAcntAll",
            {
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
        )

    async def get_financial_ratios(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
    ) -> dict:
        """주요 재무비율을 조회합니다."""
        return await self._get(
            "fnlttCmpnyIndx",
            {
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
            },
        )

    async def get_disclosures(
        self,
        corp_code: str,
        bgn_de: str = "",
        end_de: str = "",
        page_count: int = 10,
    ) -> dict:
        """공시 목록을 조회합니다.

        Args:
            corp_code: 기업코드
            bgn_de: 시작일 (YYYYMMDD)
            end_de: 종료일 (YYYYMMDD)
            page_count: 조회 건수
        """
        params: dict[str, Any] = {
            "corp_code": corp_code,
            "page_count": str(page_count),
        }
        if bgn_de:
            params["bgn_de"] = bgn_de
        if end_de:
            params["end_de"] = end_de
        return await self._get("list", params)

    async def get_major_shareholders(self, corp_code: str, bsns_year: str) -> dict:
        """최대주주 현황을 조회합니다."""
        return await self._get(
            "hyslrSttus",
            {
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": "11011",
            },
        )

    async def get_dividend_info(self, corp_code: str, bsns_year: str) -> dict:
        """배당 정보를 조회합니다."""
        return await self._get(
            "alotMatter",
            {
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": "11011",
            },
        )

    async def collect_all(self, corp_code: str, bsns_year: str) -> dict[str, Any]:
        """분석에 필요한 전체 데이터를 수집합니다.

        Returns:
            각 API 결과를 키로 묶은 딕셔너리
        """
        results = await asyncio.gather(
            self.get_company_info(corp_code),
            self.get_financial_statements(corp_code, bsns_year),
            self.get_financial_ratios(corp_code, bsns_year),
            self.get_disclosures(corp_code),
            self.get_major_shareholders(corp_code, bsns_year),
            self.get_dividend_info(corp_code, bsns_year),
            return_exceptions=True,
        )

        keys = [
            "company_info",
            "financial_statements",
            "financial_ratios",
            "disclosures",
            "major_shareholders",
            "dividend_info",
        ]
        collected = {}
        for key, result in zip(keys, results, strict=True):
            if isinstance(result, Exception):
                logger.error(f"DART 데이터 수집 실패 [{key}]: {result}")
                collected[key] = {}
            else:
                collected[key] = result

        return collected


def _cache_is_fresh(path: Path) -> bool:
    """캐시 파일이 있고 TTL 이내이면 True."""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime < CACHE_TTL


def _read_cache(path: Path) -> list[dict[str, str]] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"기업코드 캐시 읽기 실패: {e}")
        return None
    if not isinstance(data, list):
        return None
    rows: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or "corp_code" not in item:
            continue
        rows.append(
            {
                "corp_code": str(item.get("corp_code", "")).strip(),
                "corp_name": str(item.get("corp_name", "")).strip(),
                "stock_code": str(item.get("stock_code", "")).strip(),
                "modify_date": str(item.get("modify_date", "")).strip(),
            }
        )
    return rows


def _write_cache(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _parse_corp_zip(zip_bytes: bytes) -> list[dict[str, str]]:
    """ZIP 안의 XML을 파싱해 기업코드 리스트를 만듭니다."""
    xml_bytes = _unzip_xml(zip_bytes)
    text = _decode_xml(xml_bytes)
    root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    for node in root.iter("list"):
        rows.append(
            {
                "corp_code": _xml_text(node, "corp_code"),
                "corp_name": _xml_text(node, "corp_name"),
                "stock_code": _xml_text(node, "stock_code"),
                "modify_date": _xml_text(node, "modify_date"),
            }
        )
    return rows


def _unzip_xml(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        xml_name = next(
            (n for n in names if n.lower().endswith(".xml")),
            names[0] if names else "",
        )
        if not xml_name:
            raise ValueError("ZIP 안에 XML 파일이 없습니다.")
        return zf.read(xml_name)


def _decode_xml(raw: bytes) -> str:
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _xml_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()

