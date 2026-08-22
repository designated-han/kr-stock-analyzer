"""리포트 생성기.

SynthesisResult를 Markdown 및 HTML 리포트로 변환합니다.
PDF 변환은 weasyprint가 설치된 경우에만 지원됩니다.
"""

import logging
from datetime import datetime
from pathlib import Path

from core.models import SynthesisResult, AgentResult

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent
TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_markdown_report(result: SynthesisResult) -> str:
    """SynthesisResult를 Markdown 리포트로 변환합니다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    company = result.company

    lines = [
        f"# {company.name} 투자분석 리포트",
        f"",
        f"> 생성일: {now} | 시장: {company.market} | 종목코드: {company.stock_code}",
        f"",
        f"---",
        f"",
        f"## Executive Summary",
        f"",
        f"**종합 점수: {result.overall_score:.1f} / 10**",
        f"",
        f"**투자 의견: {result.consensus.value}**",
        f"",
        f"{result.executive_summary}",
        f"",
        f"---",
        f"",
        f"## 핵심 투자 포인트",
        f"",
    ]

    for i, point in enumerate(result.key_points, 1):
        lines.append(f"{i}. {point}")
    lines.append("")

    # 의견 일치/충돌
    if result.agreements:
        lines.append("## 의견 일치 사항")
        lines.append("")
        for item in result.agreements:
            lines.append(f"- {item}")
        lines.append("")

    if result.conflicts:
        lines.append("## 의견 충돌 사항")
        lines.append("")
        for item in result.conflicts:
            lines.append(f"- {item}")
        lines.append("")

    # 실무 분석 결과
    lines.append("---")
    lines.append("")
    lines.append("## 실무 분석 상세")
    lines.append("")
    for agent_result in result.analyst_results:
        lines.extend(_format_agent_section(agent_result))

    # 철학 평가 결과
    lines.append("---")
    lines.append("")
    lines.append("## 투자 철학 평가")
    lines.append("")
    for agent_result in result.philosophy_results:
        lines.extend(_format_agent_section(agent_result))

    # 리스크 종합
    lines.append("---")
    lines.append("")
    lines.append("## 리스크 종합")
    lines.append("")
    all_risks = []
    for ar in result.analyst_results + result.philosophy_results:
        all_risks.extend(ar.risks)

    if all_risks:
        # 리스크 점수(심각도×확률) 내림차순 정렬
        all_risks.sort(key=lambda r: r.severity * r.probability, reverse=True)
        lines.append("| 리스크 | 심각도 | 확률 | 위험점수 | 설명 |")
        lines.append("|--------|--------|------|----------|------|")
        for risk in all_risks[:10]:
            score = risk.severity * risk.probability
            lines.append(
                f"| {risk.title} | {risk.severity}/5 | {risk.probability}/5 | {score}/25 | {risk.description} |"
            )
        lines.append("")

    # 면책 조항
    lines.append("---")
    lines.append("")
    lines.append("*이 리포트는 AI 멀티에이전트 시스템에 의해 자동 생성되었으며, "
                  "투자 권유가 아닙니다. 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.*")
    lines.append("")

    return "\n".join(lines)


def _format_agent_section(result: AgentResult) -> list[str]:
    """개별 에이전트 결과를 Markdown 섹션으로 변환합니다."""
    agent_labels = {
        "financial": "재무분석",
        "industry": "산업분석",
        "risk": "리스크분석",
        "technical": "기술분석",
        "economist": "이코노미스트",
        "buffett": "버핏/그레이엄 (가치투자)",
        "lynch": "피터 린치 (GARP)",
        "dalio": "레이 달리오 (매크로)",
    }
    label = agent_labels.get(result.agent, result.agent)

    lines = [
        f"### {label}",
        f"",
        f"**점수: {result.score}/10 | 확신도: {result.conviction.value}**",
        f"",
        f"{result.summary}",
        f"",
    ]

    if result.evidence:
        lines.append("**근거:**")
        lines.append("")
        for ev in result.evidence:
            source_note = f" ({ev.source})" if ev.source else ""
            lines.append(f"- {ev.claim}: {ev.data}{source_note}")
        lines.append("")

    if result.risks:
        lines.append("**주요 리스크:**")
        lines.append("")
        for risk in result.risks[:3]:
            lines.append(f"- {risk.title} (심각도 {risk.severity}/5): {risk.description}")
        lines.append("")

    return lines


def save_report(
    result: SynthesisResult,
    output_format: str = "md",
    output_dir: Path | None = None,
) -> Path:
    """리포트를 파일로 저장합니다.

    Args:
        result: 합성 결과
        output_format: 출력 형식 ("md" 또는 "html")
        output_dir: 저장 디렉토리 (None이면 output/)

    Returns:
        저장된 파일 경로
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    company_name = result.company.name.replace(" ", "_")

    markdown = build_markdown_report(result)

    if output_format == "md":
        filepath = output_dir / f"{company_name}_{timestamp}.md"
        filepath.write_text(markdown, encoding="utf-8")
    elif output_format == "html":
        html = _markdown_to_html(markdown, result.company.name)
        filepath = output_dir / f"{company_name}_{timestamp}.html"
        filepath.write_text(html, encoding="utf-8")
    else:
        raise ValueError(f"지원하지 않는 형식: {output_format}")

    logger.info(f"리포트 저장: {filepath}")
    return filepath


def _markdown_to_html(markdown_text: str, title: str) -> str:
    """Markdown을 간단한 HTML로 변환합니다.

    별도 라이브러리 없이 기본 변환을 수행합니다.
    고품질 변환이 필요하면 markdown 또는 mistune 패키지를 사용하세요.
    """
    # 기본 HTML 래퍼
    html_body = markdown_text
    # 간단한 변환 (프로덕션에서는 markdown 라이브러리 권장)
    html_body = html_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} 투자분석 리포트</title>
    <style>
        body {{ font-family: 'Pretendard', -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; line-height: 1.7; color: #1a1a1a; }}
        h1 {{ color: #1e3a5f; border-bottom: 3px solid #1e3a5f; padding-bottom: 0.5rem; }}
        h2 {{ color: #2c5282; margin-top: 2rem; }}
        h3 {{ color: #3182ce; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 0.5rem; text-align: left; }}
        th {{ background: #edf2f7; }}
        blockquote {{ border-left: 4px solid #3182ce; padding-left: 1rem; color: #4a5568; }}
        hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 2rem 0; }}
    </style>
</head>
<body>
<pre style="white-space: pre-wrap;">{html_body}</pre>
</body>
</html>"""
