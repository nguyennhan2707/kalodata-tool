import time
import json
import altair as alt
import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="Săn Sản Phẩm Affiliate", layout="wide")

# Múi giờ Việt Nam (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

def now_vn() -> datetime:
    return datetime.now(VN_TZ)

# --- 1. HÀM CHUẨN HÓA SỐ & TIỀN VNĐ ---
INT_COLS = [
    "Đơn giá (VNĐ)", "Lượt bán", "Doanh thu Video", "Doanh thu Live",
    "Doanh thu Tủ trưng bày", "Tổng doanh thu", "Số NST", "Số Video",
    "Số đánh giá", "Số Video Ads", "Số Video AI"
]
FLOAT_COLS = ["Hoa hồng (%)", "Tăng trưởng (%)", "ROAS cao nhất"]

def parse_vn_num(val) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("₫", "").replace("đồng", "").replace("VNĐ", "").replace("%", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def to_int(val) -> int:
    return int(round(parse_vn_num(val)))

def fmt_vnd(val) -> str:
    return f"{to_int(val):,}".replace(",", ".") + " đồng"

def clean_numeric_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in INT_COLS:
        if col in df.columns:
            df[col] = df[col].apply(to_int)
    for col in FLOAT_COLS:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: round(parse_vn_num(x), 1))
    return df

# --- 2. KẾT NỐI GOOGLE SHEETS ---
@st.cache_resource
def get_spreadsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["SHEET_ID"])

def get_data_sheet():
    return get_spreadsheet().worksheet("Data")

def get_master_sheet():
    ss = get_spreadsheet()
    try:
        return ss.worksheet("MasterData")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="MasterData", rows=5000, cols=4)
        ws.append_row(["loai_du_lieu", "ma_id", "ten_hien_thi", "ma_cha"])
        return ws

DASHBOARD_HEADERS = [
    "Đợt chạy", "Ảnh SP", "Mã SP", "Tên sản phẩm", "Đơn giá (VNĐ)", "Hoa hồng (%)",
    "Lượt bán", "Doanh thu Video", "Tổng doanh thu", "Tăng trưởng (%)",
    "Số NST", "Số Video", "Số đánh giá", "Xu hướng doanh thu",
    "Ngành cấp 1", "Ngành cấp 2", "Tên Shop",
    "Có chạy Ads", "Số Video Ads", "ROAS cao nhất", "Có Video AI", "Số Video AI"
]

def get_dashboard_sheet():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet("Weekly_Dashboard")
        if not ws.get_all_values():
            ws.append_row(DASHBOARD_HEADERS)
        return ws
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="Weekly_Dashboard", rows=3000, cols=len(DASHBOARD_HEADERS))
        ws.append_row(DASHBOARD_HEADERS)
        return ws

# --- 3. ĐỒNG BỘ MASTER DATA & CACHE DỮ LIỆU ---
EXCLUDED_AUTO_FIELDS = {
    "product_id", "product_name", "master_image_url", "revenue", "commission_rate",
    "revenue_growth_rate", "sales_volumn", "unit_price", "live_revenue",
    "video_revenue", "showcase_revenue", "launch_date", "sku_count",
    "pri_category", "sec_category", "ter_category", "seller_id", "seller_name"
}

def extract_master_entries_from_api(items: list) -> list:
    entries = []
    for item in items:
        pri = item.get("pri_category") or {}
        sec = item.get("sec_category") or {}
        ter = item.get("ter_category") or {}

        c1_id, c1_name = str(pri.get("category_id", "")).strip(), str(pri.get("category_name", "")).strip()
        c2_id, c2_name = str(sec.get("category_id", "")).strip(), str(sec.get("category_name", "")).strip()
        c3_id, c3_name = str(ter.get("category_id", "")).strip(), str(ter.get("category_name", "")).strip()

        if c1_id and c1_name:
            entries.append(("nganh_cap_1", c1_id, c1_name, ""))
        if c2_id and c2_name:
            entries.append(("nganh_cap_2", c2_id, c2_name, c1_id))
        if c3_id and c3_name:
            entries.append(("nganh_cap_3", c3_id, c3_name, c2_id))

        s_id, s_name = str(item.get("seller_id", "")).strip(), str(item.get("seller_name", "")).strip()
        if s_id and s_name:
            entries.append(("shop", s_id, s_name, ""))

        for k, v in item.items():
            if k in EXCLUDED_AUTO_FIELDS or v is None:
                continue
            if isinstance(v, str) and v.strip():
                entries.append((k, v.strip(), v.strip(), ""))
            elif isinstance(v, dict):
                v_id = str(v.get("id", "") or v.get("code", "")).strip()
                v_name = str(v.get("name", "") or v_id).strip()
                if v_id:
                    entries.append((k, v_id, v_name, ""))
    return entries

