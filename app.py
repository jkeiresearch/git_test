# app.py
import os
import json
import time
import math
from datetime import datetime, date
from urllib.parse import urlencode
import requests
import pandas as pd
import streamlit as st

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="시외/고속버스 시간표 & 요금", page_icon="🚌", layout="wide")

# API 키 (Streamlit Cloud/로컬 secrets 사용 권장)
# .streamlit/secrets.toml 에 다음처럼 저장:
# DATA_GO_KR_KEY = "발급받은_디코딩전_서비스키"
API_KEY = st.secrets.get("DATA_GO_KR_KEY", os.getenv("DATA_GO_KR_KEY", ""))

KST = "Asia/Seoul"

# TAGO 베이스URL 및 엔드포인트(필요시 교체)
BASE = "https://apis.data.go.kr"
# TAGO 서비스군은 보통 /1613000/ 하위에 있음. (기관이 공지로 이전 고시한 바 있음)
# 정확한 path/op 명은 data.go.kr의 각 서비스 '활용가이드' 탭을 확인해 업데이트할 것.  :contentReference[oaicite:3]{index=3}
SERVICES = {
    "suburbs": {  # 시외버스
        "base": f"{BASE}/1613000/SuburbsBusInfoService",
        "ops": {
            # 터미널 목록 (이름, 도시코드 등으로 필터) - 문서의 실제 op명을 확인해 반영
            "terminals": "getSuberbsBusTrminlList",
            # 출/도착지 기반 운행(배차) 정보 - 문서 실제 op명 확인
            "alloc": "getStrtpntAlocFndSuberbsInfo",
        },
        "note": "시외버스(당일 배차 중심)"
    },
    "express": {   # 고속버스
        "base": f"{BASE}/1613000/ExpBusInfoService",
        "ops": {
            "terminals": "getExpBusTrminlList",
            "alloc": "getStrtpntAlocFndExpbusInfo",  # 문서에 예시로 자주 등장하는 오퍼레이션명
        },
        "note": "고속버스"
    }
}

# =========================
# 공용 유틸
# =========================
def api_get(url: str, params: dict, parse_json=True):
    """공공데이터포털 표준 params로 호출."""
    q = params.copy()
    # data.go.kr는 serviceKey 파라미터명 고정. (일부 API는 'serviceKey'만 요구)
    q["serviceKey"] = API_KEY
    # JSON 응답 원할 때
    if "_type" not in q:
        q["_type"] = "json"

    full = f"{url}?{urlencode(q, doseq=True)}"
    r = requests.get(full, timeout=20)
    r.raise_for_status()
    if not parse_json:
        return r.text
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def to_time_str(kst_hm: str):
    """예: '0550' → '05:50' 또는 '055000' → '05:50:00' 형태 정리."""
    s = str(kst_hm)
    if len(s) == 4:
        return f"{s[:2]}:{s[2:]}"
    if len(s) == 6:
        return f"{s[:2]}:{s[2:4]}:{s[4:]}"
    return s


def pretty_money(v):
    try:
        return f"{int(v):,}원"
    except:
        return v


@st.cache_data(ttl=60 * 60)
def fetch_terminals(service_key: str, mode="suburbs", name=None, cityCode=None, pageNo=1, numOfRows=500):
    """터미널 목록 가져오기 (시외/고속). name으로 부분검색 지원."""
    svc = SERVICES[mode]
    url = f"{svc['base']}/{svc['ops']['terminals']}"
    params = {
        "pageNo": pageNo,
        "numOfRows": numOfRows,
    }
    if name:
        # 실제 파라미터명은 API 가이드에서 확인 (terminalNm 등)
        params["terminalNm"] = name
    if cityCode:
        params["cityCode"] = cityCode

    data = api_get(url, params)
    # 응답 표준 형태에 맞춰 파싱 (response > body > items > item)
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
    except Exception:
        items = []
    df = pd.DataFrame(items)
    return df


