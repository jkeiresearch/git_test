# app.py
import io
import re
from datetime import date, datetime
from typing import List, Dict, Any

import pandas as pd
import streamlit as st

# ===== Utils =====
def I(n: Any) -> int:
    try:
        x = float(n)
    except Exception:
        return 0
    if x != x:  # NaN
        return 0
    return int(round(x))

def W(n: Any) -> str:
    n = 0 if n is None else int(round(float(n)))
    return f"{n:,}원"

def day_inc(s: str, e: str) -> int:
    if not s or not e:
        return 0
    try:
        sd = datetime.strptime(s, "%Y-%m-%d").date()
        ed = datetime.strptime(e, "%Y-%m-%d").date()
    except Exception:
        return 0
    if ed < sd:
        return 0
    return (ed - sd).days + 1  # 동일 날짜도 1일

def per_diem_edu(mode: str, d: int, p: int) -> int:
    F = p
    H = round(p / 2)
    if d <= 0:
        return 0
    if mode == "none":
        return I(d * F)
    if mode == "dorm":  # 입소: 첫/마지막만 전액
        return I(F if d == 1 else 2 * F)
    # commute: 첫/마지막 전액, 중간 절반
    if d == 1:
        return I(F)
    if d == 2:
        return I(2 * F)
    return I(2 * F + (d - 2) * H)

def dedu_shared(days: int, p: int, d: int) -> int:
    H = round(p / 2)
    use_days = max(0, min(I(days), max(0, d)))
    return I(H * use_days)

def dedu_meal(m: int, per: int, unit: int) -> int:
    m = max(0, I(m))
    block = m // 3
    rem = m % 3
    return I(block * per + rem * unit)

# CSV: 허용 형식 route,cost  (cost는 45000 또는 45,000 모두 허용)
def parse_routes_csv(text: str) -> List[Dict[str, Any]]:
    lines = [l.strip() for l in re.split(r"\r?\n", text) if l.strip()]
    out = []
    for i, line in enumerate(lines):
        cols = [c.strip() for c in line.split(",")]
        if i == 0 and re.search(r"route", cols[0] if cols else "", re.I) and \
           re.search(r"(cost|금액)", (cols[1] if len(cols) > 1 else ""), re.I):
            continue  # 헤더 스킵
        if len(cols) >= 2:
            route = cols[0]
            raw_cost = "".join(cols[1:])  # "45,000" → "45000"
            cost_str = re.sub(r"[^0-9\.-]", "", raw_cost or "")
            cost = int(float(cost_str)) if cost_str else 0
            if route:
                out.append({"route": route, "cost": cost})
    return out

def csv_escape_cell(v: Any) -> str:
    s = "" if v is None else str(v)
    if re.search(r"[\",\r\n]", s):
        s = '"' + s.replace('"', '""') + '"'
    return s

def to_csv(rows: List[List[Any]]) -> str:
    return "\n".join([",".join(csv_escape_cell(c) for c in r) for r in rows])

# ===== Streamlit App =====
st.set_page_config(page_title="출장비 계산기 (Python)", layout="wide")
st.title("출장비 계산기 (Python)")

# --- Session State (defaults) ---
if "per_diem" not in st.session_state:
    st.session_state.per_diem = 25000
    st.session_state.meal_per_day = 25000
    st.session_state.meal_unit = 8330
    st.session_state.start_date = ""
    st.session_state.end_date = ""
    st.session_state.edu_mode = "none"
    st.session_state.shared_days = 0
    st.session_state.meals = 0
    st.session_state.routes = [
        {"route": "광주-서울", "cost": 45000},
        {"route": "서울-광주", "cost": 45000},
        {"route": "광주-대전", "cost": 21000},
    ]
    st.session_state.legs = [{"route": "광주-서울", "qty": 1}]
    st.session_state.lodgings = []  # {"date": "YYYY-MM-DD", "amount": 0}
    st.session_state.rows = []
    st.session_state.seq = 1

