"""DART Open API 클라이언트.

전자공시시스템(DART)에서 기업 정보, 재무제표, 공시 데이터를 조회합니다.
API 문서: https://opendart.fss.or.kr/guide/main.do
"""

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
TIMEOUT = 30.0


class DartClient:
    """DART Open API 클라이언트."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.dart_api_key
        if not self.api_key:
            logger.warning("DART API 키가 설정되지 않았습니다.")

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        """DART API GET 요청."""
        params = params or {}
        params["crtfc_key"] = self.api_key

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{BASE_URL}/{endpoint}.json", params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "000":
            msg = data.get("message", "알 수 없는 오류")
            logger.warning(f"DART API 오류 [{endpoint}]: {msg}")
            return {}
        return data

    async def search_company(self, company_name: str) -> dict:
        """기업명으로 기업 코드를 검색합니다.

        Note: DART는 기업명 검색 API를 직접 제공하지 않으므로,
              기업코드 파일(corpCode.xml)을 다운로드하거나 corp_code를 직접 입력해야 합니다.
              여기서는 기업코드가 이미 알려진 경우를 위한 스텁입니다.
        """
        # TODO: corpCode.xml 다운로드 및 로컬 캐시 구현
        logger.info(f"기업 검색: {company_name} (corp_code 필요)")
        return {}

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
        import asyncio

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
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                logger.error(f"DART 데이터 수집 실패 [{key}]: {result}")
                collected[key] = {}
            else:
                collected[key] = result

        return collected
