"""KR Stock Analyzer — Streamlit 프론트엔드.

실행: streamlit run app.py
"""

import asyncio
import logging
import time

import streamlit as st

from core.models import AnalysisRequest, CompanyInfo, AgentResult, SynthesisResult
from core.orchestrator import run_pipeline

# ── 페이지 설정 ───────────────────────────────────────────
st.set_page_config(
    page_title="KR Stock Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",  # 모바일: 사이드바 기본 접힘
)

# ── 모바일 최적화 CSS ─────────────────────────────────────
# Streamlit의 st.columns는 모바일(640px 이하)에서 자동으로 세로 스택됨.
# 추가 CSS로 여백/폰트 최적화.
st.markdown("""
<style>
    /* 모바일 여백 축소 */
    .block-container {
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 1200px;
    }

    /* 모바일에서 메트릭 카드 가독성 */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea11, #764ba211);
        border-radius: 12px;
        padding: 12px 16px;
        border: 1px solid #e2e8f0;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        flex-wrap: wrap;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        font-size: 0.9rem;
    }

    /* 모바일에서 expander 터치 영역 확대 */
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.4rem;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 10px 12px;
            font-size: 0.85rem;
        }
    }
</style>
""", unsafe_allow_html=True)


# ── 헤더 ──────────────────────────────────────────────────
st.title("📊 KR Stock Analyzer")
st.caption("AI 멀티에이전트 한국 상장기업 분석 시스템")

# ── 입력 폼 ───────────────────────────────────────────────
# 모바일에서는 columns가 세로 스택되므로 자연스럽게 대응됨
with st.form("analysis_form"):
    col1, col2 = st.columns([2, 1])

    with col1:
        company_name = st.text_input(
            "기업명",
            placeholder="예: 삼성전자",
            help="분석할 한국 상장기업명을 입력하세요",
        )
        stock_code = st.text_input(
            "종목코드 (선택)",
            placeholder="예: 005930",
            help="6자리 종목코드",
        )

    with col2:
        market = st.selectbox("시장", ["KOSPI", "KOSDAQ"])
        depth = st.selectbox(
            "분석 깊이",
            ["standard", "quick", "deep"],
            help="quick: 빠른 요약 / standard: 기본 분석 / deep: 심층 분석",
        )
        industry = st.text_input("업종 (선택)", placeholder="예: 반도체")

    corp_code = st.text_input("DART 기업코드 (선택)", placeholder="예: 00126380")
    submitted = st.form_submit_button("🔍 분석 시작", use_container_width=True)


# ── 분석 실행 ─────────────────────────────────────────────
if submitted:
    if not company_name.strip():
        st.error("기업명을 입력해주세요.")
        st.stop()

    company = CompanyInfo(
        name=company_name.strip(),
        stock_code=stock_code.strip(),
        corp_code=corp_code.strip(),
        market=market,
        industry=industry.strip(),
    )
    request = AnalysisRequest(company=company, depth=depth)

    # 진행 상태 표시
    progress = st.progress(0, text="분석 준비 중...")
    status_area = st.empty()

    try:
        start = time.time()

        # asyncio 이벤트 루프에서 파이프라인 실행
        # Streamlit은 sync 환경이므로 asyncio.run 사용
        with st.spinner("에이전트 분석 중... (1~3분 소요)"):
            progress.progress(10, text="실무 분석 에이전트 실행 중...")
            result = asyncio.run(run_pipeline(request))
            progress.progress(100, text="분석 완료!")

        elapsed = time.time() - start
        status_area.success(f"분석 완료! ({elapsed:.0f}초 소요)")

        # 결과를 session_state에 저장 (페이지 새로고침 방지)
        st.session_state["result"] = result
        st.session_state["company"] = company

    except Exception as e:
        progress.empty()
        st.error(f"분석 중 오류가 발생했습니다: {e}")
        logging.exception("분석 실패")
        st.stop()

# ── 결과 표시 ─────────────────────────────────────────────
if "result" in st.session_state:
    result: SynthesisResult = st.session_state["result"]
    company: CompanyInfo = st.session_state["company"]

    st.divider()

    # ─ 종합 결과 카드 ─
    st.subheader(f"{company.name} 분석 결과")

    # 스코어 + 컨센서스 (모바일에서 세로 스택)
    m1, m2, m3 = st.columns(3)
    with m1:
        score = result.overall_score
        delta_label = "긍정적" if score >= 6 else ("중립" if score >= 4 else "부정적")
        st.metric("종합 점수", f"{score:.1f} / 10", delta=delta_label)
    with m2:
        st.metric("투자 의견", result.consensus.value)
    with m3:
        agent_count = len(result.analyst_results) + len(result.philosophy_results)
        st.metric("참여 에이전트", f"{agent_count}개")

    # Executive Summary
    st.info(result.executive_summary)

    # ─ 핵심 투자 포인트 ─
    if result.key_points:
        st.subheader("핵심 투자 포인트")
        for i, point in enumerate(result.key_points, 1):
            st.markdown(f"**{i}.** {point}")

    # ─ 탭 기반 상세 결과 ─
    st.divider()

    tab_analysts, tab_philosophy, tab_risks, tab_consensus, tab_raw = st.tabs([
        "📈 실무 분석",
        "🧠 투자 철학",
        "⚠️ 리스크",
        "🤝 의견 비교",
        "📄 전문 리포트",
    ])

    # ─ 실무 분석 탭 ─
    with tab_analysts:
        _render_agent_results(result.analyst_results)

    # ─ 투자 철학 탭 ─
    with tab_philosophy:
        _render_agent_results(result.philosophy_results)

    # ─ 리스크 탭 ─
    with tab_risks:
        _render_risks(result)

    # ─ 의견 비교 탭 ─
    with tab_consensus:
        _render_consensus(result)

    # ─ 전문 리포트 탭 ─
    with tab_raw:
        _render_full_report(result)


