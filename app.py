"""KR Stock Analyzer — Streamlit 프론트엔드.

실행: streamlit run app.py
"""

import asyncio
import logging
import time

import nest_asyncio
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

nest_asyncio.apply()

from core.display import (
    progress_fraction,
    quick_stats,
    resolve_market,
    score_accent,
    snowflake_scores,
    validate_analysis_inputs,
)
from core.models import AgentResult, AnalysisRequest, CompanyInfo, SynthesisResult
from core.orchestrator import run_pipeline
from core.ux import format_usage_caption, format_user_error, upsert_history
from data.dart_client import DartClient
from data.formatter import format_dart_data, format_news_data

logger = logging.getLogger(__name__)

_TIME_HINTS = {"quick": "약 30초", "standard": "약 1~2분", "deep": "약 2~3분"}
_QUICK_STOCKS = [
    ("삼성전자", "005930"),
    ("SK하이닉스", "000660"),
    ("카카오", "035720"),
    ("네이버", "035420"),
]


def _candidate_label(row: dict) -> str:
    stock = row.get("stock_code") or "비상장"
    return f"{row.get('corp_name', '')} ({stock}) · {row.get('corp_code', '')}"


def _company_from_pending(pending: dict, match: dict | None = None) -> CompanyInfo:
    name = pending["name"]
    stock = pending["stock_code"]
    corp = pending["corp_code"]
    if match:
        name = match.get("corp_name") or name
        stock = stock or match.get("stock_code", "")
        corp = match.get("corp_code", "")
    return CompanyInfo(
        name=name,
        stock_code=stock,
        corp_code=corp,
        market=resolve_market(pending.get("market", "자동감지"), match),
        industry=pending["industry"],
    )


async def _resolve_company_safe(pending: dict) -> list[dict]:
    async with DartClient() as dart:
        return await dart.resolve_company(
            name=pending["name"],
            stock_code=pending["stock_code"],
            corp_code=pending["corp_code"],
        )


def _run_analysis(company: CompanyInfo, depth: str) -> None:
    """파이프라인을 실행하고 결과를 session_state에 저장합니다."""
    request = AnalysisRequest(company=company, depth=depth)
    try:
        start = time.time()
        st.info(f"⏱️ 예상 소요 시간: {_TIME_HINTS.get(depth, '약 1분')}")
        progress_bar = st.progress(0, text="준비 중...")

        with st.status("분석 중...", expanded=True) as status:
            def on_progress(message: str) -> None:
                st.write(message)
                pct = progress_fraction(message)
                if pct is not None:
                    progress_bar.progress(pct, text=message)

            result = asyncio.run(run_pipeline(request, on_progress=on_progress))
            progress_bar.progress(1.0, text="✅ 분석 완료!")
            status.update(label="✅ 분석 완료!", state="complete")

        elapsed = time.time() - start
        st.success(f"분석 완료! ({elapsed:.0f}초 소요)")
        st.session_state["result"] = result
        st.session_state["company"] = result.company
        st.session_state.setdefault("history", {})
        upsert_history(st.session_state["history"], result.company, result)
        st.session_state.pop("pending_form", None)
        st.session_state.pop("corp_candidates", None)
    except Exception as e:
        st.session_state.pop("pending_form", None)
        st.session_state.pop("corp_candidates", None)
        st.error(format_user_error(e))
        logging.exception("분석 실패")
        st.stop()


