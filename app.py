# ==== 터미널 리스트 '팝업' (st.dialog 우선, 미지원시 expander 폴백) ====
import os, requests, certifi
import streamlit as st
import pandas as pd
from urllib.parse import urlencode, unquote

BASE = "https://apis.data.go.kr"

# 질문자 샘플과 동일하게 맞춤
SERVICE_PATH_SUBURBS = "/1613000/SuburbsBusInfoService"
OP_SUB_TERMINALS     = "getSuberbsBusTrminlList"      # 시외 터미널 목록
OP_SUB_ALLOC         = "getStrtpntAlocFndSuberbsInfo" # 시외 배차(참고)

SERVICE_PATH_EXPRESS = "/1613000/ExpBusInfoService"
OP_EXP_TERMINALS     = "getExpBusTrminlList"          # 고속 터미널 목록
OP_EXP_ALLOC         = "getStrtpntAlocFndExpbusInfo"  # 고속 배차(참고)

# 두 개 API 키 (Streamlit secrets 권장)
SUBURBS_API_KEY = st.secrets.get("SUBURBS_API_KEY", os.getenv("SUBURBS_API_KEY", ""))
EXPRESS_API_KEY = st.secrets.get("EXPRESS_API_KEY", os.getenv("EXPRESS_API_KEY", ""))

def _mask(url: str, key: str) -> str:
    if not key:
        return url
    return url.replace(key, "***")

def call_api_json(base_path: str, op: str, params: dict, api_key: str):
    """
    • JSON 우선 요청
    • URL / 상태 / resultCode 진단 출력
    • JSON 파싱 실패 시 raw 반환
    """
    if not api_key:
        st.error("API 키가 설정되지 않았습니다.")
        return None

    # data.go.kr 키 특성상, '디코딩된 키'가 필요할 때가 많음 → 시도
    api_key_use = api_key
    try:
        # 이미 디코딩된 키라면 unquote 해도 동일
        api_key_decoded = unquote(api_key)
        api_key_use = api_key_decoded or api_key
    except Exception:
        pass

    url = f"{BASE}{base_path}/{op}"
    q = {**params, "serviceKey": api_key_use, "_type": "json"}
    full = f"{url}?{urlencode(q)}"

    st.caption("요청(URL, 키 마스킹): " + _mask(full, api_key_use))
    try:
        r = requests.get(full, timeout=15, verify=certifi.where(), allow_redirects=False)
        st.write("HTTP 상태:", r.status_code)
        if 300 <= r.status_code < 400:
            st.warning("리디렉트 감지: " + str(r.headers.get("Location")))
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        st.error("SSL 오류 발생. (https 도메인/인증서/시간 동기화 점검 필요)")
        st.exception(e)
        return None
    except requests.exceptions.RequestException as e:
        st.error("네트워크/HTTP 오류")
        st.exception(e)
        return None

    # JSON 파싱
    try:
        data = r.json()
    except Exception:
        st.warning("JSON 파싱 실패. raw 응답 상단을 표시합니다.")
        st.code(r.text[:1000])
        return None

    # data.go.kr 표준 응답 진단(resultCode)
    try:
        rc = data["response"]["header"]["resultCode"]
        rm = data["response"]["header"].get("resultMsg", "")
        st.write("resultCode:", rc, "| resultMsg:", rm)
        if str(rc) != "00":
            st.error(f"API 오류(resultCode={rc}): {rm}")
    except Exception:
        st.info("표준 헤더를 확인할 수 없습니다. 응답 구조가 다른지 점검 필요.")

    return data

