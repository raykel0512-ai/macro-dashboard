# v2.0
# 매크로 대시보드 - FRED + AI 해설
# Made by Raykel

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fredapi import Fred
from openai import OpenAI
from datetime import datetime, timedelta

# ============================================
# 페이지 설정
# ============================================
st.set_page_config(
    page_title="매크로 대시보드 v2.0",
    page_icon="📊",
    layout="wide"
)

# ============================================
# API 연결
# ============================================
@st.cache_resource
def get_fred():
    return Fred(api_key=st.secrets["FRED_API_KEY"])

fred = get_fred()

# ============================================
# 공통 데이터 로딩
# ============================================
@st.cache_data(ttl=3600)
def load_series(series_id, start_date=None, years=10):
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    try:
        return fred.get_series(series_id, observation_start=start_date).dropna()
    except Exception as e:
        st.error(f"데이터 로딩 실패 ({series_id}): {e}")
        return pd.Series(dtype=float)

@st.cache_data(ttl=3600)
def get_latest_value(series_id):
    """최신값과 그 직전값 반환"""
    try:
        data = fred.get_series(series_id).dropna()
        if len(data) < 2:
            return None, None, None
        return data.iloc[-1], data.iloc[-2], data.index[-1]
    except:
        return None, None, None

# ============================================
# AI 해설 함수
# ============================================
@st.cache_resource
def get_openai():
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

