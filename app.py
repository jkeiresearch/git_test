# ====== 팝업(팝오버/모달) 터미널 피커 ======
import streamlit as st
import pandas as pd
import requests, certifi
from urllib.parse import urlencode
import os, re

BASE = "https://apis.data.go.kr"

# 서비스 경로/오퍼레이션 (질문자 샘플에 맞춤)
SERVICE_PATH_SUBURBS = "/1613000/SuburbsBusInfoService"
OP_SUB_TERMINALS = "getSuberbsBusTrminlList"         # 시외 터미널 목록
OP_SUB_ALLOC     = "getStrtpntAlocFndSuberbsInfo"    # 시외 배차(참고)

SERVICE_PATH_EXPRESS = "/1613000/ExpBusInfoService"
OP_EXP_TERMINALS = "getExpBusTrminlList"             # 고속 터미널 목록
OP_EXP_ALLOC     = "getStrtpntAlocFndExpbusInfo"     # 고속 배차(참고)

# 두 개 API 키 (secrets 사용 권장)
SUBURBS_API_KEY = st.secrets.get("SUBURBS_API_KEY", os.getenv("SUBURBS_API_KEY", ""))
EXPRESS_API_KEY = st.secrets.get("EXPRESS_API_KEY", os.getenv("EXPRESS_API_KEY", ""))

def _mask(url: str, key: str) -> str:
    return url.replace(key, "***")

def call_api(base_path, op, params, api_key):
    url = f"{BASE}{base_path}/{op}"
    q = {**params, "serviceKey": api_key, "_type": "json"}
    full = f"{url}?{urlencode(q)}"
    # 디버그: 키 마스킹된 URL 출력
    st.caption("요청: " + _mask(full, api_key))
    r = requests.get(full, timeout=15, verify=certifi.where())
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}