# --- Inputs ---
with st.container():
    st.subheader("기본 설정")
    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        sd = st.date_input("시작일", value=date.today() if not st.session_state.start_date else datetime.strptime(st.session_state.start_date, "%Y-%m-%d"))
        st.session_state.start_date = sd.strftime("%Y-%m-%d")
    with c2:
        ed = st.date_input("종료일", value=date.today() if not st.session_state.end_date else datetime.strptime(st.session_state.end_date, "%Y-%m-%d"))
        st.session_state.end_date = ed.strftime("%Y-%m-%d")
    with c3:
        st.number_input("일비(원)", value=st.session_state.per_diem, step=1000, key="per_diem")
    with c4:
        st.selectbox("교육/훈련 기준", ["none", "dorm", "commute"], format_func=lambda x: {"none":"일반","dorm":"입소","commute":"통학"}[x], key="edu_mode")

    cc1, cc2, cc3 = st.columns([1,1,1])
    with cc1:
        st.number_input("식비/일(원)", value=st.session_state.meal_per_day, step=1000, key="meal_per_day")
    with cc2:
        st.number_input("1식 감액(원)", value=st.session_state.meal_unit, step=10, key="meal_unit")
    with cc3:
        st.markdown(f"**총 일수:** {day_inc(st.session_state.start_date, st.session_state.end_date)}일")

# --- Transport Routes (Data Editor + CSV upload) ---
st.subheader("교통비 노선표")
u1, u2 = st.columns([2,1])
with u1:
    st.caption("CSV 형식: `route,cost` / 예: `광주-서울,45000` (헤더 허용)")
with u2:
    up = st.file_uploader("노선표 CSV 업로드", type=["csv"])
    if up is not None:
        text = up.read().decode("utf-8", errors="ignore")
        parsed = parse_routes_csv(text)
        if parsed:
            st.session_state.routes = parsed
        else:
            st.warning("CSV에서 유효한 노선을 찾지 못했습니다.")

routes_df = pd.DataFrame(st.session_state.routes)
routes_df = st.data_editor(routes_df, num_rows="dynamic", use_container_width=True, key="routes_df")
st.session_state.routes = routes_df.fillna({"route": "", "cost": 0}).to_dict(orient="records")

# --- Legs (journeys) ---
st.subheader("여정")
legs_df = pd.DataFrame(st.session_state.legs)
legs_df = st.data_editor(legs_df, num_rows="dynamic", use_container_width=True, key="legs_df")
st.session_state.legs = legs_df.fillna({"route": "", "qty": 0}).to_dict(orient="records")

# --- Lodgings ---
st.subheader("숙박비 (실비 입력)")
lodgings_df = pd.DataFrame(st.session_state.lodgings)
lodgings_df = st.data_editor(lodgings_df, num_rows="dynamic", use_container_width=True, key="lodgings_df")
st.session_state.lodgings = lodgings_df.fillna({"date": "", "amount": 0}).to_dict(orient="records")

# --- Calculations ---
D = day_inc(st.session_state.start_date, st.session_state.end_date)
route_map = {r["route"]: int(r.get("cost") or 0) for r in st.session_state.routes}
transport_total = I(sum((route_map.get(l["route"], 0) * int(l.get("qty") or 0)) for l in st.session_state.legs))
lodging_total = I(sum(int(x.get("amount") or 0) for x in st.session_state.lodgings))

base_per = I(D * st.session_state.per_diem)
per_after_edu = per_diem_edu(st.session_state.edu_mode, D, st.session_state.per_diem)
edu_ded = max(0, base_per - per_after_edu)
shared_ded = dedu_shared(st.session_state.shared_days, st.session_state.per_diem, D)
meal_gross = I(D * st.session_state.meal_per_day)
meal_ded = dedu_meal(st.session_state.meals, st.session_state.meal_per_day, st.session_state.meal_unit)

per_net = max(0, per_after_edu - shared_ded)
meal_net = max(0, meal_gross - meal_ded)

total_ded = I(edu_ded + shared_ded + meal_ded)
grand = I(transport_total + lodging_total + per_net + meal_net)

# --- Deductions inputs ---
st.subheader("감액 기준")
dd1, dd2 = st.columns([1,1])
with dd1:
    st.number_input("공용차량 이용일수", min_value=0, value=st.session_state.shared_days, key="shared_days", step=1, help="하루당 일비 절반 감액")
with dd2:
    st.number_input("식사 제공 횟수(총)", min_value=0, value=st.session_state.meals, key="meals", step=1, help="3식=하루분(식비/일), 나머지는 1식당 8,330원")

# --- Summary ---
st.subheader("계산 결과")
c_left, c_right = st.columns(2)
with c_left:
    st.markdown("**일비**")
    st.write(f"- 감액 전(일반): {W(base_per)}")
    if st.session_state.edu_mode != "none":
        st.write(f"- 교육 규칙 감액: - {W(edu_ded)}")
    st.write(f"- 교육 적용 후: {W(per_after_edu)}")
    st.write(f"- 공용차량 감액: - {W(shared_ded)}")
    st.write(f"- 일비(순액): **{W(per_net)}**")