@st.cache_data(ttl=60)  # 배차는 당일기준 변동 가능 → 캐시 짧게
def fetch_allocations(service_key: str, mode="suburbs", depTerminalId=None, arrTerminalId=None, depPlandDate=None, busGradeId=None, pageNo=1, numOfRows=500):
    """출/도착 터미널 ID + 날짜(YYYYMMDD) 기준 배차/요금/등급."""
    svc = SERVICES[mode]
    url = f"{svc['base']}/{svc['ops']['alloc']}"
    params = {
        "pageNo": pageNo,
        "numOfRows": numOfRows,
    }
    # 실제 요구 파라미터명은 API 가이드 확인 필요
    # 일반적으로: depTerminalId, arrTerminalId, depPlandTime(YYYYMMDD), busGradeId 등을 사용
    if depTerminalId:
        params["depTerminalId"] = depTerminalId
    if arrTerminalId:
        params["arrTerminalId"] = arrTerminalId
    if depPlandDate:
        # 일부 API는 depPlandTime(YYYYMMDD) 사용. 둘 다 넣어 호환
        params["depPlandDate"] = depPlandDate
        params["depPlandTime"] = depPlandDate
    if busGradeId:
        params["busGradeId"] = busGradeId

    data = api_get(url, params)
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
    except Exception:
        items = []

    # 필드 정규화 (API 스펙에 따라 필드명이 다를 수 있어, 안전하게 존재여부 체크)
    norm = []
    for it in items:
        dep_time = it.get("depPlandTime") or it.get("depTime") or it.get("depTm") or ""
        arr_time = it.get("arrPlandTime") or it.get("arrTime") or it.get("arrTm") or ""
        grade_nm = it.get("gradeNm") or it.get("busGradeNm") or it.get("busClassName") or ""
        charge = it.get("charge") or it.get("adultCharge") or it.get("fare") or ""
        runtime = it.get("runTime") or it.get("duration") or ""
        norm.append({
            "출발시간": to_time_str(str(dep_time)[-6:] if dep_time else ""),
            "도착시간": to_time_str(str(arr_time)[-6:] if arr_time else ""),
            "버스등급": grade_nm,
            "예매요금": pretty_money(charge),
            "소요(분)": runtime
        })
    return pd.DataFrame(norm)


# =========================
# UI
# =========================
st.title("🚌 시외/고속버스 시간표 & 요금(국토부 TAGO)")
st.caption("국토교통부 오픈API 기반 · 당일 배차 중심 데이터 \n— 시외버스/고속버스 터미널 선택 → 시간표/요금 조회")

if not API_KEY:
    st.warning("⚠️ 먼저 data.go.kr에서 서비스키를 발급받아 `DATA_GO_KR_KEY` 로 설정해 주세요.")
    st.stop()

colm1, colm2, colm3 = st.columns([1.2, 1, 1])
with colm1:
    mode = st.radio("서비스", ["시외버스(Suburbs)", "고속버스(Express)"], horizontal=True)
    mode_key = "suburbs" if "시외" in mode else "express"
with colm2:
    pick_date = st.date_input("출발 날짜", value=date.today(), format="YYYY-MM-DD")
with colm3:
    bus_grade = st.selectbox("버스등급(선택)", ["(전체)","일반","우등","프리미엄","심야"], index=0)

st.divider()

# 터미널 검색 패널
st.subheader("① 터미널 선택")
tc1, tc2 = st.columns(2)
with tc1:
    st.write("출발 터미널 검색")
    dep_keyword = st.text_input("출발지 터미널명(예: 광주, 동서울, 해남 등)", value="광주")
    if st.button("출발지 검색", use_container_width=True):
        dep_df = fetch_terminals(API_KEY, mode=mode_key, name=dep_keyword)
        st.session_state["dep_list"] = dep_df

with tc2:
    st.write("도착 터미널 검색")
    arr_keyword = st.text_input("도착지 터미널명(예: 해남, 여수, 목포 등)", value="해남")
    if st.button("도착지 검색", use_container_width=True):
        arr_df = fetch_terminals(API_KEY, mode=mode_key, name=arr_keyword)
        st.session_state["arr_list"] = arr_df