def save_master_entries(entries: list) -> int:
    if not entries:
        return 0
    ws = get_master_sheet()
    existing = ws.get_all_records()
    existing_keys = {
        (str(r.get("loai_du_lieu", "")).strip(), str(r.get("ma_id", "")).strip(), str(r.get("ma_cha", "")).strip())
        for r in existing
    }
    new_rows, seen = [], set()
    for loai, ma_id, ten, ma_cha in entries:
        key = (loai, ma_id, ma_cha)
        if key not in existing_keys and key not in seen:
            seen.add(key)
            new_rows.append([loai, ma_id, ten, ma_cha])
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    return len(new_rows)

@st.cache_data(ttl=300)
def load_master_data() -> pd.DataFrame:
    ws = get_master_sheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=["loai_du_lieu", "ma_id", "ten_hien_thi", "ma_cha"])
    df_m = pd.DataFrame(records).astype(str)
    for col in df_m.columns:
        df_m[col] = df_m[col].str.strip()
    return df_m

@st.cache_data(ttl=120)
def load_dashboard_data() -> pd.DataFrame:
    ws = get_dashboard_sheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=DASHBOARD_HEADERS)
    return clean_numeric_df(pd.DataFrame(records))

# --- 4. CÁC HÀM GỌI API & XỬ LÝ DỮ LIỆU ---
def call_kalodata_api(endpoint: str, payload: dict):
    url = f"https://www.kalodata.com/openapi/v1/tiktok/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "secret-key": st.secrets["KALODATA_SECRET_KEY"]
    }
    res = requests.post(url, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()

def parse_trend_list(val) -> list:
    if isinstance(val, list):
        return [parse_vn_num(x) for x in val]
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [parse_vn_num(x) for x in parsed]
        except Exception:
            parts = [p.strip() for p in val.strip("[]").split(",") if p.strip()]
            return [parse_vn_num(p) for p in parts]
    return []

# --- POPUP HIỂN THỊ CHI TIẾT SẢN PHẨM KHI CLICK CỘT ---
@st.dialog("📦 Chi tiết sản phẩm", width="large")
def show_product_popup(row: pd.Series):
    col_img, col_info = st.columns([1, 2.3])
    with col_img:
        img_url = str(row.get("Ảnh SP", "")).strip()
        if img_url:
            st.image(img_url, use_container_width=True)
        else:
            st.caption("Không có ảnh")
        st.caption(f"**Mã SP:** `{row.get('Mã SP', '')}`")
        st.caption(f"**Shop:** {row.get('Tên Shop', '')}")
        st.caption(f"**Ngành:** {row.get('Ngành cấp 1', '')} > {row.get('Ngành cấp 2', '')}")

    with col_info:
        st.subheader(str(row.get("Tên sản phẩm", "")))
        m1, m2, m3 = st.columns(3)
        m1.metric("Đơn giá", fmt_vnd(row.get("Đơn giá (VNĐ)", 0)))
        m2.metric("Hoa hồng", f"{parse_vn_num(row.get('Hoa hồng (%)', 0)):.1f}%")
        m3.metric("Lượt bán", f"{to_int(row.get('Lượt bán', 0)):,}".replace(",", "."))

        m4, m5, m6 = st.columns(3)
        m4.metric("Doanh thu Video", fmt_vnd(row.get("Doanh thu Video", 0)))
        m5.metric("Tổng doanh thu", fmt_vnd(row.get("Tổng doanh thu", 0)))
        m6.metric("Tăng trưởng", f"{parse_vn_num(row.get('Tăng trưởng (%)', 0)):+.1f}%")

        m7, m8, m9 = st.columns(3)
        m7.metric("Số NST (Cạnh tranh)", f"{to_int(row.get('Số NST', 0)):,}".replace(",", "."))
        m8.metric("Số Video gắn SP", f"{to_int(row.get('Số Video', 0)):,}".replace(",", "."))
        m9.metric("Số đánh giá", f"{to_int(row.get('Số đánh giá', 0)):,}".replace(",", "."))

    st.markdown("---")
    c_ads, c_ai = st.columns(2)
    c_ads.info(
        f"**Quảng cáo (Ads):** {row.get('Có chạy Ads', 'Chưa check')} "
        f"| Số Video Ads: **{to_int(row.get('Số Video Ads', 0))}** "
        f"| ROAS cao nhất: **{parse_vn_num(row.get('ROAS cao nhất', 0)):.2f}**"
    )
    c_ai.info(
        f"**Video AI:** {row.get('Có Video AI', 'Chưa check')} "
        f"| Số Video AI đang ra đơn: **{to_int(row.get('Số Video AI', 0))}**"
    )

    trend_vals = row.get("Xu hướng doanh thu", [])
    if isinstance(trend_vals, list) and len(trend_vals) > 0:
        st.markdown("**📈 Biểu đồ xu hướng doanh thu theo ngày:**")
        df_t = pd.DataFrame({"Ngày": range(1, len(trend_vals) + 1), "Doanh thu": trend_vals})
        st.line_chart(df_t.set_index("Ngày"), height=200)

# --- 5. HÀM LỌC ĐỘNG THEO TỪNG CỘT ---
def filter_dataframe(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    df = df.copy()
    with st.expander("🔍 Bộ lọc chi tiết theo từng cột", expanded=False):
        filterable_cols = [c for c in df.columns if c not in ["Ảnh SP", "Xu hướng doanh thu"]]
        selected_cols = st.multiselect("Chọn các cột muốn lọc:", options=filterable_cols, key=f"{key_prefix}_cols")
        for col in selected_cols:
            numeric_series = pd.to_numeric(df[col], errors="coerce")
            is_numeric = (
                numeric_series.notna().sum() > 0
                and numeric_series.notna().sum() == df[col].replace("", pd.NA).notna().sum()
            )
            if is_numeric and col not in ["Mã SP", "Mã Shop", "Mã ngành cấp 1", "Mã ngành cấp 2", "Mã ngành cấp 3"]:
                _min, _max = float(numeric_series.min()), float(numeric_series.max())
                if _min < _max:
                    user_range = st.slider(
                        f"Khoảng giá trị cho [{col}]",
                        min_value=_min, max_value=_max, value=(_min, _max),
                        key=f"{key_prefix}_{col}"
                    )
                    df = df[numeric_series.between(user_range[0], user_range[1])]
            else:
                unique_vals = df[col].astype(str).unique().tolist()
                if len(unique_vals) <= 30:
                    chosen = st.multiselect(f"Chọn giá trị cho [{col}]", options=unique_vals, default=unique_vals, key=f"{key_prefix}_{col}")
                    df = df[df[col].astype(str).isin(chosen)]
                else:
                    search_text = st.text_input(f"Tìm kiếm từ khóa trong [{col}]", key=f"{key_prefix}_{col}")
                    if search_text.strip():
                        df = df[df[col].astype(str).str.contains(search_text.strip(), case=False, na=False)]
    return df

# --- CẤU HÌNH HIỂN THỊ CỘT (PHÂN CÁCH HÀNG NGHÌN, KHÔNG SỐ LẺ) ---
COLUMN_CONFIG = {
    "Ảnh SP": st.column_config.ImageColumn("Ảnh SP"),
    "Đơn giá (VNĐ)": st.column_config.NumberColumn("Đơn giá (VNĐ)", format="localized", step=1),
    "Lượt bán": st.column_config.NumberColumn("Lượt bán", format="localized", step=1),
    "Doanh thu Video": st.column_config.NumberColumn("Doanh thu Video (VNĐ)", format="localized", step=1),
    "Doanh thu Live": st.column_config.NumberColumn("Doanh thu Live (VNĐ)", format="localized", step=1),
    "Doanh thu Tủ trưng bày": st.column_config.NumberColumn("Doanh thu Tủ trưng bày (VNĐ)", format="localized", step=1),
    "Tổng doanh thu": st.column_config.NumberColumn("Tổng doanh thu (VNĐ)", format="localized", step=1),
    "Số NST": st.column_config.NumberColumn("Số NST", format="localized", step=1),
    "Số Video": st.column_config.NumberColumn("Số Video", format="localized", step=1),
    "Số đánh giá": st.column_config.NumberColumn("Số đánh giá", format="localized", step=1),
    "Hoa hồng (%)": st.column_config.NumberColumn(format="%.1f%%"),
    "Tăng trưởng (%)": st.column_