def parse_items(payload):
    try:
        items = payload["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            return [items]
        return items or []
    except Exception:
        return []

def show_terminal_picker(mode_key: str, state_key_out: str, title: str = "터미널 선택"):
    """
    mode_key: "suburbs" | "express" (시외/고속)
    state_key_out: 선택된 터미널 ID를 저장할 세션키 (예: 'dep_id' or 'arr_id')
    """
    def _ui_body():
        st.markdown(f"### {title}")
        c1, c2 = st.columns(2)
        with c1:
            kw = st.text_input("터미널명 (예: 광주, 동서울, 해남)", key=f"{state_key_out}_kw", value="")
        with c2:
            city = st.text_input("도시코드(선택)", key=f"{state_key_out}_city", value="")

        colp1, colp2 = st.columns(2)
        with colp1:
            page = st.number_input("pageNo", min_value=1, value=1, step=1, key=f"{state_key_out}_page")
        with colp2:
            rows = st.number_input("numOfRows", min_value=10, max_value=1000, value=200, step=10, key=f"{state_key_out}_rows")

        if st.button("검색", use_container_width=True, key=f"{state_key_out}_search"):
            base_path = SERVICE_PATH_SUBURBS if mode_key == "suburbs" else SERVICE_PATH_EXPRESS
            op        = OP_SUB_TERMINALS    if mode_key == "suburbs" else OP_EXP_TERMINALS
            api_key   = SUBURBS_API_KEY     if mode_key == "suburbs" else EXPRESS_API_KEY

            params = {"pageNo": page, "numOfRows": rows}
            if kw:   params["terminalNm"] = kw
            if city: params["cityCode"]   = city

            data = call_api_json(base_path, op, params, api_key)
            if not data:
                return

            items = parse_items(data)
            df = pd.DataFrame(items)
            if df.empty:
                st.warning("검색 결과가 비어 있습니다.")
                return

            st.dataframe(df, use_container_width=True, height=320)

            # 가장 가능성 높은 컬럼 추정
            id_col = None
            name_col = None
            for c in df.columns:
                cl = c.lower()
                if cl in ("terminalid", "terminal_id", "terminalcd", "terminalcode"):
                    id_col = c
                if cl in ("terminalnm", "terminalname", "terminal_nm"):
                    name_col = c

            if not id_col:
                st.info("ID 컬럼을 찾지 못했습니다. 응답 스키마를 확인하세요.")
                return

            opts = [f"{r[id_col]} · {r.get(name_col,'')}" for _, r in df.iterrows()]
            pick = st.selectbox("선택", opts, key=f"{state_key_out}_pick")

            sel_id = pick.split("·")[0].strip()
            if st.button("이 터미널 사용", type="primary", key=f"{state_key_out}_use"):
                st.session_state[state_key_out] = sel_id
                st.success(f"선택됨: {sel_id}")

    # st.dialog가 있으면 팝업, 없으면 expander
    if hasattr(st, "dialog"):
        # 버튼을 눌러 모달 열기
        if st.button("터미널 리스트(팝업) 열기", key=f"{state_key_out}_open", use_container_width=True):
            @st.dialog(title)
            def _dlg():
                _ui_body()
            _dlg()
    else:
        with st.expander("터미널 리스트 열기 (팝업 대체: expander)"):
            _ui_body()

# ===== 사용 예시 =====
# 시외 터미널 선택(출발/도착)
st.subheader("시외버스 터미널 선택")
show_terminal_picker(mode_key="suburbs", state_key_out="dep_id", title="출발 터미널 선택(시외)")
show_terminal_picker(mode_key="suburbs", state_key_out="arr_id", title="도착 터미널 선택(시외)")

st.write("현재 선택된 출발ID:", st.session_state.get("dep_id", ""))
st.write("현재 선택된 도착ID:", st.session_state.get("arr_id", ""))

# (원하면) 고속 모드도 동일하게 호출
# st.subheader("고속버스 터미널 선택")
# show_terminal_picker(mode_key="express", state_key_out="dep_id_exp", title="출발 터미널 선택(고속)")
# show_terminal_picker(mode_key="express", state_key_out="arr_id_exp", title="도착 터미널 선택(고속)")
# st.write("고속 출발ID:", st.session_state.get("dep_id_exp", ""))
# st.write("고속 도착ID:", st.session_state.get("arr_id_exp", ""))
# ==== /터미널 팝업 ====