# ── 렌더링 헬퍼 함수들 ────────────────────────────────────

def _render_agent_results(results: list[AgentResult]):
    """에이전트 결과를 카드 형태로 렌더링합니다."""
    agent_labels = {
        "financial": ("💰", "재무분석"),
        "industry": ("🏭", "산업분석"),
        "risk": ("⚠️", "리스크분석"),
        "technical": ("📉", "기술분석"),
        "economist": ("🌍", "이코노미스트"),
        "buffett": ("🎩", "버핏/그레이엄"),
        "lynch": ("📊", "피터 린치"),
        "dalio": ("🌊", "레이 달리오"),
    }

    for r in results:
        icon, label = agent_labels.get(r.agent, ("🤖", r.agent))
        score_color = "🟢" if r.score >= 7 else ("🟡" if r.score >= 4 else "🔴")

        with st.expander(f"{icon} {label}  —  {score_color} {r.score}/10 ({r.conviction.value})", expanded=False):
            st.markdown(r.summary)

            if r.evidence:
                st.markdown("**근거:**")
                for ev in r.evidence:
                    source = f" _({ev.source})_" if ev.source else ""
                    st.markdown(f"- **{ev.claim}**: {ev.data}{source}")

            if r.risks:
                st.markdown("**식별 리스크:**")
                for risk in r.risks[:3]:
                    severity_bar = "🔴" * risk.severity + "⚪" * (5 - risk.severity)
                    st.markdown(f"- {risk.title} {severity_bar}: {risk.description}")


def _render_risks(result: SynthesisResult):
    """전체 리스크를 종합하여 표시합니다."""
    all_risks = []
    for ar in result.analyst_results + result.philosophy_results:
        for risk in ar.risks:
            all_risks.append({
                "리스크": risk.title,
                "심각도": risk.severity,
                "확률": risk.probability,
                "위험점수": risk.severity * risk.probability,
                "설명": risk.description,
                "출처": ar.agent,
            })

    if not all_risks:
        st.info("식별된 리스크가 없습니다.")
        return

    # 위험점수 내림차순 정렬
    all_risks.sort(key=lambda x: x["위험점수"], reverse=True)

    # 상위 리스크 하이라이트
    st.markdown("### 🔴 주요 리스크 TOP 5")
    for i, risk in enumerate(all_risks[:5], 1):
        score = risk["위험점수"]
        color = "🔴" if score >= 15 else ("🟠" if score >= 10 else "🟡")
        st.markdown(f"{color} **{i}. {risk['리스크']}** (위험점수: {score}/25)")
        st.caption(f"{risk['설명']} — _{risk['출처']}_")

    # 전체 리스크 테이블
    if len(all_risks) > 5:
        with st.expander(f"전체 리스크 목록 ({len(all_risks)}건)"):
            import pandas as pd
            df = pd.DataFrame(all_risks)
            st.dataframe(df, use_container_width=True, hide_index=True)


def _render_consensus(result: SynthesisResult):
    """에이전트 간 의견 비교를 표시합니다."""
    # 점수 비교 차트
    st.markdown("### 에이전트별 점수 비교")

    all_results = result.analyst_results + result.philosophy_results
    if all_results:
        import plotly.graph_objects as go

        agent_labels = {
            "financial": "재무", "industry": "산업", "risk": "리스크",
            "technical": "기술", "economist": "매크로",
            "buffett": "버핏", "lynch": "린치", "dalio": "달리오",
        }

        names = [agent_labels.get(r.agent, r.agent) for r in all_results]
        scores = [r.score for r in all_results]
        colors = ["#4CAF50" if s >= 7 else ("#FFC107" if s >= 4 else "#F44336") for s in scores]

        fig = go.Figure(go.Bar(
            x=names,
            y=scores,
            marker_color=colors,
            text=[f"{s:.1f}" for s in scores],
            textposition="outside",
        ))
        fig.update_layout(
            yaxis_range=[0, 11],
            yaxis_title="점수",
            height=350,
            margin=dict(l=40, r=20, t=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.add_hline(y=result.overall_score, line_dash="dash",
                      line_color="blue", annotation_text=f"종합 {result.overall_score:.1f}")
        st.plotly_chart(fig, use_container_width=True)

    # 의견 일치/충돌
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### ✅ 의견 일치")
        if result.agreements:
            for item in result.agreements:
                st.markdown(f"- {item}")
        else:
            st.caption("분석된 의견 일치 사항이 없습니다.")

    with col_b:
        st.markdown("### ⚡ 의견 충돌")
        if result.conflicts:
            for item in result.conflicts:
                st.markdown(f"- {item}")
        else:
            st.caption("분석된 의견 충돌이 없습니다.")


def _render_full_report(result: SynthesisResult):
    """전문 Markdown 리포트를 표시하고 다운로드 제공합니다."""
    from output.report_builder import build_markdown_report

    report_md = build_markdown_report(result)
    st.markdown(report_md)

    # 다운로드 버튼
    st.download_button(
        label="📥 Markdown 리포트 다운로드",
        data=report_md,
        file_name=f"{result.company.name}_분석리포트.md",
        mime="text/markdown",
        use_container_width=True,
    )
