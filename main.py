"""KR Stock Analyzer — CLI 진입점.

사용법:
    python main.py 삼성전자 --stock-code 005930
    python main.py 삼성전자 --stock-code 005930 --depth deep
    python main.py 삼성전자 --corp-code 00126380 --output html
"""

import argparse
import asyncio
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

from core.models import AnalysisRequest, CompanyInfo
from core.orchestrator import run_pipeline
from output.report_builder import save_report

console = Console()


def setup_logging(verbose: bool = False) -> None:
    """로깅 설정."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def parse_args() -> argparse.Namespace:
    """CLI 인자 파싱."""
    parser = argparse.ArgumentParser(
        description="한국 상장기업 AI 멀티에이전트 분석 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("company", help="분석 대상 기업명")
    parser.add_argument("--stock-code", default="", help="종목코드 (6자리, 예: 005930)")
    parser.add_argument("--corp-code", default="", help="DART 기업코드 (8자리)")
    parser.add_argument("--market", default="KOSPI", choices=["KOSPI", "KOSDAQ"], help="시장 (기본: KOSPI)")
    parser.add_argument("--industry", default="", help="업종")
    parser.add_argument("--depth", default="standard", choices=["quick", "standard", "deep"], help="분석 깊이")
    parser.add_argument("--output", default="md", choices=["md", "html"], help="출력 형식")
    parser.add_argument("--output-dir", default=None, help="출력 디렉토리")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 로그 출력")

    return parser.parse_args()


async def main() -> None:
    """메인 실행 함수."""
    args = parse_args()
    setup_logging(args.verbose)

    # 기업 정보 구성
    company = CompanyInfo(
        name=args.company,
        stock_code=args.stock_code,
        corp_code=args.corp_code,
        market=args.market,
        industry=args.industry,
    )

    request = AnalysisRequest(company=company, depth=args.depth)

    console.print(
        Panel(
            f"[bold]{company.name}[/bold]\n"
            f"종목코드: {company.stock_code or '미지정'} | "
            f"시장: {company.market} | "
            f"분석 깊이: {request.depth}",
            title="분석 대상",
            border_style="blue",
        )
    )

    try:
        # 파이프라인 실행
        with console.status("[bold green]분석 중..."):
            result = await run_pipeline(request)

        # 결과 출력
        console.print()
        console.print(
            Panel(
                f"[bold]종합 점수: {result.overall_score:.1f} / 10[/bold]\n"
                f"투자 의견: [bold]{result.consensus.value}[/bold]\n\n"
                f"{result.executive_summary}",
                title="분석 결과",
                border_style="green" if result.overall_score >= 6 else "red",
            )
        )

        # 리포트 저장
        from pathlib import Path

        output_dir = Path(args.output_dir) if args.output_dir else None
        filepath = save_report(result, output_format=args.output, output_dir=output_dir)
        console.print(f"\n[dim]리포트 저장: {filepath}[/dim]")

    except Exception as e:
        console.print(f"[bold red]오류 발생:[/bold red] {e}")
        logging.getLogger(__name__).exception("분석 실패")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