def parse_items(payload):
    try:
        items = payload["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        return items
    except Exception:
        return []

def terminal_picker(mode_key: str, title: str, button_label: str, state_key_out: str):
    """
    mode_key: "suburbs" | "express"
    title: 팝업 제목
    button_label: 버튼 문구 (예: '출발 터미널 찾기')
    state_key_out: 선택 ID를 저장할 세션 키 (예: 'dep_id' 또는 'arr_id')
    """

    # ---- 팝오버(신버전) 있으면 사용 ----
    has_popover = hasattr(st, "popover")

    if has_popover:
        with st.popover(button_label, use_container_width=True):
            st.markdown(f"#### {title}")
            # 검색 입력
            kw = st.text_input("터미널명 (예: 광주, 동서울, 해남 등)", key=f"{state_key_out}_kw", value="")
            city = st.text_input("도시코드 (선택)", key=f"{state_key_out}_city", value="")
            col1, col2 = st.columns([1,1])
            with col1:
                page = st.number_input("pageNo", min_value=1, value=1, step=1, key=f"{state_key_out}_page")
            with col2:
                rows = st.number_input("numOfRows", min_value=10, max_value=1000, value=200, step=10, key=f"{state_key_out}_rows")

            if st.button("검색", use_container_width=True, key=f"{state_key_out}_search"):
                base_path = SERVICE_PATH_SUBURBS if mode_key=="suburbs" else SERVICE_PATH_EXPRESS
                op        = OP_SUB_TERMINALS if mode_key=="suburbs" else OP_EXP_TERMINALS
                api_key   = SUBURBS_API_KEY if mode_key=="suburbs" else EXPRESS_API_KEY
                if not api_key:
                    st.error("해당 서비스의 API 키가 설정되지 않았습니다.")
                else:
                    params = {"pageNo": page, "numOfRows": rows}
                    if kw:   params["terminalNm"] = kw
                    if city: params["cityCode"]   = city
                    data = call_api(base_path, op, params, api_key)
                    items = parse_items(data)
                    df = pd.DataFrame(items)

                    if df.empty:
                        st.warning("검색 결과가 없습니다.")
                    else:
                        # 가장 가능성 높은 컬럼 정리
                        id_col = None
                        name_col = None
                        city_col = None
                        for c in df.columns:
                            cl = c.lower()
                            if cl in ("terminalid","terminal_id","terminalcd","terminalcode"):
                                id_col = c
                            if cl in ("terminalnm","terminalname","terminal_nm"):
                                name_col = c
                            if cl in ("citycode","city_cd","citycodevalue"):
                                city_col = c

                        # 표시용 테이블(읽기 전용)
                        show = df.copy()
                        st.dataframe(show, use_container_width=True, height=300)

                        # 선택 위젯
                        if id_col:
                            choices = [f"{r[id_col]} · {r.get(name_col,'')}" for _, r in df.iterrows()]
                            pick = st.selectbox("선택", choices, key=f"{state_key_out}_pick")
                            # ID만 추출
                            sel_id = pick.split("·")[0].strip()
                            if st.button("이 터미널 사용", type="primary", key=f"{state_key_out}_use"):
                                st.session_state[state_key_out] = sel_id
                                st.success(f"선택됨: {sel_id}")
                        else:
                            st.info("ID 컬럼을 찾지 못했습니다. 응답 스키마를 확인하세요.")
    else:
        # ---- 구버전 폴백: CSS 오버레이 모달 ----
        key_flag = f"show_modal_{state_key_out}"
        if st.button(button_label, use_container_width=True, key=f"{state_key_out}_open"):
            st.session_state[key_flag] = True

        if st.session_state.get(key_flag):
            # 오버레이 스타일
            st.markdown("""
            <style>
            ._overlay {
                position: fixed; inset: 0; background: rgba(0,0,0,0.35);
                display: flex; align-items: center; justify-content: center; z-index: 9999;
            }
            ._modal {
                width: min(900px, 95vw); max-height: 85vh; overflow: auto;
                background: white; padding: 1.25rem; border-radius: 12px;
                box-shadow: 0 10px 30px rgba(0,0,0,.2);
            }
            </style>
            """, unsafe_allow_html=True)
            # 컨테이너
            with st.container():
                st.markdown('<div class="_overlay"><div class="_modal">', unsafe_allow_html=True)
                st.markdown(f"#### {title}")

                kw = st.text_input("터미널명 (예: 광주, 동서울, 해남 등)", key=f"{state_key_out}_kw_fb", value="")
                city = st.text_input("도시코드 (선택)", key=f"{state_key_out}_city_fb", value="")
                col1, col2 = st.columns([1,1])
                with col1:
                    page = st.number_input("pageNo", min_value=1, value=1, step=1, key=f"{state_key_out}_page_fb")
                with col2:
                    rows = st.number_input("numOfRows", min_value=10, max_value=1000, value=200, step=10, key=f"{state_key_out}_rows_fb")

                if st.button("검색", use_container_width=True, key=f"{state_key_out}_search_fb"):
                    base_path = SERVICE_PATH_SUBURBS if mode_key=="suburbs" else SERVICE_PATH_EXPRESS
                    op        = OP_SUB_TERMINALS if mode_key=="suburbs" else OP_EXP_TERMINALS
                    api_key   = SUBURBS_API_KEY if mode_key=="suburbs" else EXPRESS_API_KEY
                    if not api_key:
                        st.error("해당 서비스의 API 키가 설정되지 않았습니다.")
                    else:
                        params = {"pageNo": page, "numOfRows": rows}
                        if kw:   params["terminalNm"] = kw
                        if city: params["cityCode"]   = city
                        data = call_api(base_path, op, params, api_key)
                        items = parse_items(data)
                        df = pd.DataFrame(items)

                        if df.empty:
                            st.warning("검색 결과가 없습니다.")
                        else:
                            id_col = None
                            name_col = None
                            for c in df.columns:
                                cl = c.lower()
                                if cl in ("terminalid","terminal_id","terminalcd","terminalcode"):
                                    id_col = c
                                if cl in ("terminalnm","terminalname","terminal_nm"):
                                    name_col = c
                            st.dataframe(df, use_container_width=True, height=300)
                            if id_col:
                                choices = [f"{r[id_col]} · {r.get(name_col,'')}" for _, r in df.iterrows()]
                                pick = st.selectbox("선택", choices, key=f"{state_key_out}_pick_fb")
                                sel_id = pick.split("·")[0].strip()
                                if st.button("이 터미널 사용", type="primary", key=f"{state_key_out}_use_fb"):
                                    st.session_state[state_key_out] = sel_id
                                    st.session_state[key_flag] = False
                                    st.success(f"선택됨: {sel_id}")
                            else:
                                st.info("ID 컬럼을 찾지 못했습니다. 응답 스키마를 확인하세요.")

                if st.button("닫기", key=f"{state_key_out}_close"):
                    st.session_state[key_flag] = False

                st.markdown('</div></div>', unsafe_allow_html=True)
# ====== /팝업 ======