def pick_terminal(label, key_df, key_pick):
    df = st.session_state.get(key_df)
    if df is not None and not df.empty:
        show = df.copy()
        # 표시 칼럼 가공 (터미널ID, 터미널명, 도시코드 등 추정 컬럼명)
        # 실제 스키마에 맞춰 아래 컬럼명을 조정할 것.
        cand_cols = [c for c in show.columns if c.lower() in ("terminalid","terminal_id","terminalcd","terminalcode","terminalnm","citycode","cityname","citynm","termminalid")]
        # 그냥 다 보여주되, 눈에 잘 띄게 ID/이름 위주로 정렬
        st.dataframe(show, use_container_width=True, height=240)
        # 터미널 ID 추출 컬럼 추정
        id_col = None
        for c in show.columns:
            if c.lower() in ("terminalid","terminal_id","terminalcd","terminalcode"):
                id_col = c; break
        name_col = None
        for c in show.columns:
            if c.lower() in ("terminalnm","terminalname","terminal_nm","termminalnm"):
                name_col = c; break
        # 선택 위젯
        options = []
        if id_col and name_col:
            options = [f"{r[id_col]} · {r[name_col]}" for _, r in show.iterrows()]
        elif id_col:
            options = [str(r[id_col]) for _, r in show.iterrows()]
        else:
            options = [str(i) for i in range(len(show))]
        pick = st.selectbox(label, options)
        # 선택값에서 터미널ID 복원
        term_id = None
        if id_col:
            if "·" in pick:
                term_id = pick.split("·")[0].strip()
            else:
                term_id = pick.strip()
        else:
            # id 컬럼을 못찾으면 행번호 기준
            idx = options.index(pick)
            term_id = str(show.iloc[idx].get("terminalId", show.iloc[idx].get("TERMINAL_ID","")))
        st.session_state[key_pick] = term_id
    else:
        st.info("위에서 검색 버튼을 눌러 목록을 불러오세요.")

lc1, lc2 = st.columns(2)
with lc1:
    pick_terminal("출발 터미널 선택", "dep_list", "dep_id")
with lc2:
    pick_terminal("도착 터미널 선택", "arr_list", "arr_id")

st.divider()

# 조회
st.subheader("② 시간표 / 요금 조회")
dep_id = st.session_state.get("dep_id")
arr_id = st.session_state.get("arr_id")

# 자주 쓰는 예시(광주 유·스퀘어, 해남) 기본값 제공
if not dep_id and dep_keyword == "광주":
    dep_id = "NAI6193701"
if not arr_id and arr_keyword == "해남":
    arr_id = "NAI5903801"

col_go1, col_go2, col_go3 = st.columns([1.2, 1, 1])
with col_go1:
    st.write(f"출발ID: `{dep_id or ''}`  →  도착ID: `{arr_id or ''}`")
with col_go2:
    dep_str = pick_date.strftime("%Y%m%d")
    st.write(f"조회일자: `{dep_str}`")
with col_go3:
    do_query = st.button("조회하기", type="primary", use_container_width=True)

if do_query:
    if not dep_id or not arr_id:
        st.error("출발/도착 터미널을 선택(또는 ID 입력)해주세요.")
        st.stop()

    df = fetch_allocations(API_KEY, mode=mode_key, depTerminalId=dep_id, arrTerminalId=arr_id, depPlandDate=dep_str)
    if df.empty:
        st.warning("조회 결과가 없습니다. (해당 날짜/노선에 배차가 없거나 API 응답이 없을 수 있어요)")
    else:
        # 버스등급 필터
        if bus_grade != "(전체)":
            df = df[df["버스등급"].fillna("").str.contains(bus_grade, na=False)]
        st.dataframe(df, use_container_width=True, height=min(600, 60 + 35 * max(1, len(df))))
        # CSV 저장
        st.download_button("CSV 다운로드", df.to_csv(index=False).encode("utf-8-sig"), file_name=f"bus_{mode_key}_{dep_id}_{arr_id}_{dep_str}.csv", mime="text/csv")

st.caption("※ 시외버스는 당일 배차 제공 중심이며, 일부 노선/등급/요금이 변동될 수 있습니다. 운영가이드 필드명에 맞춰 엔드포인트/파라미터를 업데이트하세요.")
