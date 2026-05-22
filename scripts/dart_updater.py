"""
DART → Supabase 자동 업데이트 스크립트
GitHub Actions가 매주 1회 실행
"""

import os
import sys
import time
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime
from supabase import create_client

# === 환경변수 ===
DART_API_KEY = os.environ.get("DART_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not all([DART_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ 환경변수 누락")
    sys.exit(1)

# === 연결 ===
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
DART_BASE = "https://opendart.fss.or.kr/api"


def dart_request(endpoint, params):
    params["crtfc_key"] = DART_API_KEY
    url = f"{DART_BASE}/{endpoint}"
    resp = requests.get(url, params=params, timeout=30)
    return resp.json()


def load_all_corp_codes():
    """DART 전체 corp_code ZIP 다운로드 → 매핑 딕셔너리"""
    print("📥 DART 전체 회사 코드 다운로드 중...")
    url = f"{DART_BASE}/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}
    
    # 재시도 로직 (최대 3회)
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=120)
            
            print(f"   응답 상태: {resp.status_code}")
            print(f"   응답 크기: {len(resp.content)} bytes")
            print(f"   Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
            
            if resp.status_code != 200:
                print(f"❌ HTTP 에러: {resp.status_code}")
                if attempt < 2:
                    print(f"   3초 후 재시도... ({attempt + 2}/3)")
                    time.sleep(3)
                    continue
                return {}
            
            # ZIP인지 확인 (ZIP 파일은 'PK'로 시작)
            if not resp.content.startswith(b'PK'):
                # ZIP이 아니면 응답 내용 확인
                preview = resp.content[:500].decode('utf-8', errors='ignore')
                print(f"⚠️ ZIP 아닌 응답 받음. 내용 미리보기:")
                print(f"   {preview}")
                
                if attempt < 2:
                    print(f"   5초 후 재시도... ({attempt + 2}/3)")
                    time.sleep(5)
                    continue
                return {}
            
            # ZIP 정상 처리
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            xml_data = z.read(z.namelist()[0]).decode("utf-8")
            root = ET.fromstring(xml_data)
            
            mapping = {}
            for item in root.findall("list"):
                sc = item.findtext("stock_code", "").strip()
                if sc:
                    corp_code = item.findtext("corp_code", "").strip()
                    corp_name = item.findtext("corp_name", "").strip()
                    mapping[sc] = (corp_code, corp_name)
            
            print(f"✅ {len(mapping)}개 상장사 매핑 로드")
            return mapping
            
        except Exception as e:
            print(f"❌ 시도 {attempt + 1} 실패: {e}")
            if attempt < 2:
                time.sleep(5)
            else:
                return {}
    
    return {}


def get_amount_from_list(items, account_nm_list):
    for nm in account_nm_list:
        for item in items:
            account_nm = item.get("account_nm", "")
            if nm in account_nm:
                try:
                    val = item.get("thstrm_amount", "")
                    if val and val != "-":
                        return float(str(val).replace(",", ""))
                except:
                    continue
    return None


def fetch_kr_financial(ticker, corp_code, corp_name, years):
    """한 종목 재무 데이터 수집"""
    try:
        # 회사 정보
        company_resp = dart_request("company.json", {"corp_code": corp_code})
        if company_resp.get("status") != "000":
            return None, []
        
        company_info = {
            "ticker": ticker,
            "corp_code": corp_code,
            "corp_name": company_resp.get("corp_name", corp_name),
            "ceo_name": company_resp.get("ceo_nm", ""),
            "establish_date": company_resp.get("est_dt", ""),
            "industry": company_resp.get("induty_code", ""),
            "homepage": company_resp.get("hm_url", ""),
        }
        
        financial_data = []
        for year in years:
            try:
                fs_resp = dart_request("fnlttSinglAcnt.json", {
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": "11011",
                })
                
                if fs_resp.get("status") != "000":
                    continue
                
                items = fs_resp.get("list", [])
                if not items:
                    continue
                
                cfs_items = [i for i in items if i.get("fs_div") == "CFS"]
                if not cfs_items:
                    cfs_items = [i for i in items if i.get("fs_div") == "OFS"]
                if not cfs_items:
                    cfs_items = items
                
                revenue = get_amount_from_list(cfs_items, ['매출액', '수익(매출액)', '영업수익'])
                op_profit = get_amount_from_list(cfs_items, ['영업이익'])
                net_income = get_amount_from_list(cfs_items, ['당기순이익', '연결당기순이익'])
                total_assets = get_amount_from_list(cfs_items, ['자산총계'])
                total_equity = get_amount_from_list(cfs_items, ['자본총계'])
                total_liabilities = get_amount_from_list(cfs_items, ['부채총계'])
                
                if not revenue:
                    continue
                
                financial_data.append({
                    "ticker": ticker,
                    "corp_code": corp_code,
                    "corp_name": company_info["corp_name"],
                    "fiscal_year": year,
                    "revenue": revenue,
                    "operating_profit": op_profit,
                    "net_income": net_income,
                    "total_assets": total_assets,
                    "total_equity": total_equity,
                    "total_liabilities": total_liabilities,
                    "operating_margin": (op_profit / revenue * 100) if (revenue and op_profit) else None,
                    "net_margin": (net_income / revenue * 100) if (revenue and net_income) else None,
                    "roe": (net_income / total_equity * 100) if (total_equity and net_income) else None,
                    "roa": (net_income / total_assets * 100) if (total_assets and net_income) else None,
                    "debt_ratio": (total_liabilities / total_equity * 100) if (total_equity and total_liabilities) else None,
                    "updated_at": datetime.now().isoformat(),
                })
            except Exception as e:
                print(f"    ⚠️ {year}년 실패: {e}")
                continue
        
        return company_info, financial_data
    except Exception as e:
        print(f"  ❌ 전체 실패: {e}")
        return None, []


def save_to_supabase(company_info, financial_data):
    if company_info:
        try:
            sb.table("kr_companies").upsert(company_info, on_conflict="ticker").execute()
        except Exception as e:
            print(f"  회사정보 저장 실패: {e}")
    
    for fin in financial_data:
        try:
            sb.table("kr_financials").upsert(fin, on_conflict="ticker,fiscal_year").execute()
        except Exception as e:
            print(f"  재무 저장 실패 ({fin.get('fiscal_year')}): {e}")


def main():
    print("=" * 50)
    print(f"🚀 DART 데이터 업데이트 시작")
    print(f"   시각: {datetime.now().isoformat()}")
    print("=" * 50)
    
    # 1. Supabase에서 워치리스트의 한국 종목 가져오기
    print("\n[1] 워치리스트 조회...")
    watchlist_resp = sb.table("watchlist").select("*").eq("market", "KR").execute()
    kr_tickers = [w["ticker"] for w in watchlist_resp.data]
    
    if not kr_tickers:
        print("   워치리스트에 한국 종목 없음. 종료.")
        return
    
    print(f"   대상: {len(kr_tickers)}개 종목")
    print(f"   {kr_tickers}")
    
    # 2. corp_code 매핑 다운로드
    print("\n[2] corp_code 매핑 다운로드...")
    corp_mapping = load_all_corp_codes()
    if not corp_mapping:
        print("❌ corp_code 매핑 실패. 종료.")
        sys.exit(1)
    
    # 3. 종목별 수집
    print("\n[3] 종목별 재무 데이터 수집...")
    current_year = datetime.now().year
    years_to_fetch = [current_year - 1, current_year - 2, current_year - 3]
    
    success_count = 0
    fail_count = 0
    
    for i, ticker in enumerate(kr_tickers, 1):
        if ticker not in corp_mapping:
            print(f"\n[{i}/{len(kr_tickers)}] {ticker}: ❌ corp_code 못 찾음")
            fail_count += 1
            continue
        
        corp_code, corp_name = corp_mapping[ticker]
        print(f"\n[{i}/{len(kr_tickers)}] {ticker} ({corp_name})")
        
        company_info, financial_data = fetch_kr_financial(ticker, corp_code, corp_name, years_to_fetch)
        
        if company_info and financial_data:
            save_to_supabase(company_info, financial_data)
            print(f"  ✅ {len(financial_data)}개 연도 저장")
            success_count += 1
        else:
            print(f"  ❌ 데이터 없음")
            fail_count += 1
        
        time.sleep(0.5)
    
    print("\n" + "=" * 50)
    print(f"🎉 완료: 성공 {success_count} / 실패 {fail_count}")
    print("=" * 50)


if __name__ == "__main__":
    main()
