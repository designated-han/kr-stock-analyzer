"""HTML 리포트 변환."""

from output.report_builder import markdown_to_html


def test_markdown_to_html_renders_heading_and_table():
    source = """# 삼성전자 분석

| 항목 | 값 |
|---|---|
| 점수 | 7.5 |
"""
    html = markdown_to_html(source, "삼성전자")
    assert "<!DOCTYPE html>" in html
    assert "<title>삼성전자 투자분석 리포트</title>" in html
    assert "<h1>" in html
    assert "<table>" in html
    assert "<th>" in html
    assert "7.5" in html
    assert '<pre style="white-space: pre-wrap;">' not in html


def test_markdown_to_html_escapes_title():
    html = markdown_to_html("# 본문", '<script>alert(1)</script>')
    head = html.split("<body>", 1)[0]
    assert "<script>" not in head
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt; 투자분석 리포트</title>" in html
