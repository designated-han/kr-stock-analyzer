"""Naver 클라이언트 단위 테스트."""

from data.naver_client import _strip_html


def test_strip_html_removes_tags():
    assert _strip_html("<b>굵게</b>") == "굵게"


def test_strip_html_decodes_entities():
    assert _strip_html("A &amp; B &lt;C&gt;") == "A & B <C>"
    assert _strip_html("it&#39;s") == "it's"
    assert _strip_html("&apos;&#x27;") == "''"


def test_strip_html_empty():
    assert _strip_html("") == ""