# ── 페이지 설정 ───────────────────────────────────────────
st.set_page_config(
    page_title="KR Stock Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    :root {
        --ksa-text: #1a1a1a;
        --ksa-muted: #888;
        --ksa-track: #e0e0e0;
        --ksa-stat-a: #f8f9fa;
        --ksa-stat-b: #ffffff;
        --ksa-stat-border: #eee;
        --ksa-metric-border: #e2e8f0;
    }
    .block-container {
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 1200px;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea11, #764ba211);
        border-radius: 12px;
        padding: 12px 16px;
        border: 1px solid var(--ksa-metric-border);
    }
    [data-testid="stMetricValue"] { font-size: 1.8rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 0; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; font-size: 0.9rem; }

    .ksa-stat-row {
        display: flex; justify-content: space-between;
        padding: 6px 12px;
        border-bottom: 1px solid var(--ksa-stat-border);
        font-size: 0.9rem;
        color: var(--ksa-text);
    }
    .ksa-stat-row span:first-child { color: var(--ksa-muted); }
    .ksa-stat-row span:last-child { font-weight: 600; }
    .ksa-bar-track {
        flex: 1; background: var(--ksa-track); border-radius: 4px;
        height: 12px; margin: 0 8px;
    }
    .ksa-bar-fill { height: 100%; border-radius: 4px; }

    @media (prefers-color-scheme: dark) {
        :root {
            --ksa-text: #e8e8e8;
            --ksa-muted: #aaa;
            --ksa-track: #3a3a3a;
            --ksa-stat-a: #1e1e1e;
            --ksa-stat-b: #161616;
            --ksa-stat-border: #333;
            --ksa-metric-border: #333;
        }
        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #667eea22, #764ba222);
            border: 1px solid #333;
        }
    }
    [data-theme="dark"] [data-testid="stMetric"],
    .stApp[data-theme="dark"] [data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea22, #764ba222);
        border: 1px solid #333;
    }
    @media (max-width: 640px) {
        .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
        [data-testid="stMetricValue"] { font-size: 1.4rem; }
        .stTabs [data-baseweb="tab"] { padding: 10px 12px; font-size: 0.85rem; }
    }