@st.cache_data(ttl=3600)
def ai_commentary(context_data, focus):
    """
    context_data: dict 형태의 지표값들
    focus: 어떤 관점에서 해설할지
    """
    try:
        client = get_openai()
        system_msg = "너는 거시경제 분석가야. 한국어로 간결하게 해설해줘."
        user_msg = f"""[데이터]
{context_data}

[해설 관점]
{focus}

규칙:
- 5문장 이내로 핵심만
- 숫자의 의미와 시장 함의 위주
- 단정적 예측 금지, 가능성 위주로
- 마지막에 "투자자가 주목할 점:" 한 줄 추가"""
        
        response = client.chat.completions.create(
            model="gpt-5-mini",
            max_completion_tokens=400,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 해설 생성 실패: {e}"

[데이터]
{context_data}

[해설 관점]
{focus}

규칙:
- 5문장 이내로 핵심만
- 숫자의 의미와 시장 함의 위주
- 단정적 예측 금지, 가능성 위주로
- 마지막에 "투자자가 주목할 점:" 한 줄 추가
"""
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        return f"AI 해설 생성 실패: {e}"

# ============================================
# 헤더
# ============================================
st.title("📊 매크로 대시보드 v2.0")
st.caption(f"FRED 기반 거시경제 모니터링 + AI 해설 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================
# 탭 구성
# ============================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏠 Overview",
    "🚨 Recession Watch",
    "🏦 Fed Watch",
    "🇰🇷 Korea",
    "💰 Assets",
    "🔍 Explorer"
])

# ============================================
# 🏠 TAB 1: Overview
# ============================================
with tab1:
    st.header("핵심 지표 한눈에")
    
    overview_indicators = {
        "실업률 (%)": "UNRATE",
        "CPI YoY (%)": "CPIAUCSL",
        "연방기금금리 (%)": "DFF",
        "10년물 국채 (%)": "DGS10",
        "장단기 스프레드": "T10Y2Y",
        "VIX": "VIXCLS",
        "원/달러": "DEXKOUS",
        "WTI 유가 ($)": "DCOILWTICO",
    }
    
    cols = st.columns(4)
    overview_summary = {}
    
    for i, (label, sid) in enumerate(overview_indicators.items()):
        latest, prev, date = get_latest_value(sid)
        if latest is None:
            continue
        
        if "YoY" in label:
            # CPI는 전년대비로 변환
            data = load_series(sid, years=2)
            yoy = data.pct_change(periods=12).dropna() * 100
            if len(yoy) > 0:
                latest = yoy.iloc[-1]
                prev = yoy.iloc[-2] if len(yoy) > 1 else latest
        
        delta = latest - prev if prev is not None else 0
        overview_summary[label] = round(latest, 2)
        
        with cols[i % 4]:
            st.metric(label, f"{latest:,.2f}", f"{delta:+,.2f}")
    
    st.divider()
    
    if st.button("🤖 Overview AI 해설 보기", key="overview_ai"):
        with st.spinner("Claude Haiku가 분석 중..."):
            commentary = ai_commentary(
                overview_summary,
                "미국 거시경제 현황을 종합적으로 진단해줘. 인플레이션, 고용, 금리, 시장 변동성을 묶어서."
            )
            st.info(commentary)

# ============================================
# 🚨 TAB 2: Recession Watch
# ============================================
with tab2:
    st.header("경기 침체 신호 모니터링")
    
    signals = {}
    score = 0
    
    # 1. 장단기 스프레드
    spread, _, _ = get_latest_value("T10Y2Y")
    if spread is not None:
        is_warning = spread < 0
        signals["장단기 스프레드 (10Y-2Y)"] = {
            "value": f"{spread:.2f}%",
            "warning": is_warning,
            "desc": "음수 = 역전 (12-18개월 후 침체 가능성)"
        }
        if is_warning:
            score += 1
    
    # 2. 10Y-3M 스프레드
    spread3m, _, _ = get_latest_value("T10Y3M")
    if spread3m is not None:
        is_warning = spread3m < 0
        signals["장단기 스프레드 (10Y-3M)"] = {
            "value": f"{spread3m:.2f}%",
            "warning": is_warning,
            "desc": "연준이 더 신뢰하는 신호"
        }
        if is_warning:
            score += 1
    
    # 3. Sahm Rule
    sahm, _, _ = get_latest_value("SAHMREALTIME")
    if sahm is not None:
        is_warning = sahm >= 0.5
        signals["Sahm Rule"] = {
            "value": f"{sahm:.2f}",
            "warning": is_warning,
            "desc": "0.5 초과 = 침체 진입 신호"
        }
        if is_warning:
            score += 1
    
    # 4. 신규 실업수당 청구 (4주 이평)
    claims = load_series("ICSA", years=2)
    if len(claims) > 4:
        ma4 = claims.rolling(4).mean().iloc[-1]
        ma4_3m_ago = claims.rolling(4).mean().iloc[-13] if len(claims) > 13 else ma4
        change_pct = (ma4 - ma4_3m_ago) / ma4_3m_ago * 100
        is_warning = change_pct > 20
        signals["신규 실업수당 (4주이평, 3개월 변화)"] = {
            "value": f"{change_pct:+.1f}%",
            "warning": is_warning,
            "desc": "+20% 이상 = 노동시장 악화"
        }
        if is_warning:
            score += 1
    
    # 5. 하이일드 스프레드
    hy, _, _ = get_latest_value("BAMLH0A0HYM2")
    if hy is not None:
        is_warning = hy > 6.0
        signals["하이일드 신용 스프레드"] = {
            "value": f"{hy:.2f}%",
            "warning": is_warning,
            "desc": "6% 초과 = 신용 위기 신호"
        }
        if is_warning:
            score += 1
    
    total = len(signals)
    
    # 점수판
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("⚠️ 점등된 신호", f"{score} / {total}")
        if score == 0:
            st.success("정상 국면")
        elif score <= 2:
            st.warning("주의 단계")
        else:
            st.error("경계 단계")
    
    with col2:
        for name, info in signals.items():
            icon = "🔴" if info["warning"] else "🟢"
            st.write(f"{icon} **{name}**: {info['value']} — _{info['desc']}_")
    
    st.divider()
    
    # 장단기 스프레드 차트
    spread_data = load_series("T10Y2Y", years=10)
    if len(spread_data) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=spread_data.index, y=spread_data.values,
            mode='lines', name='10Y-2Y',
            line=dict(color='#1f77b4', width=2)
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="역전선")
        fig.update_layout(title="장단기 스프레드 추이 (10년)", height=400, template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
    
    if st.button("🤖 침체 신호 AI 해설 보기", key="recession_ai"):
        ctx = {name: info["value"] for name, info in signals.items()}
        ctx["점등 신호 수"] = f"{score}/{total}"
        with st.spinner("Claude Haiku가 분석 중..."):
            commentary = ai_commentary(
                ctx,
                "경기 침체 신호들을 종합 진단해줘. 어떤 단계인지, 무엇을 더 주시해야 하는지."
            )
            st.info(commentary)

# ============================================
# 🏦 TAB 3: Fed Watch
# ============================================
with tab3:
    st.header("연준 정책 추적")
    
    fed_indicators = {
        "연방기금금리 (%)": "DFF",
        "연준 자산 (조달러)": "WALCL",
        "역레포 잔액": "RRPONTSYD",
        "5년 기대 인플레이션 (%)": "T5YIE",
        "10년 기대 인플레이션 (%)": "T10YIE",
        "근원 PCE YoY (%)": "PCEPILFE",
    }
    
    cols = st.columns(3)
    fed_summary = {}
    
    for i, (label, sid) in enumerate(fed_indicators.items()):
        latest, prev, _ = get_latest_value(sid)
        if latest is None:
            continue
        
        if "YoY" in label:
            data = load_series(sid, years=2)
            yoy = data.pct_change(periods=12).dropna() * 100
            if len(yoy) > 0:
                latest = yoy.iloc[-1]
                prev = yoy.iloc[-2]
        elif "조달러" in label:
            latest = latest / 1e6  # 단위 조정
            prev = prev / 1e6 if prev else prev
        
        delta = latest - prev if prev is not None else 0
        fed_summary[label] = round(latest, 2)
        
        with cols[i % 3]:
            st.metric(label, f"{latest:,.2f}", f"{delta:+,.2f}")
    
    st.divider()
    
    # 연준 자산 차트
    walcl = load_series("WALCL", years=10) / 1e6
    if len(walcl) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=walcl.index, y=walcl.values,
            mode='lines', name='Fed Assets',
            fill='tozeroy', line=dict(color='#2ca02c', width=2)
        ))
        fig.update_layout(title="연준 대차대조표 (조달러)", height=400, template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
    
    if st.button("🤖 연준 정책 AI 해설 보기", key="fed_ai"):
        with st.spinner("Claude Haiku가 분석 중..."):
            commentary = ai_commentary(
                fed_summary,
                "연준의 통화정책 스탠스를 진단해줘. 금리, 대차대조표, 인플레 기대를 묶어서 다음 행보 가능성도."
            )
            st.info(commentary)

# ============================================
# 🇰🇷 TAB 4: Korea
# ============================================
with tab4:
    st.header("한국 매크로")
    
    korea_indicators = {
        "원/달러 환율": "DEXKOUS",
        "한국 CPI YoY (%)": "KORCPIALLMINMEI",
        "한국 실업률 (%)": "LRHUTTTTKRM156S",
        "한국 산업생산": "KORPROINDMISMEI",
        "한국 기준금리 (%)": "INTDSRKRM193N",
    }
    
    cols = st.columns(3)
    korea_summary = {}
    
    for i, (label, sid) in enumerate(korea_indicators.items()):
        latest, prev, _ = get_latest_value(sid)
        if latest is None:
            continue
        
        if "YoY" in label:
            data = load_series(sid, years=3)
            yoy = data.pct_change(periods=12).dropna() * 100
            if len(yoy) > 0:
                latest = yoy.iloc[-1]
                prev = yoy.iloc[-2]
        
        delta = latest - prev if prev is not None else 0
        korea_summary[label] = round(latest, 2)
        
        with cols[i % 3]:
            st.metric(label, f"{latest:,.2f}", f"{delta:+,.2f}")
    
    st.divider()
    
    # 원/달러 차트
    krw = load_series("DEXKOUS", years=5)
    if len(krw) > 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=krw.index, y=krw.values,
            mode='lines', line=dict(color='#d62728', width=2)
        ))
        fig.update_layout(title="원/달러 환율 (5년)", height=400, template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
    
    if st.button("🤖 한국 매크로 AI 해설 보기", key="korea_ai"):
        with st.spinner("Claude Haiku가 분석 중..."):
            commentary = ai_commentary(
                korea_summary,
                "한국 경제 상황을 진단해줘. 환율, 물가, 고용, 금리를 묶어서 한국 투자자 관점에서."
            )
            st.info(commentary)

# ============================================
# 💰 TAB 5: Assets
# ============================================
with tab5:
    st.header("자산군 모니터링")
    
    asset_indicators = {
        "VIX": "VIXCLS",
        "금 ($)": "GOLDAMGBD228NLBM",
        "WTI 유가 ($)": "DCOILWTICO",
        "달러 인덱스": "DTWEXBGS",
        "10년물 국채 (%)": "DGS10",
        "하이일드 스프레드 (%)": "BAMLH0A0HYM2",
    }
    
    cols = st.columns(3)
    asset_summary = {}
    
    for i, (label, sid) in enumerate(asset_indicators.items()):
        latest, prev, _ = get_latest_value(sid)
        if latest is None:
            continue
        
        delta = latest - prev if prev is not None else 0
        asset_summary[label] = round(latest, 2)
        
        with cols[i % 3]:
            st.metric(label, f"{latest:,.2f}", f"{delta:+,.2f}")
    
    st.divider()
    
    # 자산별 1년 추이 (정규화)
    st.subheader("1년 상대 성과 (시작점 = 100)")
    
    fig = go.Figure()
    for label, sid in asset_indicators.items():
        data = load_series(sid, years=1)
        if len(data) > 0:
            normalized = data / data.iloc[0] * 100
            fig.add_trace(go.Scatter(
                x=normalized.index, y=normalized.values,
                mode='lines', name=label, line=dict(width=1.5)
            ))
    fig.add_hline(y=100, line_dash="dash", line_color="gray")
    fig.update_layout(height=450, template='plotly_white', hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)
    
    if st.button("🤖 자산군 AI 해설 보기", key="asset_ai"):
        with st.spinner("Claude Haiku가 분석 중..."):
            commentary = ai_commentary(
                asset_summary,
                "자산군 현황을 진단해줘. VIX, 금, 유가, 달러, 채권 금리, 신용 스프레드의 조합으로 본 시장 심리."
            )
            st.info(commentary)

# ============================================
# 🔍 TAB 6: Explorer (v1.0 기능)
# ============================================
with tab6:
    st.header("자유 탐색")
    st.caption("원하는 FRED Series ID를 직접 입력하거나 카탈로그에서 선택하세요.")
    
    EXPLORER_CATALOG = {
        "성장": {
            "GDPC1": "실질 GDP",
            "INDPRO": "산업생산지수",
        },
        "물가": {
            "CPIAUCSL": "CPI (전체)",
            "CPILFESL": "근원 CPI",
            "PCEPI": "PCE 물가지수",
        },
        "고용": {
            "UNRATE": "실업률",
            "PAYEMS": "비농업 고용",
            "ICSA": "신규 실업수당",
        },
        "금리": {
            "DFF": "연방기금금리",
            "DGS10": "10년물 국채",
            "DGS2": "2년물 국채",
            "T10Y2Y": "10Y-2Y 스프레드",
        },
        "직접 입력": {"custom": "직접 입력"},
    }
    
    col1, col2 = st.columns(2)
    with col1:
        category = st.selectbox("카테고리", list(EXPLORER_CATALOG.keys()))
    with col2:
        series_dict = EXPLORER_CATALOG[category]
        if category == "직접 입력":
            custom_id = st.text_input("FRED Series ID", value="GDPC1")
            series_id = custom_id
        else:
            series_id = st.selectbox("지표", list(series_dict.keys()),
                                     format_func=lambda x: f"{x} - {series_dict[x]}")
    
    period = st.radio("기간", ["1년", "3년", "5년", "10년", "전체"], horizontal=True, index=2)
    transform = st.selectbox("변환", ["원본", "전년동월대비 (%)", "전월대비 (%)", "12개월 이동평균"])
    
    period_map = {"1년": 1, "3년": 3, "5년": 5, "10년": 10, "전체": 50}
    data = load_series(series_id, years=period_map[period])
    
    if len(data) > 0:
        if transform == "전년동월대비 (%)":
            data = (data.pct_change(periods=12) * 100).dropna()
        elif transform == "전월대비 (%)":
            data = (data.pct_change() * 100).dropna()
        elif transform == "12개월 이동평균":
            data = data.rolling(12).mean().dropna()
        
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("최신값", f"{data.iloc[-1]:,.2f}")
        col_b.metric("기간 평균", f"{data.mean():,.2f}")
        col_c.metric("기간 최고", f"{data.max():,.2f}")
        col_d.metric("기간 최저", f"{data.min():,.2f}")
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=data.index, y=data.values, mode='lines',
                                 line=dict(color='#1f77b4', width=2)))
        if transform in ["전년동월대비 (%)", "전월대비 (%)"]:
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(title=f"{series_id} ({transform})", height=500, template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)

# ============================================
# 푸터
# ============================================
st.divider()
st.caption("Data: FRED (St. Louis Fed) | AI: GPT-5 mini | Made by Raykel")
