# app.py — Streamlit + TAGO(국토부) 버스 조회 (진단/안정화 패치 포함)
import os
import re
from datetime import date
from urllib.parse import urlencode

import certifi
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="시외/고속버스 시간표 & 요금", page_icon="🚌", layout="wide")
st.title("🚌 시외/고속버스 시간표 & 요금 (국토부 TAGO)")
st.caption("• 당일 배차 중심 데이터 · 터미널 검색 → 출/도착 선택 → 조회\n• 네트워크/SSL/오탈자 진단 로그를 화면에 표시하도록 패치됨")

# API 키 (Secrets 또는 환경변수)
API_KEY = st.secrets.get("DATA_GO_KR_KEY", os.getenv("DATA_GO_KR_KEY", ""))

if not API_KEY:
    st.warning("⚠️ 먼저 data.go.kr 서비스키를 Streamlit Secrets의 `DATA_GO_KR_KEY` 로 등록하세요.")
    st.stop()

# =========================
# TAGO 엔드포인트(필요시 교체)
# =========================
BASE = "https://apis.data.go.kr"  # 반드시 https + 정확한 도메인
# 아래 경로/오퍼레이션명은 활용가이드대로 확인해서 필요시 수정
SERVICE_PATH_SUBURBS = "/1613000/SuburbsBusInfoService"
SERVICE_PATH_EXPRESS = "/1613000/ExpBusInfoService"

# 흔히 쓰이는 오퍼레이션명 (문서에서 확인 후 필요시 수정)
OP_SUB_TERMINALS = "getSuberbsBusTrminlList"        # 시외 터미널 목록
OP_SUB_ALLOC     = "getStrtpntAlocFndSuberbsInfo"   # 시외 출/도착 배차
OP_EXP_TERMINALS = "getExpBusTrminlList"            # 고속 터미널 목록
OP_EXP_ALLOC     = "getStrtpntAlocFndExpbusInfo"    # 고속 출/도착 배차

# =========================
# HTTP 세션(재시도/UA/인증서 번들)
# =========================
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Streamlit; bus-app)"})
retries = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods={"GET", "POST"},
    raise_on_status=False,
)
SESSION.mount("https://", HTTPAdapter(max_retries=retries))
SESSION.mount("http://", HTTPAdapter(max_retries=retries))

def mask_key(url: str) -> str:
    return re.sub(r"(serviceKey=)[^&]+", r"\1***MASKED***", url)

def api_get_json(base_url: str, params: dict, *, allow_redirects: bool):
    """완성 URL 로깅 + 인증서 번들 지정 + 리디렉트 제어."""
    q = params.copy()
    q["serviceKey"] = API_KEY
    q.setdefault("_type", "json")
    full_url = f"{base_url}?{urlencode(q, doseq=True)}"

    st.write("🔎 요청 URL (키 마스킹):", mask_key(full_url))
    try:
        r = SESSION.get(
            full_url,
            timeout=20,
            allow_redirects=allow_redirects,
            verify=certifi.where(),  # 인증서 번들 명시
        )
        st.write("↩️ HTTP 상태:", r.status_code)
        if not allow_redirects and 300 <= r.status_code < 400:
            st.warning(f"리디렉트 감지: {r.headers.get('Location')}")
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
    except requests.exceptions.SSLError as e:
        st.error("❌ SSL 오류(인증서/리디렉트/시간 동기화 문제 가능). 아래 예외 요약을 확인하세요.")
        st.exception(e)
        raise
    except requests.exceptions.RequestException as e:
        st.error("❌ 네트워크/HTTP 오류. URL/오퍼레이션명/파라미터를 확인하세요.")
        st.exception(e)
        raise

def normalize_items(top: dict):
    """표준 응답(response>body>items>item) 파싱."""
    try:
        items = top["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        return items
    except Exception:
        return []

def to_time_str(s):
    """'0550' or '055000' → '05:50' / '05:50:00'"""
    if not s:
        return ""
    s = str(s)
    if len(s) == 4:
        return f"{s[:2]}:{s[2:]}"
    if len(s) == 6:
        return f"{s[:2]}:{s[2:4]}:{s[4:]}"
    return s

def pretty_money(v):
    try:
        return f"{int(v):,}원"
    except:
        return v or ""

# =========================
# UI — 서비스/날짜/등급
# =========================
cols = st.columns([1.1, 1, 1])
with cols[0]:
    mode = st.radio("서비스", ["시외(Suburbs)", "고속(Express)"], horizontal=True)
    is_suburbs = mode.startswith("시외")
with cols[1]:
    pick_date = st.date_input("출발 날짜", value=date.today(), format="YYYY-MM-DD")
with cols[2]:
    bus_grade = st.selectbox("버스등급(옵션)", ["(전체)", "일반", "우등", "프리미엄", "심야"], index=0)

st.divider()
st.subheader("① 터미널 검색")

# =========================
# 출발/도착 터미널 검색
# =========================
left, right = st.columns(2)

with left:
    dep_kw = st.text_input("출발 터미널명", value="광주")
    if st.button("출발지 검색", use_container_width=True):
        base = BASE + (SERVICE_PATH_SUBURBS if is_suburbs else SERVICE_PATH_EXPRESS)
        op   = OP_SUB_TERMINALS if is_suburbs else OP_EXP_TERMINALS
        url  = f"{base}/{op}"
        # 먼저 리디렉트 여부 점검
        data = api_get_json(url, {"pageNo":1, "numOfRows":500, "terminalNm":dep_kw}, allow_redirects=False)
        st.write("응답 상위 키:", list(data.keys()))
        items = normalize_items(data)
        dep_df = pd.DataFrame(items)
        st.session_state["dep_df"] = dep_df
        if dep_df.empty:
            st.warning("결과가 비어있습니다. (엔드포인트/파라미터/리디렉트/키 문제 가능)")
        else:
            st.dataframe(dep_df, use_container_width=True, height=260)

with right:
    arr_kw = st.text_input("도착 터미널명", value="해남")
    if st.button("도착지 검색", use_container_width=True):
        base = BASE + (SERVICE_PATH_SUBURBS if is_suburbs else SERVICE_PATH_EXPRESS)
        op   = OP_SUB_TERMINALS if is_suburbs else OP_EXP_TERMINALS
        url  = f"{base}/{op}"
        data = api_get_json(url, {"pageNo":1, "numOfRows":500, "terminalNm":arr_kw}, allow_redirects=False)
        st.write("응답 상위 키:", list(data.keys()))
        items = normalize_items(data)