with c_right:
    st.markdown("**식비**")
    st.write(f"- 감액 전: {W(meal_gross)}")
    st.write(f"- 식사 제공 감액: - {W(meal_ded)}")
    st.write(f"- 식비(순액): **{W(meal_net)}**")

c2_left, c2_right = st.columns(2)
with c2_left:
    st.markdown("**교통비**")
    st.write(f"합계: **{W(transport_total)}**")
with c2_right:
    st.markdown("**숙박비**")
    st.write(f"합계: **{W(lodging_total)}**")

st.info(f"총 감액: **{W(total_ded)}**  |  지급 예상: **{W(grand)}**")

# --- Save & Reset (accumulate rows) ---
def save_current():
    if D <= 0:
        st.warning("유효한 기간을 입력하세요.")
        return
    seq = st.session_state.seq
    row = {
        "No": seq,
        "일자": f"{st.session_state.start_date}~{st.session_state.end_date} ({D}일)",
        "일비(순액)": W(per_net),
        "식비(순액)": W(meal_net),
        "교통비": W(transport_total),
        "숙박비": W(lodging_total),
        "총 감액": W(total_ded),
        "지급예상금액": W(grand),
    }
    st.session_state.rows.append(row)
    st.session_state.seq += 1
    # 입력 초기화 (노선표는 유지)
    st.session_state.start_date = ""
    st.session_state.end_date = ""
    st.session_state.edu_mode = "none"
    st.session_state.shared_days = 0
    st.session_state.meals = 0
    st.session_state.legs = [{"route": st.session_state.routes[0]["route"] if st.session_state.routes else "", "qty": 1}]
    st.session_state.lodgings = []

st.button("계산 결과 저장", on_click=save_current, type="primary")

# --- Saved table + CSV download ---
st.subheader("저장된 계산 내역")
rows_df = pd.DataFrame(st.session_state.rows)
if rows_df.empty:
    st.caption("저장된 계산이 없습니다.")
else:
    st.dataframe(rows_df, use_container_width=True)

# CSV 다운로드 (보이는 형식 그대로, BOM 포함)
header = ["No","일자","일비(순액)","식비(순액)","교통비","숙박비","총 감액","지급예상금액"]
body = [[r.get(h, "") for h in header] for r in st.session_state.rows]
csv_text = "\ufeff" + to_csv([header] + body)
st.download_button(
    "CSV 다운로드",
    data=csv_text.encode("utf-8"),
    file_name="출장비_계산_테이블.csv",
    mime="text/csv;charset=utf-8"
)

# ===== Built-in Tests (kept & expanded) =====
with st.expander("내장 테스트 실행"):
    if st.button("Run tests"):
        results = []
        def eq(name, got, exp):
            results.append(("✅" if got == exp else "❌") + f" {name}: got={got} expected={exp}")

        # 날짜 계산
        eq("Day same day", day_inc("2025-09-10", "2025-09-10"), 1)
        eq("Day next day", day_inc("2025-09-10", "2025-09-11"), 2)

        # 일비 규칙
        eq("Edu none 3d", per_diem_edu("none", 3, 25000), 75000)
        eq("Edu dorm 3d", per_diem_edu("dorm", 3, 25000), 50000)
        eq("Edu commute 3d", per_diem_edu("commute", 3, 25000), 2*25000 + round(25000/2))

        # 식비 감액
        eq("Meal 5식", dedu_meal(5, 25000, 8330), 25000 + 16660)

        # CSV 파싱 (개행/헤더/천단위 콤마)
        eq("CSV newline split", len(parse_routes_csv("route,cost\n광주-서울,45000")), 1)
        parsed = parse_routes_csv("route,cost\n광주-서울,45,000\n서울-광주,45000")
        eq("CSV thousands handled - first", parsed[0]["cost"], 45000)

        # CSV 생성(인용/개행/쉼표)
        sample_csv = to_csv([["No","메모"], [1, "줄\n바꿈"], [2, "쉼표,포함"]])
        eq("CSV quote newline", bool(re.search(r"\"줄\n바꿈\"", sample_csv)), True)
        eq("CSV quote comma", bool(re.search(r"\"쉼표,포함\"", sample_csv)), True)

        # BOM
        with_bom = "\ufeff" + sample_csv
        eq("CSV BOM prefix", ord(with_bom[0]), 0xFEFF)

        st.write("\n".join(results))
