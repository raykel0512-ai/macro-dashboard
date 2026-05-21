# v3.0
# 매크로 대시보드 + 종목 분석
# Made by Raykel

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fredapi import Fred
from openai import OpenAI
from supabase import create_client
from datetime import datetime, timedelta
import yfinance as yf
import FinanceDataReader as fdr
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from ta.volatility import BollingerBands

# ============================================
# 페이지 설정
# ============================================
st.set_page_config(
    page_title="투자 대시보드 v3.0",
    page_icon="📊",
    layout="wide"
)

# ============================================
# API 연결
# ============================================
@st.cache_resource
def get_fred():
    return Fred(api_key=st.secrets["FRED_API_KEY"])

@st.cache_resource
def get_openai():
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

fred = get_fred()
sb = get_supabase()

# ============================================
# 공통 함수
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
    try:
        data = fred.get_series(series_id).dropna()
        if len(data) < 2:
            return None, None, None
        return data.iloc[-1], data.iloc[-2], data.index[-1]
    except:
        return None, None, None

@st.cache_data(ttl=3600)
def ai_commentary(context_data, focus):
    try:
        client = get_openai()
        system_msg = "너는 거시경제 및 주식 분석가야. 한국어로 간결하게 해설해줘."
        user_msg = (
            f"[데이터]\n{context_data}\n\n"
            f"[해설 관점]\n{focus}\n\n"
            "규칙:\n"
            "- 5-7문장으로 핵심만\n"
            "- 숫자의 의미와 시장 함의 위주\n"
            "- 단정적 예측 금지, 가능성 위주로\n"
            "- 기술적 지표는 참고 사항임을 명시\n"
            "- 마지막에 '주목할 점:' 한 줄 추가"
        )

        response = client.chat.completions.create(
            model="gpt-5-mini",
            max_completion_tokens=500,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 해설 생성 실패: {e}"

# ============================================
# 주식 데이터 로딩
# ============================================
@st.cache_data(ttl=900)  # 15분 캐시
def load_stock_data(ticker, market, years=2):
    """주식 데이터 가져오기"""
    end = datetime.now()
    start = end - timedelta(days=365 * years)
    try:
        if market == "US":
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        else:  # KR
            df = fdr.DataReader(ticker, start, end)
        
        df = df.dropna()
        return df
    except Exception as e:
        st.error(f"주식 데이터 로딩 실패 ({ticker}): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_stock_info(ticker, market):
    """종목 기본 정보"""
    info = {}
    try:
        if market == "US":
            t = yf.Ticker(ticker)
            raw = t.info
            info = {
                "name": raw.get("longName", ticker),
                "sector": raw.get("sector", "N/A"),
                "industry": raw.get("industry", "N/A"),
                "market_cap": raw.get("marketCap", 0),
                "pe": raw.get("trailingPE", None),
                "forward_pe": raw.get("forwardPE", None),
                "pb": raw.get("priceToBook", None),
                "dividend_yield": raw.get("dividendYield", 0),
                "52w_high": raw.get("fiftyTwoWeekHigh", None),
                "52w_low": raw.get("fiftyTwoWeekLow", None),
                "currency": raw.get("currency", "USD"),
            }
        else:
            # 한국 주식은 정보가 제한적 — 기본만
            info = {
                "name": ticker,
                "sector": "N/A",
                "industry": "N/A",
                "market_cap": 0,
                "pe": None,
                "forward_pe": None,
                "pb": None,
                "dividend_yield": 0,
                "52w_high": None,
                "52w_low": None,
                "currency": "KRW",
            }
    except Exception as e:
        st.warning(f"종목 정보 일부 누락: {e}")
    return info

# ============================================
# 기술적 지표 계산
# ============================================
def add_technical_indicators(df):
    """이동평균, RSI, MACD, 볼린저밴드 추가"""
    close = df["Close"]
    
    df["MA20"] = SMAIndicator(close, window=20).sma_indicator()
    df["MA60"] = SMAIndicator(close, window=60).sma_indicator()
    df["MA120"] = SMAIndicator(close, window=120).sma_indicator()
    
    df["RSI"] = RSIIndicator(close, window=14).rsi()
    
    macd = MACD(close)
    df["MACD"] = macd.macd()
    df["MACD_signal"] = macd.macd_signal()
    df["MACD_hist"] = macd.macd_diff()
    
    bb = BollingerBands(close, window=20)
    df["BB_upper"] = bb.bollinger_hband()
    df["BB_lower"] = bb.bollinger_lband()
    df["BB_mid"] = bb.bollinger_mavg()
    
    return df

# ============================================
# Supabase 함수
# ============================================
def get_watchlist():
    try:
        res = sb.table("watchlist").select("*").order("added_at", desc=True).execute()
        return res.data
    except Exception as e:
        st.error(f"워치리스트 로딩 실패: {e}")
        return []

def add_to_watchlist(ticker, name, market):
    try:
        sb.table("watchlist").insert({
            "ticker": ticker, "name": name, "market": market
        }).execute()
        return True
    except Exception as e:
        st.error(f"추가 실패: {e}")
        return False

def remove_from_watchlist(ticker, market):
    try:
        sb.table("watchlist").delete().eq("ticker", ticker).eq("market", market).execute()
        return True
    except Exception as e:
        st.error(f"삭제 실패: {e}")
        return False

def get_notes(ticker, market):
    try:
        res = sb.table("stock_notes").select("*").eq("ticker", ticker).eq("market", market).order("note_date", desc=True).execute()
        return res.data
    except Exception as e:
        st.error(f"노트 로딩 실패: {e}")
        return []

def add_note(ticker, market, title, content, target_price, stop_loss, sentiment):
    try:
        sb.table("stock_notes").insert({
            "ticker": ticker,
            "market": market,
            "title": title,
            "content": content,
            "target_price": target_price if target_price else None,
            "stop_loss": stop_loss if stop_loss else None,
            "sentiment": sentiment,
        }).execute()
        return True
    except Exception as e:
        st.error(f"노트 저장 실패: {e}")
        return False

def delete_note(note_id):
    try:
        sb.table("stock_notes").delete().eq("id", note_id).execute()
        return True
    except Exception as e:
        st.error(f"노트 삭제 실패: {e}")
        return False

# ============================================
# 헤더
# ============================================
st.title("📊 투자 대시보드 v3.0")
st.caption(f"매크로 + 종목 분석 + AI 해설 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================
# 탭 구성
# ============================================
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🏠 Overview",
    "🚨 Recession Watch",
    "🏦 Fed Watch",
    "🇰🇷 Korea",
    "💰 Assets",
    "🔍 Explorer",
    "📈 Stocks"
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
        with st.spinner("GPT-5 mini가 분석 중..."):
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
    
    spread, _, _ = get_latest_value("T10Y2Y")
    if spread is not None:
        is_warning = spread < 0
        signals["장단기 스프레드 (10Y-2Y)"] = {
            "value": f"{spread:.2f}%", "warning": is_warning,
            "desc": "음수 = 역전 (12-18개월 후 침체 가능성)"
        }
        if is_warning: score += 1
    
    spread3m, _, _ = get_latest_value("T10Y3M")
    if spread3m is not None:
        is_warning = spread3m < 0
        signals["장단기 스프레드 (10Y-3M)"] = {
            "value": f"{spread3m:.2f}%", "warning": is_warning,
            "desc": "연준이 더 신뢰하는 신호"
        }
        if is_warning: score += 1
    
    sahm, _, _ = get_latest_value("SAHMREALTIME")
    if sahm is not None:
        is_warning = sahm >= 0.5
        signals["Sahm Rule"] = {
            "value": f"{sahm:.2f}", "warning": is_warning,
            "desc": "0.5 초과 = 침체 진입 신호"
        }
        if is_warning: score += 1
    
    claims = load_series("ICSA", years=2)
    if len(claims) > 4:
        ma4 = claims.rolling(4).mean().iloc[-1]
        ma4_3m_ago = claims.rolling(4).mean().iloc[-13] if len(claims) > 13 else ma4
        change_pct = (ma4 - ma4_3m_ago) / ma4_3m_ago * 100
        is_warning = change_pct > 20
        signals["신규 실업수당 (4주이평, 3개월 변화)"] = {
            "value": f"{change_pct:+.1f}%", "warning": is_warning,
            "desc": "+20% 이상 = 노동시장 악화"
        }
        if is_warning: score += 1
    
    hy, _, _ = get_latest_value("BAMLH0A0HYM2")
    if hy is not None:
        is_warning = hy > 6.0
        signals["하이일드 신용 스프레드"] = {
            "value": f"{hy:.2f}%", "warning": is_warning,
            "desc": "6% 초과 = 신용 위기 신호"
        }
        if is_warning: score += 1
    
    total = len(signals)
    
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
        with st.spinner("GPT-5 mini가 분석 중..."):
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
            latest = latest / 1e6
            prev = prev / 1e6 if prev else prev
        
        delta = latest - prev if prev is not None else 0
        fed_summary[label] = round(latest, 2)
        
        with cols[i % 3]:
            st.metric(label, f"{latest:,.2f}", f"{delta:+,.2f}")
    
    st.divider()
    
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
        with st.spinner("GPT-5 mini가 분석 중..."):
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
        with st.spinner("GPT-5 mini가 분석 중..."):
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
        "10년 실질금리 (TIPS, %)": "DFII10",
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
        with st.spinner("GPT-5 mini가 분석 중..."):
            commentary = ai_commentary(
                asset_summary,
                "자산군 현황을 진단해줘. VIX, 실질금리, 유가, 달러, 채권 금리, 신용 스프레드의 조합으로 본 시장 심리."
            )
            st.info(commentary)

# ============================================
# 🔍 TAB 6: Explorer
# ============================================
with tab6:
    st.header("자유 탐색")
    st.caption("원하는 FRED Series ID를 직접 입력하거나 카탈로그에서 선택하세요.")
    
    EXPLORER_CATALOG = {
        "성장": {"GDPC1": "실질 GDP", "INDPRO": "산업생산지수"},
        "물가": {"CPIAUCSL": "CPI (전체)", "CPILFESL": "근원 CPI", "PCEPI": "PCE 물가지수"},
        "고용": {"UNRATE": "실업률", "PAYEMS": "비농업 고용", "ICSA": "신규 실업수당"},
        "금리": {"DFF": "연방기금금리", "DGS10": "10년물 국채", "DGS2": "2년물 국채", "T10Y2Y": "10Y-2Y 스프레드"},
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
# 📈 TAB 7: Stocks (신규)
# ============================================
with tab7:
    st.header("개별 종목 분석")
    st.caption("⚠️ 기술적 지표는 참고용입니다. 매수/매도 시그널이 아닙니다.")
    
    # ====== 워치리스트 관리 ======
    st.subheader("📋 워치리스트")
    
    watchlist = get_watchlist()
    
    with st.expander("➕ 종목 추가/삭제"):
        col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 1])
        with col_a:
            new_ticker = st.text_input("티커", placeholder="AAPL 또는 005930", key="new_ticker")
        with col_b:
            new_name = st.text_input("종목명", placeholder="Apple", key="new_name")
        with col_c:
            new_market = st.selectbox("시장", ["US", "KR"], key="new_market")
        with col_d:
            st.write("")
            st.write("")
            if st.button("추가", key="add_btn"):
                if new_ticker and new_name:
                    if add_to_watchlist(new_ticker.upper().strip(), new_name.strip(), new_market):
                        st.success("추가됨!")
                        st.rerun()
        
        if watchlist:
            st.divider()
            st.write("**삭제하기**")
            for w in watchlist:
                col_x, col_y = st.columns([4, 1])
                with col_x:
                    st.write(f"[{w['market']}] {w['ticker']} - {w['name']}")
                with col_y:
                    if st.button("❌", key=f"del_{w['id']}"):
                        if remove_from_watchlist(w['ticker'], w['market']):
                            st.rerun()
    
    if not watchlist:
        st.info("워치리스트가 비어있습니다. 위에서 종목을 추가하세요.")
        st.stop()
    
    # ====== 종목 선택 ======
    st.divider()
    
    ticker_options = {f"[{w['market']}] {w['ticker']} - {w['name']}": (w['ticker'], w['market']) 
                      for w in watchlist}
    selected_label = st.selectbox("종목 선택", list(ticker_options.keys()))
    selected_ticker, selected_market = ticker_options[selected_label]
    
    period_stock = st.radio("기간", ["3개월", "6개월", "1년", "2년"], horizontal=True, index=2, key="stock_period")
    period_years = {"3개월": 0.25, "6개월": 0.5, "1년": 1, "2년": 2}[period_stock]
    
    # ====== 데이터 로딩 ======
    with st.spinner(f"{selected_ticker} 데이터 로딩 중..."):
        df = load_stock_data(selected_ticker, selected_market, years=max(period_years, 1))
        info = get_stock_info(selected_ticker, selected_market)
    
    if df.empty:
        st.error("데이터를 가져올 수 없습니다.")
        st.stop()
    
    # 기술적 지표 추가
    df = add_technical_indicators(df)
    
    # 기간 필터링
    cutoff = datetime.now() - timedelta(days=int(365 * period_years))
    df_view = df[df.index >= cutoff].copy()
    
    # ====== 기본 정보 ======
    st.subheader(f"📌 {info.get('name', selected_ticker)} ({selected_ticker})")
    
    current_price = df["Close"].iloc[-1]
    prev_price = df["Close"].iloc[-2]
    daily_change = (current_price - prev_price) / prev_price * 100
    
    currency = info.get("currency", "USD")
    symbol = "₩" if currency == "KRW" else "$"
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("현재가", f"{symbol}{current_price:,.2f}", f"{daily_change:+.2f}%")
    col2.metric("52주 최고", 
                f"{symbol}{info['52w_high']:,.2f}" if info['52w_high'] else "N/A",
                f"{(current_price/info['52w_high']-1)*100:+.1f}%" if info['52w_high'] else "")
    col3.metric("52주 최저",
                f"{symbol}{info['52w_low']:,.2f}" if info['52w_low'] else "N/A",
                f"{(current_price/info['52w_low']-1)*100:+.1f}%" if info['52w_low'] else "")
    col4.metric("RSI (14)", f"{df['RSI'].iloc[-1]:.1f}",
                "과매수" if df['RSI'].iloc[-1] > 70 else ("과매도" if df['RSI'].iloc[-1] < 30 else "중립"))
    
    # 추가 펀더멘털 (미국 종목만)
    if selected_market == "US" and info.get("pe"):
        col5, col6, col7, col8 = st.columns(4)
        col5.metric("PER", f"{info['pe']:.1f}" if info['pe'] else "N/A")
        col6.metric("Forward PER", f"{info['forward_pe']:.1f}" if info['forward_pe'] else "N/A")
        col7.metric("PBR", f"{info['pb']:.2f}" if info['pb'] else "N/A")
        col8.metric("배당수익률", f"{info['dividend_yield']*100:.2f}%" if info['dividend_yield'] else "N/A")
        st.caption(f"섹터: {info.get('sector', 'N/A')} | 산업: {info.get('industry', 'N/A')}")
    
    st.divider()
    
    # ====== 차트: 가격 + 이동평균 + 볼린저밴드 ======
    st.subheader("📊 가격 차트 & 기술적 지표")
    
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05,
                        row_heights=[0.6, 0.2, 0.2],
                        subplot_titles=("가격 + 이동평균 + 볼린저밴드", "거래량", "RSI / MACD"))
    
    # 캔들스틱
    fig.add_trace(go.Candlestick(
        x=df_view.index, open=df_view["Open"], high=df_view["High"],
        low=df_view["Low"], close=df_view["Close"], name="가격",
        increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
    ), row=1, col=1)
    
    # 이동평균
    for ma, color in [("MA20", "#ff9800"), ("MA60", "#9c27b0"), ("MA120", "#3f51b5")]:
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view[ma], name=ma,
                                 line=dict(color=color, width=1)), row=1, col=1)
    
    # 볼린저밴드
    fig.add_trace(go.Scatter(x=df_view.index, y=df_view["BB_upper"], name="BB 상단",
                             line=dict(color='gray', width=0.5, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_view.index, y=df_view["BB_lower"], name="BB 하단",
                             line=dict(color='gray', width=0.5, dash='dot'),
                             fill='tonexty', fillcolor='rgba(128,128,128,0.05)'), row=1, col=1)
    
    # 거래량
    colors = ['#ef5350' if c >= o else '#26a69a' 
              for c, o in zip(df_view["Close"], df_view["Open"])]
    fig.add_trace(go.Bar(x=df_view.index, y=df_view["Volume"], name="거래량",
                         marker_color=colors, showlegend=False), row=2, col=1)
    
    # RSI
    fig.add_trace(go.Scatter(x=df_view.index, y=df_view["RSI"], name="RSI",
                             line=dict(color='#1f77b4', width=1.5)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)
    
    fig.update_layout(height=800, template='plotly_white',
                      xaxis_rangeslider_visible=False,
                      hovermode='x unified')
    
    st.plotly_chart(fig, use_container_width=True)
    
    # ====== 기술적 지표 요약 ======
    st.subheader("🔍 기술적 신호 요약")
    
    rsi_now = df["RSI"].iloc[-1]
    macd_now = df["MACD"].iloc[-1]
    macd_signal = df["MACD_signal"].iloc[-1]
    ma20_now = df["MA20"].iloc[-1]
    ma60_now = df["MA60"].iloc[-1]
    ma120_now = df["MA120"].iloc[-1]
    
    signals_tech = []
    if rsi_now > 70:
        signals_tech.append(("🔴 RSI 과매수", f"{rsi_now:.1f} (>70)"))
    elif rsi_now < 30:
        signals_tech.append(("🟢 RSI 과매도", f"{rsi_now:.1f} (<30)"))
    else:
        signals_tech.append(("⚪ RSI 중립", f"{rsi_now:.1f}"))
    
    if macd_now > macd_signal:
        signals_tech.append(("🟢 MACD 상승 우위", f"{macd_now:.2f} > {macd_signal:.2f}"))
    else:
        signals_tech.append(("🔴 MACD 하락 우위", f"{macd_now:.2f} < {macd_signal:.2f}"))
    
    if current_price > ma20_now > ma60_now > ma120_now:
        signals_tech.append(("🟢 정배열", "단·중·장기 추세 상승"))
    elif current_price < ma20_now < ma60_now < ma120_now:
        signals_tech.append(("🔴 역배열", "단·중·장기 추세 하락"))
    else:
        signals_tech.append(("⚪ 혼조", "추세 불명확"))
    
    bb_pos = (current_price - df["BB_lower"].iloc[-1]) / (df["BB_upper"].iloc[-1] - df["BB_lower"].iloc[-1])
    if bb_pos > 0.95:
        signals_tech.append(("🔴 볼린저 상단 근접", f"{bb_pos*100:.0f}% 지점"))
    elif bb_pos < 0.05:
        signals_tech.append(("🟢 볼린저 하단 근접", f"{bb_pos*100:.0f}% 지점"))
    else:
        signals_tech.append(("⚪ 볼린저 중간", f"{bb_pos*100:.0f}% 지점"))
    
    for name, val in signals_tech:
        st.write(f"{name}: **{val}**")
    
    # ====== AI 해설 ======
    if st.button("🤖 종목 AI 해설 보기", key="stock_ai"):
        stock_ctx = {
            "종목": f"{info.get('name')} ({selected_ticker})",
            "현재가": f"{symbol}{current_price:,.2f}",
            "1일 변동": f"{daily_change:+.2f}%",
            "RSI": f"{rsi_now:.1f}",
            "MACD": f"{macd_now:.2f} vs Signal {macd_signal:.2f}",
            "이동평균 정렬": "정배열" if current_price > ma20_now > ma60_now > ma120_now else 
                          ("역배열" if current_price < ma20_now < ma60_now < ma120_now else "혼조"),
            "볼린저 위치": f"{bb_pos*100:.0f}%",
            "52주 위치": f"최고대비 {(current_price/info['52w_high']-1)*100:+.1f}%" if info['52w_high'] else "N/A",
        }
        if selected_market == "US":
            stock_ctx["PER"] = info.get("pe")
            stock_ctx["섹터"] = info.get("sector")
        
        with st.spinner("GPT-5 mini가 분석 중..."):
            commentary = ai_commentary(
                stock_ctx,
                f"{info.get('name')} 종목의 현재 상황을 진단해줘. 기술적 지표와 펀더멘털(가능한 경우)을 균형있게."
            )
            st.info(commentary)
    
    st.divider()
    
    # ====== 종목 노트 ======
    st.subheader("📝 종목 노트")
    
    with st.expander("✏️ 새 노트 작성"):
        note_title = st.text_input("제목", placeholder="예: 4분기 실적 발표 후 분석")
        note_content = st.text_area("내용", height=150, placeholder="매수 사유, 관찰 포인트, 리스크 등...")
        col_n1, col_n2, col_n3 = st.columns(3)
        with col_n1:
            note_target = st.number_input(f"목표가 ({symbol})", min_value=0.0, value=0.0, step=1.0)
        with col_n2:
            note_stop = st.number_input(f"손절가 ({symbol})", min_value=0.0, value=0.0, step=1.0)
        with col_n3:
            note_sentiment = st.selectbox("관점", ["bullish", "neutral", "bearish"],
                                          format_func=lambda x: {"bullish": "🟢 강세", "neutral": "⚪ 중립", "bearish": "🔴 약세"}[x])
        
        if st.button("💾 노트 저장", key="save_note"):
            if note_title and note_content:
                if add_note(selected_ticker, selected_market, note_title, note_content,
                           note_target if note_target > 0 else None,
                           note_stop if note_stop > 0 else None,
                           note_sentiment):
                    st.success("노트 저장됨!")
                    st.rerun()
            else:
                st.warning("제목과 내용을 입력하세요.")
    
    # 노트 목록
    notes = get_notes(selected_ticker, selected_market)
    if notes:
        st.write(f"**총 {len(notes)}개의 노트**")
        for note in notes:
            sentiment_icon = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴"}.get(note.get("sentiment"), "")
            with st.expander(f"{sentiment_icon} [{note['note_date']}] {note['title']}"):
                st.write(note["content"])
                col_meta1, col_meta2, col_meta3 = st.columns(3)
                if note.get("target_price"):
                    col_meta1.write(f"🎯 목표가: {symbol}{note['target_price']:,.2f}")
                if note.get("stop_loss"):
                    col_meta2.write(f"🛑 손절가: {symbol}{note['stop_loss']:,.2f}")
                col_meta3.write(f"작성: {note.get('created_at', '')[:10]}")
                
                if st.button("🗑️ 삭제", key=f"del_note_{note['id']}"):
                    if delete_note(note['id']):
                        st.rerun()
    else:
        st.info("아직 작성된 노트가 없습니다.")

# ============================================
# 푸터
# ============================================
st.divider()
st.caption("Data: FRED + yfinance + FinanceDataReader | AI: GPT-5 mini | Storage: Supabase | Made by Raykel")
