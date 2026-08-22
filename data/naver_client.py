"""Naver Search API 클라이언트.

네이버 검색 API를 통해 뉴스, 블로그 데이터를 수집합니다.
API 문서: https://developers.naver.com/docs/serviceapi/search/news/news.md
"""

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi.naver.com/v1/search"
TIMEOUT = 15.0


class NaverClient:
    """Naver Search API 클라이언트."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.client_id = client_id or settings.naver_client_id
        self.client_secret = client_secret or settings.naver_client_secret
        if not self.client_id:
            logger.warning("Naver API 키가 설정되지 않았습니다.")

    def _headers(self) -> dict[str, str]:
        return {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

    async def _search(
        self,
        endpoint: str,
        query: str,
        display: int = 10,
        sort: str = "date",
    ) -> dict:
        """네이버 검색 API 공통 호출."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/{endpoint}",
                headers=self._headers(),
                params={
                    "query": query,
                    "display": display,
                    "sort": sort,
                },
            )
            response.raise_for_status()
            return response.json()

    async def search_news(
        self,
        query: str,
        display: int = 20,
        sort: str = "date",
    ) -> list[dict[str, Any]]:
        """뉴스 검색.

        Args:
            query: 검색어 (예: "삼성전자 실적")
            display: 결과 수 (최대 100)
            sort: 정렬 (date=최신순, sim=정확도순)

        Returns:
            뉴스 항목 리스트
        """
        data = await self._search("news.json", query, display, sort)
        items = data.get("items", [])
        # HTML 태그 제거
        for item in items:
            item["title"] = _strip_html(item.get("title", ""))
            item["description"] = _strip_html(item.get("description", ""))
        return items

    async def search_blog(
        self,
        query: str,
        display: int = 10,
        sort: str = "sim",
    ) -> list[dict[str, Any]]:
        """블로그 검색."""
        data = await self._search("blog.json", query, display, sort)
        items = data.get("items", [])
        for item in items:
            item["title"] = _strip_html(item.get("title", ""))
            item["description"] = _strip_html(item.get("description", ""))
        return items

    async def collect_company_news(
        self,
        company_name: str,
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """기업 관련 뉴스와 블로그를 종합 수집합니다.

        Args:
            company_name: 기업명
            keywords: 추가 검색 키워드 (예: ["실적", "전망"])

        Returns:
            {"news": [...], "blog": [...], "sentiment_summary": "..."}
        """
        import asyncio

        # 기본 검색 + 키워드별 검색
        queries = [company_name]
        if keywords:
            queries.extend([f"{company_name} {kw}" for kw in keywords[:3]])

        news_tasks = [self.search_news(q, display=10) for q in queries]
        blog_task = self.search_blog(company_name, display=5)

        results = await asyncio.gather(*news_tasks, blog_task, return_exceptions=True)

        # 뉴스 결과 합치기 (중복 제거)
        all_news = []
        seen_links = set()
        for result in results[:-1]:
            if isinstance(result, Exception):
                logger.warning(f"뉴스 검색 실패: {result}")
                continue
            for item in result:
                link = item.get("link", "")
                if link not in seen_links:
                    seen_links.add(link)
                    all_news.append(item)

        blog_results = results[-1] if not isinstance(results[-1], Exception) else []

        return {
            "news": all_news[:30],  # 최대 30건
            "blog": blog_results,
            "total_news_count": len(all_news),
        }


def _strip_html(text: str) -> str:
    """간단한 HTML 태그 제거."""
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