</style>
""", unsafe_allow_html=True)


# ── 헤더 ──────────────────────────────────────────────────
st.title("📊 KR Stock Analyzer")
st.caption("기업명만 입력하면 분석을 시작합니다")

# ── 사이드바 ──────────────────────────────────────────────
st.session_state.setdefault("history", {})
history = st.session_state["history"]
with st.sidebar:
    st.header("📋 분석 히스토리")
    if not history:
        st.caption("아직 분석 내역이 없습니다.")
        st.markdown("---")
        st.markdown("**💡 추천 분석 기업**")
        recommend_cols = st.columns(2)
        for i, (name, code) in enumerate(_QUICK_STOCKS):
            with recommend_cols[i % 2]:
                if st.button(name, key=f"quick_{code}", use_container_width=True):
                    st.session_state["pending_form"] = {
                        "name": name,
                        "stock_code": code,
                        "corp_code": "",
                        "market": "KOSPI",
                        "industry": "",
                        "depth": "quick",
                    }
                    st.session_state.pop("result", None)
                    st.session_state.pop("corp_candidates", None)
                    st.rerun()
    else:
        st.caption("보기 버튼으로 재분석 없이 이전 결과를 엽니다.")
        for name in reversed(list(history.keys())):
            entry = history[name]
            score = entry["result"].overall_score
            consensus = entry["result"].consensus.value
            score_color = "🟢" if score >= 7 else "🟡" if score >= 4 else "🔴"
            col_info, col_btn = st.columns([3, 1])
            with col_info:
                st.markdown(f"**{name}** {score_color} {score:.1f}")
                st.caption(consensus)
            with col_btn:
                if st.button("보기", key=f"hist_{name}"):
                    st.session_state["result"] = entry["result"]
                    st.session_state["company"] = entry["company"]
                    st.session_state.pop("pending_form", None)
                    st.session_state.pop("corp_candidates", None)
                    st.rerun()


# ── 입력 폼 ───────────────────────────────────────────────
# 체크박스는 form 밖에 두어야 고급 필드가 즉시 나타납니다.
show_advanced = st.checkbox("⚙️ 고급 옵션 열기", value=False)

with st.form("analysis_form"):
    company_name = st.text_input(
        "🔍 기업명을 입력하세요",
        placeholder="예: 삼성전자, 카카오, 셀트리온",
        help="기업명만 입력하면 나머지는 자동으로 찾아줍니다",
    )
    col_depth, col_submit = st.columns([1, 1])
    with col_depth:
        depth = st.select_slider(
            "분석 깊이",
            options=["quick", "standard", "deep"],
            value="standard",
            help="⚡ quick: ~30초 / 📊 standard: ~1분 / 🔬 deep: ~2분",
        )
    with col_submit:
        st.write("")
        submitted = st.form_submit_button("🔍 분석 시작", use_container_width=True)

    if show_advanced:
        adv1, adv2 = st.columns(2)
        with adv1:
            stock_code = st.text_input("종목코드", placeholder="005930")
            market = st.selectbox("시장", ["자동감지", "KOSPI", "KOSDAQ"])
        with adv2:
            industry = st.text_input("업종", placeholder="반도체")
            corp_code = st.text_input("DART 기업코드", placeholder="00126380")
    else:
        stock_code = ""
        market = "자동감지"
        industry = ""
        corp_code = ""


# ── 분석 실행 ─────────────────────────────────────────────
if submitted:
    error = validate_analysis_inputs(company_name, stock_code, corp_code)
    if error:
        st.error(error)
        st.stop()
    st.session_state.pop("result", None)
    st.session_state.pop("corp_candidates", None)
    st.session_state["pending_form"] = {
        "name": company_name.strip(),
        "stock_code": stock_code.strip(),
        "corp_code": corp_code.strip(),
        "market": market,
        "industry": industry.strip(),
        "depth": depth,
    }

pending = st.session_state.get("pending_form")
if pending and "result" not in st.session_state:
    if "corp_candidates" in st.session_state:
        candidates = st.session_state["corp_candidates"]
        st.info(f"{len(candidates)}개 기업이 검색되었습니다. 분석할 기업을 선택하세요.")
        labels = [_candidate_label(row) for row in candidates]
        selected = st.selectbox(
            "기업 선택",
            options=list(range(len(candidates))),
            format_func=lambda i: labels[i],
        )
        if st.button("선택한 기업으로 분석", use_container_width=True):
            company = _company_from_pending(pending, candidates[selected])
            _run_analysis(company, pending["depth"])
    else:
        with st.spinner("DART 기업코드 조회 중..."):
            try:
                matches = asyncio.run(_resolve_company_safe(pending))
            except Exception as e:
                logger.warning("DART 조회 실패: %s", e)
                matches = []
                st.warning(
                    "DART 기업코드 조회에 실패했습니다. "
                    "일반 지식 기반으로 분석을 진행합니다."
                )
        if pending["corp_code"]:
            company = _company_from_pending(pending)
            _run_analysis(company, pending["depth"])
        elif len(matches) == 0:
            st.warning(
                "DART에서 기업코드를 찾지 못했습니다. "
                "일반 지식 기반으로 분석을 진행합니다."
            )
            _run_analysis(_company_from_pending(pending), pending["depth"])
        elif len(matches) == 1:
            match = matches[0]
            st.caption(
                f"DART 기업코드 {match['corp_code']} "
                f"({match.get('corp_name') or pending['name']}) 자동 조회"
            )
            _run_analysis(_company_from_pending(pending, match), pending["depth"])
        else:
            st.session_state["corp_candidates"] = matches
            st.rerun()


# ── 렌더링 헬퍼 함수들 ────────────────────────────────────

def _render_snowflake(result: SynthesisResult) -> None:
    scores = snowflake_scores(result)
    if not scores:
        st.caption("레이더 차트를 그릴 에이전트 결과가 없습니다.")
        return
    labels = list(scores.keys())
    values = list(scores.values())
    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor="rgba(99, 110, 250, 0.2)",
        line=dict(color="#636EFA", width=2),
        marker=dict(size=8),
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10])),
        showlegend=False,
        height=350,
        margin=dict(l=60, r=60, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_score_card(result: SynthesisResult) -> None:
    score = result.overall_score
    color = score_accent(score)
    st.markdown(
        f"""
        <div style="text-align: center; padding: 12px 8px 8px;">
            <div style="
                width: 120px; height: 120px; border-radius: 50%;
                border: 6px solid {color};
                display: inline-flex; align-items: center; justify-content: center;
                font-size: 2.2rem; font-weight: bold; color: {color};
            ">{score:.1f}</div>
            <div style="margin-top: 8px; font-size: 1.1rem; font-weight: 600;">{result.consensus.value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    agent_labels = {
        "financial": "재무", "industry": "산업", "risk": "리스크",
        "technical": "기술", "economist": "매크로",
        "buffett": "가치투자", "lynch": "성장투자", "dalio": "글로벌매크로",
    }
    for item in result.analyst_results + result.philosophy_results:
        label = agent_labels.get(item.agent, item.agent)
        pct = max(0.0, min(item.score / 10, 1.0)) * 100
        bar = score_accent(item.score)
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; margin: 4px 0; font-size: 0.85rem;">
                <span style="width: 80px; flex-shrink: 0;">{label}</span>
                <div class="ksa-bar-track">
                    <div class="ksa-bar-fill" style="width: {pct}%; background: {bar};"></div>
                </div>
                <span style="width: 30px; text-align: right; font-weight: 600;">{item.score:.1f}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_quick_stats(result: SynthesisResult) -> None:
    stats = quick_stats(result)
    cols = st.columns(2)
    for i, (key, value) in enumerate(stats.items()):
        bg = "var(--ksa-stat-a)" if i % 2 == 0 else "var(--ksa-stat-b)"
        with cols[i % 2]:
            st.markdown(
                f"""
                <div class="ksa-stat-row" style="background: {bg};">
                    <span>{key}</span>
                    <span>{value}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_agent_card(item: AgentResult) -> None:
    agent_labels = {
        "financial": ("💰", "재무분석", "#1e88e5"),
        "industry": ("🏭", "산업분석", "#43a047"),
        "risk": ("⚠️", "리스크분석", "#e53935"),
        "technical": ("📉", "기술분석", "#8e24aa"),
        "economist": ("🌍", "이코노미스트", "#f4511e"),
        "buffett": ("🎩", "버핏/그레이엄", "#3949ab"),
        "lynch": ("📊", "피터 린치", "#00897b"),
        "dalio": ("🌊", "레이 달리오", "#5e35b1"),
    }
    icon, label, color = agent_labels.get(item.agent, ("🤖", item.agent, "#757575"))
    badge = score_accent(item.score)
    st.markdown(
        f"""
        <div style="
            border-left: 4px solid {color};
            padding: 12px 16px; margin: 8px 0;
            background: linear-gradient(135deg, {color}14, {color}08);
            border-radius: 0 8px 8px 0;
        ">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 1.1rem; font-weight: 600;">{icon} {label}</span>
                <span style="
                    background: {badge}; color: white;
                    padding: 4px 12px; border-radius: 12px;
                    font-weight: 700; font-size: 0.9rem;
                ">{item.score:.1f}/10</span>
            </div>
            <div style="margin-top: 4px; font-size: 0.8rem; color: var(--ksa-muted);">
                확신도: {item.conviction.value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("상세 보기", expanded=False):
        st.markdown(item.summary)
        if item.evidence:
            st.markdown("**근거:**")
            for ev in item.evidence:
                source = f" _({ev.source})_" if ev.source else ""
                st.markdown(f"- **{ev.claim}**: {ev.data}{source}")
        if item.risks:
            st.markdown("**주요 리스크:**")
            for risk in item.risks[:3]:
                severity_bar = "🔴" * risk.severity + "⚪" * (5 - risk.severity)
                st.markdown(f"- {risk.title} {severity_bar}: {risk.description}")


def _render_agent_results(results: list[AgentResult]) -> None:
    if not results:
        st.caption("표시할 에이전트 결과가 없습니다.")
        return
    for item in results:
        _render_agent_card(item)


def _render_risks(result: SynthesisResult) -> None:
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
    all_risks.sort(key=lambda x: x["위험점수"], reverse=True)
    st.markdown("### 🔴 주요 리스크 TOP 5")
    for i, risk in enumerate(all_risks[:5], 1):
        score = risk["위험점수"]
        color = "🔴" if score >= 15 else ("🟠" if score >= 10 else "🟡")
        st.markdown(f"{color} **{i}. {risk['리스크']}** (위험점수: {score}/25)")
        st.caption(f"{risk['설명']} — _{risk['출처']}_")
    if len(all_risks) > 5:
        with st.expander(f"전체 리스크 목록 ({len(all_risks)}건)"):
            st.dataframe(pd.DataFrame(all_risks), use_container_width=True, hide_index=True)


def _render_consensus(result: SynthesisResult) -> None:
    st.markdown("### 에이전트별 점수 비교")
    all_results = result.analyst_results + result.philosophy_results
    if all_results:
        agent_labels = {
            "financial": "재무", "industry": "산업", "risk": "리스크",
            "technical": "기술", "economist": "매크로",
            "buffett": "버핏", "lynch": "린치", "dalio": "달리오",
        }
        names = [agent_labels.get(r.agent, r.agent) for r in all_results]
        scores = [r.score for r in all_results]
        colors = [score_accent(s) for s in scores]
        fig = go.Figure(go.Bar(
            x=names, y=scores, marker_color=colors,
            text=[f"{s:.1f}" for s in scores], textposition="outside",
        ))
        fig.update_layout(
            yaxis_range=[0, 11], yaxis_title="점수", height=350,
            margin=dict(l=40, r=20, t=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        fig.add_hline(
            y=result.overall_score, line_dash="dash", line_color="blue",
            annotation_text=f"종합 {result.overall_score:.1f}",
        )
        st.plotly_chart(fig, use_container_width=True)

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


def _render_collected_data(result: SynthesisResult) -> None:
    collected = result.collected_data or {}
    dart = collected.get("dart") or {}
    news = collected.get("news") or {}
    if not dart and not news:
        st.info("수집된 외부 데이터가 없습니다. DART/네이버 키를 설정하면 재무·뉴스가 표시됩니다.")
        return
    if dart:
        st.subheader("DART 공시 데이터")
        st.markdown(format_dart_data(dart))
    if news:
        st.subheader("최근 뉴스")
        st.markdown(format_news_data(news))


def _render_full_report(result: SynthesisResult) -> None:
    from output.report_builder import build_markdown_report, markdown_to_html

    report_md = build_markdown_report(result)
    st.markdown(report_md)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="📥 Markdown 다운로드",
            data=report_md,
            file_name=f"{result.company.name}_분석리포트.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with dl2:
        report_html = markdown_to_html(report_md, result.company.name)
        st.download_button(
            label="📥 HTML 다운로드",
            data=report_html,
            file_name=f"{result.company.name}_분석리포트.html",
            mime="text/html",
            use_container_width=True,
        )


def _render_overview(result: SynthesisResult) -> None:
    left, right = st.columns([1.15, 0.85])
    with left:
        st.markdown("##### 건강도 레이더")
        _render_snowflake(result)
    with right:
        st.markdown("##### 스마트 스코어")
        _render_score_card(result)
    st.info(result.executive_summary)
    if result.key_points:
        st.subheader("핵심 투자 포인트")
        for i, point in enumerate(result.key_points, 1):
            st.markdown(f"**{i}.** {point}")
    st.subheader("핵심 지표")
    _render_quick_stats(result)


# ── 결과 표시 ─────────────────────────────────────────────
if "result" in st.session_state:
    result: SynthesisResult = st.session_state["result"]
    company: CompanyInfo = st.session_state["company"]

    st.divider()
    st.subheader(f"{company.name} 분석 결과")
    usage = getattr(result, "usage", None)
    if usage and (usage.input_tokens or usage.output_tokens):
        st.caption(format_usage_caption(usage))

    tab_overview, tab_analysts, tab_risks, tab_consensus, tab_data, tab_report = st.tabs([
        "🎯 종합 진단",
        "📈 에이전트 분석",
        "⚠️ 리스크",
        "🤝 의견 비교",
        "📊 데이터",
        "📄 리포트",
    ])
    with tab_overview:
        _render_overview(result)
    with tab_analysts:
        view = st.radio("보기", ["실무 분석", "투자 철학"], horizontal=True)
        if view == "실무 분석":
            _render_agent_results(result.analyst_results)
        else:
            _render_agent_results(result.philosophy_results)
    with tab_risks:
        _render_risks(result)
    with tab_consensus:
        _render_consensus(result)
    with tab_data:
        _render_collected_data(result)
    with tab_report:
        _render_full_report(result)
