"""
ECOS (한국은행) → Supabase 자동 업데이트 스크립트
GitHub Actions가 매주 1회 실행
"""

import os
import sys
import time
import requests
from datetime import datetime, timedelta
from supabase import create_client

# === 환경변수 ===
ECOS_API_KEY = os.environ.get("ECOS_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not all([ECOS_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ 환경변수 누락")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
ECOS_BASE = "https://ecos.bok.or.kr/api"


# ============================================
# 수집할 시계열 정의
# ============================================
# (series_id_internal, ecos_stat_code, ecos_item_code, name, frequency, cycle)
# frequency: 'D' 일, 'M' 월, 'Q' 분기, 'A' 연간
SERIES = [
    # 국고채 금리 (일별)
    ("kr_gov_3y", "817Y002", "010200000", "국고채 3년", "D"),
    ("kr_gov_10y", "817Y002", "010210000", "국고채 10년", "D"),
    ("kr_gov_1y", "817Y002", "010195000", "국고채 1년", "D"),
    
    # 한국은행 기준금리 (일별)
    ("kr_base_rate", "722Y001", "0101000", "한국은행 기준금리", "D"),
    
    # BSI 기업경기실사지수 (월별)
    ("kr_bsi", "512Y014", "AX1AA", "BSI 제조업 (실적)", "M"),
    
    # CSI 소비자심리지수 (월별)
    ("kr_csi", "511Y002", "FME", "CSI 소비자심리", "M"),
    
    # 수출 (월별)
    ("kr_export", "403Y001", "*AA", "수출금액", "M"),
]


def fetch_ecos_series(stat_code, item_code, frequency, start_date, end_date):
    """ECOS API에서 시계열 데이터 가져오기"""
    # ECOS는 'DD' (일), 'MM' (월), 'QQ' (분기), 'YY' (연)
    cycle_map = {"D": "D", "M": "M", "Q": "Q", "A": "A"}
    cycle = cycle_map.get(frequency, "D")
    
    # 날짜 포맷
    if cycle == "D":
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
    elif cycle == "M":
        start_str = start_date.strftime("%Y%m")
        end_str = end_date.strftime("%Y%m")
    elif cycle == "Q":
        q_start = (start_date.month - 1) // 3 + 1
        q_end = (end_date.month - 1) // 3 + 1
        start_str = f"{start_date.year}Q{q_start}"
        end_str = f"{end_date.year}Q{q_end}"
    else:
        start_str = str(start_date.year)
        end_str = str(end_date.year)
    
    url = (
        f"{ECOS_BASE}/StatisticSearch/{ECOS_API_KEY}/json/kr/1/10000/"
        f"{stat_code}/{cycle}/{start_str}/{end_str}/{item_code}"
    )
    
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        
        data = resp.json()
        
        # 에러 응답 처리
        if "StatisticSearch" not in data:
            err_msg = data.get("RESULT", {}).get("MESSAGE", "Unknown error")
            return None, err_msg
        
        rows = data["StatisticSearch"].get("row", [])
        if not rows:
            return None, "no data"
        
        return rows, None
    
    except Exception as e:
        return None, str(e)


def parse_date(time_str, frequency):
    """ECOS의 TIME 문자열을 datetime으로 변환"""
    try:
        if frequency == "D":
            return datetime.strptime(time_str, "%Y%m%d").date()
        elif frequency == "M":
            return datetime.strptime(time_str + "01", "%Y%m%d").date()
        elif frequency == "Q":
            year = int(time_str[:4])
            q = int(time_str[5])  # 'Q' 다음 숫자
            month = (q - 1) * 3 + 1
            return datetime(year, month, 1).date()
        else:
            return datetime(int(time_str), 1, 1).date()
    except:
        return None


def save_to_supabase(series_id, series_name, frequency, rows):
    """Supabase에 저장"""
    saved_count = 0
    for row in rows:
        time_str = row.get("TIME", "")
        value_str = row.get("DATA_VALUE", "")
        unit = row.get("UNIT_NAME", "")
        
        obs_date = parse_date(time_str, frequency)
        if obs_date is None:
            continue
        
        try:
            value = float(value_str)
        except:
            continue
        
        try:
            sb.table("kr_macro").upsert({
                "series_id": series_id,
                "series_name": series_name,
                "observation_date": obs_date.isoformat(),
                "value": value,
                "unit": unit,
                "frequency": frequency,
                "updated_at": datetime.now().isoformat(),
            }, on_conflict="series_id,observation_date").execute()
            saved_count += 1
        except Exception as e:
            print(f"    ⚠️ 저장 실패 ({obs_date}): {e}")
    
    return saved_count


def main():
    print("=" * 50)
    print(f"🚀 ECOS 데이터 업데이트 시작")
    print(f"   시각: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # 최근 3년치 데이터 수집
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=365 * 3)
    
    success = 0
    fail = 0
    
    for series_id, stat_code, item_code, name, freq in SERIES:
        print(f"\n📥 {series_id} ({name}) 수집 중...")
        
        rows, err = fetch_ecos_series(stat_code, item_code, freq, start_date, end_date)
        
        if err:
            print(f"   ❌ 실패: {err}")
            fail += 1
            continue
        
        saved = save_to_supabase(series_id, name, freq, rows)
        print(f"   ✅ {saved}개 저장")
        success += 1
        
        time.sleep(0.5)  # API 부담 방지
    
    print("\n" + "=" * 50)
    print(f"🎉 완료: 성공 {success} / 실패 {fail}")
    print("=" * 50)


if __name__ == "__main__":
    main()
