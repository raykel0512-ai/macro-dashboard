# v1.0
# 매크로 대시보드 - FRED 데이터 기반
# Made by Raykel

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from fredapi import Fred
from datetime import datetime, timedelta

# ============================================
# 페이지 설정
# ============================================
st.set_page_config(
    page_title="매크로 대시보드",
    page_icon="📊",
    layout="wide"
)

# ============================================
# FRED API 연결
# ============================================
@st.cache_resource
def get_fred():
    return Fred(api_key=st.secrets["FRED_API_KEY"])

fred = get_fred()

# ============================================
# 지표 카탈로그
# ============================================
INDICATORS = {
    "성장": {
        "GDPC1": "실질 GDP (분기, 십억 달러)",
        "INDPRO": "산업생산지수",
    },
    "물가": {
        "CPIAUCSL": "CPI (전체)",
        "CPILFESL": "근원 CPI",
        "PCEPI": "PCE 물가지수 (연준 선호)",
    },
    "고용": {
        "UNRATE": "실업률 (%)",
        "PAYEMS": "비농업 고용자 수 (천명)",
        "ICSA": "신규 실업수당 청구",
    },
    "금리": {
        "DFF": "연방기금금리 (실효)",
        "DGS10": "미국 10년물 국채금리",
        "DGS2": "미국 2년물 국채금리",
        "T10Y2Y": "장단기 스프레드 (10Y-2Y)",
    },
    "통화·시장": {
        "M2SL": "M2 통화량",
        "VIXCLS": "VIX 변동성지수",
        "DEXKOUS": "원/달러 환율",
    },
}

# ============================================
# 데이터 로딩 함수
# ============================================
@st.cache_data(ttl=3600)
def load_series(series_id, start_date):
    """FRED에서 시계열 데이터 가져오기 (1시간 캐시)"""
    try:
        data = fred.get_series(series_id, observation_start=start_date)
        return data.dropna()
    except Exception as e:
        st.error(f"데이터 로딩 실패 ({series_id}): {e}")
        return pd.Series(dtype=float)

@st.cache_data(ttl=3600)
def get_series_info(series_id):
    """시계열 메타정보"""
    try:
        return fred.get_series_info(series_id)
    except:
        return None

# ============================================
# 사이드바
# ============================================
st.sidebar.title("⚙️ 설정")

# 카테고리 선택
category = st.sidebar.selectbox(
    "카테고리",
    list(INDICATORS.keys())
)

# 지표 선택
series_dict = INDICATORS[category]
series_id = st.sidebar.selectbox(
    "지표",
    list(series_dict.keys()),
    format_func=lambda x: f"{x} - {series_dict[x]}"
)

# 기간 설정
period_option = st.sidebar.radio(
    "조회 기간",
    ["1년", "3년", "5년", "10년", "전체"],
    index=2
)

period_map = {
    "1년": 365,
    "3년": 365 * 3,
    "5년": 365 * 5,
    "10년": 365 * 10,
    "전체": 365 * 50,
}
start_date = (datetime.now() - timedelta(days=period_map[period_option])).strftime("%Y-%m-%d")

# 변환 옵션
transform = st.sidebar.selectbox(
    "데이터 변환",
    ["원본", "전년동월대비 (%)", "전월대비 (%)", "이동평균 (12개월)"]
)

# ============================================
# 메인
# ============================================
st.title("📊 매크로 대시보드")
st.caption(f"FRED 기반 실시간 거시경제 모니터링 | 마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# 데이터 로딩
data = load_series(series_id, start_date)

if data.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

# 변환 적용
if transform == "전년동월대비 (%)":
    data = data.pct_change(periods=12) * 100
elif transform == "전월대비 (%)":
    data = data.pct_change() * 100
elif transform == "이동평균 (12개월)":
    data = data.rolling(window=12).mean()

data = data.dropna()

# ============================================
# 핵심 지표 카드
# ============================================
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("최신값", f"{data.iloc[-1]:,.2f}")
with col2:
    change = data.iloc[-1] - data.iloc[-2] if len(data) > 1 else 0
    st.metric("직전 대비", f"{change:+,.2f}")
with col3:
    st.metric("기간 최고", f"{data.max():,.2f}")
with col4:
    st.metric("기간 최저", f"{data.min():,.2f}")

# ============================================
# 차트
# ============================================
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=data.index,
    y=data.values,
    mode='lines',
    name=series_id,
    line=dict(color='#1f77b4', width=2),
    fill='tozeroy' if transform != "원본" else None,
    fillcolor='rgba(31, 119, 180, 0.1)',
))

# 0선 표시 (변환된 데이터의 경우)
if transform in ["전년동월대비 (%)", "전월대비 (%)"]:
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

fig.update_layout(
    title=f"{series_id} - {series_dict[series_id]} ({transform})",
    xaxis_title="날짜",
    yaxis_title="값",
    height=500,
    hovermode='x unified',
    template='plotly_white',
)

st.plotly_chart(fig, use_container_width=True)

# ============================================
# 지표 정보
# ============================================
with st.expander("📖 지표 상세 정보"):
    info = get_series_info(series_id)
    if info is not None:
        st.write(f"**제목:** {info.get('title', 'N/A')}")
        st.write(f"**단위:** {info.get('units', 'N/A')}")
        st.write(f"**주기:** {info.get('frequency', 'N/A')}")
        st.write(f"**시즌 조정:** {info.get('seasonal_adjustment', 'N/A')}")
        st.write(f"**마지막 업데이트:** {info.get('last_updated', 'N/A')}")
        notes = info.get('notes', '')
        if notes:
            st.write(f"**설명:** {notes[:500]}...")

# ============================================
# 데이터 테이블
# ============================================
with st.expander("📋 원본 데이터 보기"):
    df = pd.DataFrame({
        '날짜': data.index,
        '값': data.values
    })
    st.dataframe(df.tail(20).iloc[::-1], use_container_width=True, hide_index=True)
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        "📥 CSV 다운로드",
        csv,
        f"{series_id}_{datetime.now().strftime('%Y%m%d')}.csv",
        "text/csv"
    )

# ============================================
# 푸터
# ============================================
st.divider()
st.caption("Data Source: Federal Reserve Economic Data (FRED) | St. Louis Fed")
