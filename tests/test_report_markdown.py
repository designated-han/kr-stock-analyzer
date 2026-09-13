"""Markdown 리포트 빌더 테스트."""

from core.models import CompanyInfo, ConsensusOpinion, SynthesisResult
from output.report_builder import build_markdown_report


def test_build_markdown_report_structure():
    result = SynthesisResult(
        company=CompanyInfo(name="테스트기업", stock_code="000000"),
        overall_score=7.5,
        consensus=ConsensusOpinion.BUY,
        key_points=["포인트1", "포인트2"],
        analyst_results=[],
        philosophy_results=[],
        executive_summary="테스트 요약",
    )
    md = build_markdown_report(result)
    assert "# 테스트기업 투자분석 리포트" in md
    assert "7.5 / 10" in md
    assert "포인트1" in md
    assert "투자 권유가 아닙니다" in md
