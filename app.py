import time
import json
import altair as alt
import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

st.set_page_config(page_title="Săn Sản Phẩm Affiliate", layout="wide")

# --- 1. KẾT NỐI GOOGLE SHEETS ---
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

# --- 2. ĐỒNG BỘ MASTER DATA ---
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
        ws.append_rows(new_rows)
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

# --- 3. CÁC HÀM GỌI API & XỬ LÝ DỮ LIỆU ---
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
        return [float(x) for x in val if str(x).replace(".", "", 1).replace("-", "", 1).isdigit()]
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [float(x) for x in parsed]
        except Exception:
            parts = [p.strip() for p in val.strip("[]").split(",") if p.strip()]
            return [float(p) for p in parts if p.replace(".", "", 1).replace("-", "", 1).isdigit()]
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
        m1.metric("Đơn giá", f"{float(row.get('Đơn giá (VNĐ)', 0) or 0):,.0f} ₫")
        m2.metric("Hoa hồng", f"{float(row.get('Hoa hồng (%)', 0) or 0):.1f}%")
        m3.metric("Lượt bán", f"{int(float(row.get('Lượt bán', 0) or 0)):,}")

        m4, m5, m6 = st.columns(3)
        m4.metric("Doanh thu Video", f"{float(row.get('Doanh thu Video', 0) or 0):,.0f} ₫")
        m5.metric("Tổng doanh thu", f"{float(row.get('Tổng doanh thu', 0) or 0):,.0f} ₫")
        m6.metric("Tăng trưởng", f"{float(row.get('Tăng trưởng (%)', 0) or 0):+.1f}%")

        m7, m8, m9 = st.columns(3)
        m7.metric("Số NST (Cạnh tranh)", f"{int(float(row.get('Số NST', 0) or 0)):,}")
        m8.metric("Số Video gắn SP", f"{int(float(row.get('Số Video', 0) or 0)):,}")
        m9.metric("Số đánh giá", f"{int(float(row.get('Số đánh giá', 0) or 0)):,}")

    st.markdown("---")
    c_ads, c_ai = st.columns(2)
    c_ads.info(
        f"**Quảng cáo (Ads):** {row.get('Có chạy Ads', 'Chưa check')} "
        f"| Số Video Ads: **{row.get('Số Video Ads', 0)}** "
        f"| ROAS cao nhất: **{row.get('ROAS cao nhất', 0)}**"
    )
    c_ai.info(
        f"**Video AI:** {row.get('Có Video AI', 'Chưa check')} "
        f"| Số Video AI đang ra đơn: **{row.get('Số Video AI', 0)}**"
    )

    trend_vals = row.get("Xu hướng doanh thu", [])
    if isinstance(trend_vals, list) and len(trend_vals) > 0:
        st.markdown("**📈 Biểu đồ xu hướng doanh thu theo ngày:**")
        df_t = pd.DataFrame({"Ngày": range(1, len(trend_vals) + 1), "Doanh thu": trend_vals})
        st.line_chart(df_t.set_index("Ngày"), height=200)

# --- 4. HÀM LỌC ĐỘNG THEO TỪNG CỘT ---
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

# --- 5. GIAO DIỆN WEB ---
st.title("Tool Săn Sản Phẩm TikTok Shop")

COLUMN_CONFIG = {
    "Ảnh SP": st.column_config.ImageColumn("Ảnh SP"),
    "Đơn giá (VNĐ)": st.column_config.NumberColumn(format="%.0f ₫"),
    "Tổng doanh thu": st.column_config.NumberColumn(format="%.0f ₫"),
    "Doanh thu Video": st.column_config.NumberColumn(format="%.0f ₫"),
    "Doanh thu Live": st.column_config.NumberColumn(format="%.0f ₫"),
    "Doanh thu Tủ trưng bày": st.column_config.NumberColumn(format="%.0f ₫"),
    "Hoa hồng (%)": st.column_config.NumberColumn(format="%.1f%%"),
    "Tăng trưởng (%)": st.column_config.NumberColumn(format="%.1f%%"),
    "Xu hướng doanh thu": st.column_config.LineChartColumn("Biểu đồ xu hướng"),
}

df_master = load_master_data()

# --- THANH BỘ LỌC API BÊN TRÁI ---
with st.sidebar:
    st.header("⚙️ Bộ lọc gọi API")

    st.subheader("📂 Ngành hàng (Master Data)")
    selected_cat_id = ""
    selected_cat_path = []

    df_c1_all = df_master[df_master["loai_du_lieu"] == "nganh_cap_1"]
    df_c2_all = df_master[df_master["loai_du_lieu"] == "nganh_cap_2"]
    df_c3_all = df_master[df_master["loai_du_lieu"] == "nganh_cap_3"]

    if df_c1_all.empty:
        st.caption("Chưa có Master Data ngành hàng. Hãy gọi API 1 lần để tự động lưu.")
    else:
        c1_map = dict(zip(df_c1_all["ten_hien_thi"], df_c1_all["ma_id"]))
        sel_c1_name = st.selectbox("Ngành cấp 1", ["Tất cả"] + sorted(c1_map.keys()))

        if sel_c1_name != "Tất cả":
            c1_id = c1_map[sel_c1_name]
            selected_cat_id = c1_id
            selected_cat_path.append(sel_c1_name)

            df_c2_sub = df_c2_all[df_c2_all["ma_cha"] == c1_id]
            if not df_c2_sub.empty:
                c2_map = dict(zip(df_c2_sub["ten_hien_thi"], df_c2_sub["ma_id"]))
                sel_c2_name = st.selectbox("Ngành cấp 2", ["Tất cả"] + sorted(c2_map.keys()))

                if sel_c2_name != "Tất cả":
                    c2_id = c2_map[sel_c2_name]
                    selected_cat_id = c2_id
                    selected_cat_path.append(sel_c2_name)

                    df_c3_sub = df_c3_all[df_c3_all["ma_cha"] == c2_id]
                    if not df_c3_sub.empty:
                        c3_map = dict(zip(df_c3_sub["ten_hien_thi"], df_c3_sub["ma_id"]))
                        sel_c3_name = st.selectbox("Ngành cấp 3", ["Tất cả"] + sorted(c3_map.keys()))

                        if sel_c3_name != "Tất cả":
                            selected_cat_id = c3_map[sel_c3_name]
                            selected_cat_path.append(sel_c3_name)

        if selected_cat_id:
            st.info(f"**Đang chọn:** {' > '.join(selected_cat_path)}\n\nMã gửi API: `{selected_cat_id}`")

    manual_cat_ids = st.text_input("Hoặc nhập tay Mã ngành hàng", value="", help="Nhập nhiều mã cách nhau bằng dấu phẩy.")
    st.markdown("---")

    date_options = {
        "1 ngày trước (Hôm qua)": "lastDay",
        "7 ngày gần nhất": "last7Day",
        "30 ngày gần nhất": "last30Day",
        "Tùy chọn khoảng ngày (tối đa 30 ngày)": "custom"
    }
    date_label = st.selectbox("Khoảng thời gian", list(date_options.keys()), index=1)
    if date_options[date_label] == "custom":
        today = datetime.now().date()
        col_d1, col_d2 = st.columns(2)
        start_d = col_d1.date_input("Từ ngày", today - timedelta(days=7))
        end_d = col_d2.date_input("Đến ngày", today - timedelta(days=1))
        date_range = f"{start_d.strftime('%Y-%m-%d')}~{end_d.strftime('%Y-%m-%d')}"
    else:
        date_range = date_options[date_label]

    sort_field_options = {
        "Doanh thu từ Video": "video_revenue",
        "Tỷ lệ tăng trưởng doanh thu": "revenue_growth_rate",
        "Tổng doanh thu": "revenue",
        "Số lượng bán (Lượt bán)": "sales_volumn",
        "Tỷ lệ hoa hồng (%)": "commission_rate",
        "Đơn giá sản phẩm": "unit_price",
        "Ngày ra mắt": "launch_date",
        "Doanh thu Livestream": "live_revenue",
        "Doanh thu Tủ trưng bày": "showcase_revenue"
    }
    sort_field_label = st.selectbox("Sắp xếp theo", list(sort_field_options.keys()), index=0)

    sort_type_options = {"Giảm dần (Cao → Thấp)": "DESC", "Tăng dần (Thấp → Cao)": "ASC"}
    sort_type_label = st.selectbox("Thứ tự sắp xếp", list(sort_type_options.keys()), index=0)

    keyword = st.text_input("Từ khóa tìm kiếm", value="", placeholder="VD: bánh tráng, khô gà...")
    commission = st.text_input("Tỷ lệ hoa hồng (%)", value=">=10", help="VD: >=10, 15-35, <20")
    price_range = st.text_input("Khoảng đơn giá", value="25000-150000", help="VD: 25000-150000")

    with st.expander("🎯 Bộ lọc nâng cao (Shop, Affiliate, Vận chuyển)"):
        df_shop_all = df_master[df_master["loai_du_lieu"] == "shop"]
        selected_shop_id = ""
        if not df_shop_all.empty:
            shop_map = {f"{r['ten_hien_thi']} ({r['ma_id']})": r["ma_id"] for _, r in df_shop_all.iterrows()}
            sel_shop_label = st.selectbox("Chọn Cửa hàng (từ Master Data)", ["Tất cả"] + sorted(shop_map.keys()))
            if sel_shop_label != "Tất cả":
                selected_shop_id = shop_map[sel_shop_label]
        manual_shop_id = st.text_input("Hoặc nhập tay Mã Cửa hàng (Shop ID)", value="")

        affiliate_options = {
            "Chỉ sản phẩm có Affiliate": 1,
            "Tất cả (Gồm cả không Affiliate)": None,
            "Chỉ sản phẩm không có Affiliate": 0
        }
        affiliate_label = st.selectbox("Chương trình Affiliate", list(affiliate_options.keys()), index=0)

        delivery_options = {
            "Tất cả hình thức giao hàng": None,
            "Hàng nội địa (Trong nước)": "local",
            "Hàng quốc tế (Xuyên biên giới)": "global"
        }
        delivery_label = st.selectbox("Phương thức giao hàng", list(delivery_options.keys()), index=0)

        tts_options = {
            "Tất cả hình thức quản lý": None,
            "TikTok quản lý toàn diện (TTS)": 1,
            "Người bán tự giao hàng": 0
        }
        tts_label = st.selectbox("Hình thức vận hành Shop", list(tts_options.keys()), index=0)

        launch_options = {
            "Tất cả thời gian ra mắt": None,
            "Mới ra mắt trong 3 ngày (<3)": "<3",
            "Mới ra mắt trong 7 ngày (<7)": "<7",
            "Mới ra mắt trong 30 ngày (<30)": "<30",
            "Đã ra mắt trên 30 ngày (>30)": ">30"
        }
        launch_label = st.selectbox("Thời gian ra mắt sản phẩm", list(launch_options.keys()), index=0)
        revenue_range = st.text_input("Khoảng doanh thu", value="", placeholder="VD: >10000000")
        need_all = st.checkbox("Bao gồm cả sản phẩm chưa có doanh số", value=False)

    with st.expander("🌐 Thị trường & Phân trang (Mặc định VN)"):
        region_options = {
            "Việt Nam (VN)": ("VN", "vi-VN", "VND"),
            "Mỹ (US)": ("US", "en-US", "USD"),
            "Thái Lan (TH)": ("TH", "th-TH", "THB"),
            "Indonesia (ID)": ("ID", "id-ID", "IDR"),
            "Malaysia (MY)": ("MY", "en-US", "MYR"),
            "Philippines (PH)": ("PH", "en-US", "PHP"),
            "Singapore (SG)": ("SG", "en-US", "SGD")
        }
        region_label = st.selectbox("Quốc gia / Thị trường", list(region_options.keys()), index=0)
        region_code, lang_code, curr_code = region_options[region_label]

        page_size = st.number_input("Số sản phẩm/lần gọi (Tối đa 100 = 0.1 điểm)", min_value=1, max_value=100, value=100)
        page_number = st.number_input("Số trang", min_value=1, value=1)
        need_image = st.checkbox("Lấy link ảnh sản phẩm (Miễn phí)", value=True)
        need_extra = st.checkbox("Lấy thêm Tên Shop & Số SKU (Miễn phí)", value=True)

# Xây dựng payload chung cho /product/rank
api_payload = {
    "region": region_code,
    "language": lang_code,
    "currency": curr_code,
    "date_range": date_range,
    "sort_field": {
        "field": sort_field_options[sort_field_label],
        "type": sort_type_options[sort_type_label]
    },
    "page_size": int(page_size),
    "page_number": int(page_number),
    "need_all": need_all,
    "need_image": 1 if need_image else 0,
    "need_extra": need_extra
}
if manual_cat_ids.strip():
    api_payload["category_ids"] = [c.strip() for c in manual_cat_ids.split(",") if c.strip()]
elif selected_cat_id:
    api_payload["category_ids"] = [selected_cat_id]
if manual_shop_id.strip():
    api_payload["shop_id"] = manual_shop_id.strip()
elif selected_shop_id:
    api_payload["shop_id"] = selected_shop_id
if keyword.strip():
    api_payload["keyword"] = keyword.strip()
if commission.strip():
    api_payload["commission_rate"] = commission.strip()
if price_range.strip():
    api_payload["unit_price_range"] = price_range.strip()
if affiliate_options[affiliate_label] is not None:
    api_payload["is_affiliate"] = affiliate_options[affiliate_label]
if delivery_options[delivery_label] is not None:
    api_payload["delivery_type"] = delivery_options[delivery_label]
if tts_options[tts_label] is not None:
    api_payload["is_tts_product"] = tts_options[tts_label]
if launch_options[launch_label] is not None:
    api_payload["launch_date"] = launch_options[launch_label]
if revenue_range.strip():
    api_payload["revenue_range"] = revenue_range.strip()

# --- 4 TAB CHÍNH ---
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 Săn SP Win (Dashboard Tuần)",
    "⚡ Lấy nhanh Top 100 (API đơn)",
    "📊 Kho lưu trữ (Data)",
    "🧠 Quản lý Master Data"
])

# ==========================================
# TAB 1: DASHBOARD TUẦN (BIỂU ĐỒ CỘT + POPUP + LUỒNG 3 BƯỚC)
# ==========================================
with tab1:
    st.subheader("Luồng chạy Batch hàng tuần (3 bước — ~3.1 điểm / 9.300đ)")
    with st.container(border=True):
        st.markdown("**Bước 1 & 2 (Tự động):** Quét Top 100 SP theo bộ lọc bên trái $\\rightarrow$ Lọc sơ bộ $\\rightarrow$ Lấy Số NST & Biểu đồ xu hướng cho Top 20 SP.")
        c_p1, c_p2, c_p3 = st.columns(3)
        max_sales_filter = c_p1.number_input("Lọc sơ bộ: Lượt bán tối đa (<)", min_value=100, value=3000, step=500)
        min_growth_filter = c_p2.number_input("Lọc sơ bộ: Tăng trưởng tối thiểu (%)", value=0.0, step=5.0)
        top_n_detail = c_p3.number_input("Số SP lấy chi tiết ở Bước 2", min_value=1, max_value=30, value=20)

        if st.button(f"🚀 Chạy Bước 1 & 2 (Tối đa {0.1 + top_n_detail * 0.1:.1f} điểm)", type="primary"):
            try:
                with st.spinner("Bước 1: Đang quét Top 100 sản phẩm (/product/rank)..."):
                    res_rank = call_kalodata_api("product/rank", api_payload)
                    items = res_rank.get("data", [])

                if not items:
                    st.warning("Bước 1 không trả về sản phẩm nào khớp bộ lọc.")
                else:
                    added_m = save_master_entries(extract_master_entries_from_api(items))
                    if added_m > 0:
                        load_master_data.clear()

                    candidates = [
                        it for it in items
                        if (it.get("sales_volumn") or 0) < max_sales_filter
                        and (it.get("revenue_growth_rate") or 0) > min_growth_filter
                    ]
                    candidates.sort(key=lambda x: x.get("video_revenue") or 0, reverse=True)
                    top_candidates = candidates[:int(top_n_detail)]

                    if not top_candidates:
                        st.warning(f"Có {len(items)} SP từ Bước 1 nhưng không SP nào thỏa điều kiện Lượt bán < {max_sales_filter} và Tăng trưởng > {min_growth_filter}%.")
                    else:
                        st.info(f"Bước 1 lọc được **{len(candidates)}** SP đạt chuẩn. Đang chạy Bước 2 lấy chi tiết cho **Top {len(top_candidates)}** SP...")
                        progress_bar = st.progress(0)
                        crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                        dash_rows = []

                        for idx, item in enumerate(top_candidates):
                            pid = str(item.get("product_id", ""))
                            detail_payload = {
                                "region": region_code,
                                "language": lang_code,
                                "currency": curr_code,
                                "date_range": date_range,
                                "product_id": pid,
                                "need_image": 0,
                                "need_extra": False
                            }
                            try:
                                d_res = call_kalodata_api("product/detail", detail_payload)
                                d_data = d_res.get("data") or {}
                            except Exception:
                                d_data = {}

                            pri = item.get("pri_category") or {}
                            sec = item.get("sec_category") or {}
                            trend_list = d_data.get("revenue_trend") or []

                            dash_rows.append([
                                crawl_time,
                                item.get("master_image_url", ""),
                                pid,
                                item.get("product_name", ""),
                                item.get("unit_price", 0),
                                item.get("commission_rate", 0),
                                item.get("sales_volumn", 0),
                                item.get("video_revenue", 0),
                                item.get("revenue", 0),
                                item.get("revenue_growth_rate", 0),
                                d_data.get("creator_number", 0),
                                d_data.get("video_number", 0),
                                d_data.get("product_review_count", 0),
                                json.dumps(trend_list),
                                pri.get("category_name", ""),
                                sec.get("category_name", ""),
                                item.get("seller_name", ""),
                                "Chưa check", 0, 0, "Chưa check", 0
                            ])
                            progress_bar.progress((idx + 1) / len(top_candidates))
                            time.sleep(0.15)

                        dash_ws = get_dashboard_sheet()
                        dash_ws.append_rows(dash_rows)
                        st.success(f"Hoàn tất Bước 1 & 2! Đã lưu {len(dash_rows)} SP tiềm năng vào tab Weekly_Dashboard.")
                        st.rerun()
            except Exception as e:
                st.error(f"Lỗi khi chạy Batch Bước 1 & 2: {e}")

    st.markdown("---")
    st.subheader("📈 Dashboard Phân tích & Biểu đồ xếp hạng tuần")

    try:
        dash_ws = get_dashboard_sheet()
        dash_records = dash_ws.get_all_records()

        if not dash_records:
            st.info("Chưa có dữ liệu Dashboard. Hãy bấm nút **Chạy Bước 1 & 2** ở trên để bắt đầu.")
        else:
            df_dash = pd.DataFrame(dash_records)
            batches = sorted(df_dash["Đợt chạy"].astype(str).unique().tolist(), reverse=True)
            sel_batch = st.selectbox("Chọn đợt chạy tuần", batches)
            df_b = df_dash[df_dash["Đợt chạy"].astype(str) == sel_batch].copy()

            # Thanh lọc nhanh trên Dashboard
            f1, f2, f3 = st.columns(3)
            max_nst_val = int(pd.to_numeric(df_b["Số NST"], errors="coerce").max() or 100)
            nst_range = f1.slider(
                "Lọc Số Nhà sáng tạo (creator_number)",
                min_value=0, max_value=max(max_nst_val, 100),
                value=(0, min(max(max_nst_val, 100), 100))
            )
            ads_filter = f2.selectbox("Trạng thái Ads", ["Tất cả", "Có", "Không", "Chưa check"])
            ai_filter = f3.selectbox("Có Video AI?", ["Tất cả", "Có", "Không", "Chưa check"])

            df_b["Số NST_num"] = pd.to_numeric(df_b["Số NST"], errors="coerce").fillna(0)
            df_b = df_b[df_b["Số NST_num"].between(nst_range[0], nst_range[1])]
            if ads_filter != "Tất cả":
                df_b = df_b[df_b["Có chạy Ads"].astype(str) == ads_filter]
            if ai_filter != "Tất cả":
                df_b = df_b[df_b["Có Video AI"].astype(str) == ai_filter]

            df_b["Xu hướng doanh thu"] = df_b["Xu hướng doanh thu"].apply(parse_trend_list)

            # --- BIỂU ĐỒ CỘT TỪ THẤP ĐẾN CAO (CLICK ĐỂ MỞ POPUP) ---
            if not df_b.empty:
                st.markdown("#### 📊 Biểu đồ xếp hạng sản phẩm tiềm năng (Thấp → Cao)")
                st.caption("💡 Bấm trực tiếp vào bất kỳ cột sản phẩm nào trên biểu đồ để mở **Popup chi tiết đầy đủ**.")

                chart_metric = st.selectbox(
                    "Chọn chỉ số xếp hạng trên biểu đồ:",
                    ["Doanh thu Video", "Lượt bán", "Tăng trưởng (%)", "Hoa hồng (%)", "Tổng doanh thu"],
                    index=0
                )

                df_chart = df_b.copy()
                df_chart[chart_metric] = pd.to_numeric(df_chart[chart_metric], errors="coerce").fillna(0)
                df_chart["Mã SP"] = df_chart["Mã SP"].astype(str)
                # Tạo tên ngắn duy nhất cho trục X
                df_chart["Tên ngắn"] = df_chart.apply(
                    lambda r: f"{str(r['Tên sản phẩm'])[:18]}... ({str(r['Mã SP'])[-4:]})", axis=1
                )

                point_sel = alt.selection_point(name="select_prod", fields=["Mã SP"])
                bar_chart = (
                    alt.Chart(df_chart)
                    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                    .encode(
                        x=alt.X(
                            "Tên ngắn:N",
                            sort=alt.EncodingSortField(field=chart_metric, order="ascending"),
                            title="Sản phẩm (Xếp từ thấp → cao)",
                            axis=alt.Axis(labelAngle=-35)
                        ),
                        y=alt.Y(f"{chart_metric}:Q", title=chart_metric),
                        color=alt.condition(point_sel, alt.value("#FF4B4B"), alt.value("#4C78A8")),
                        tooltip=[
                            "Tên sản phẩm", "Mã SP", "Đơn giá (VNĐ)", "Hoa hồng (%)",
                            "Lượt bán", "Số NST", "Doanh thu Video", "Tăng trưởng (%)"
                        ]
                    )
                    .add_params(point_sel)
                    .properties(height=380)
                )

                chart_event = st.altair_chart(bar_chart, use_container_width=True, on_select="rerun")

                # Xử lý sự kiện Click cột -> Mở Popup
                sel_list = chart_event.selection.get("select_prod", []) if chart_event and chart_event.selection else []
                if sel_list:
                    clicked_pid = str(sel_list[0].get("Mã SP", ""))
                    if clicked_pid and clicked_pid != st.session_state.get("last_clicked_pid"):
                        st.session_state["last_clicked_pid"] = clicked_pid
                        matched = df_b[df_b["Mã SP"].astype(str) == clicked_pid]
                        if not matched.empty:
                            show_product_popup(matched.iloc[0])
                else:
                    st.session_state["last_clicked_pid"] = None

            # --- BẢNG DỮ LIỆU & BƯỚC 3 ---
            st.markdown("#### 📋 Bảng danh sách & Bước 3 (Check Ads + Video AI)")
            df_b_tbl = df_b.copy()
            df_b_tbl.insert(0, "Chọn check Ads", False)
            df_b_display = df_b_tbl.drop(columns=["Số NST_num", "Đợt chạy"])

            st.caption(f"Đang hiển thị **{len(df_b_display)}** sản phẩm. Tick vào cột **Chọn check Ads** rồi bấm nút Bước 3 bên dưới.")
            edited_df = st.data_editor(
                df_b_display,
                column_config={
                    "Chọn check Ads": st.column_config.CheckboxColumn("Chọn check Ads", default=False),
                    **COLUMN_CONFIG
                },
                disabled=[c for c in df_b_display.columns if c != "Chọn check Ads"],
                use_container_width=True,
                height=500,
                hide_index=True
            )

            selected_pids = edited_df[edited_df["Chọn check Ads"] == True]["Mã SP"].astype(str).tolist()
            if st.button(f"🔥 Chạy Bước 3: Check Ads & Video AI cho {len(selected_pids)} SP đã chọn ({len(selected_pids)*0.1:.1f} điểm)", disabled=len(selected_pids) == 0):
                prog3 = st.progress(0)
                all_sheet_vals = dash_ws.get_all_values()
                header_row = all_sheet_vals[0]
                col_idx_batch = header_row.index("Đợt chạy")
                col_idx_pid = header_row.index("Mã SP")
                col_idx_ads_start = header_row.index("Có chạy Ads") + 1

                for idx, pid in enumerate(selected_pids):
                    v_payload = {
                        "region": region_code,
                        "language": lang_code,
                        "currency": curr_code,
                        "date_range": date_range,
                        "sort_field": {"field": "revenue", "type": "DESC"},
                        "page_size": 50,
                        "page_number": 1,
                        "product_id": pid
                    }
                    try:
                        v_res = call_kalodata_api("video/rank", v_payload)
                        vids = v_res.get("data") or []
                    except Exception:
                        vids = []

                    ads_vids = [v for v in vids if v.get("ad") == 1]
                    ai_vids = [v for v in vids if v.get("ai_video") == 1]
                    max_roas = max([float(v.get("ads_roas") or 0) for v in ads_vids], default=0.0)

                    has_ads = "Có" if ads_vids else "Không"
                    has_ai = "Có" if ai_vids else "Không"

                    for r_i, r_val in enumerate(all_sheet_vals[1:], start=2):
                        if str(r_val[col_idx_batch]) == sel_batch and str(r_val[col_idx_pid]) == pid:
                            dash_ws.update(
                                values=[[has_ads, len(ads_vids), round(max_roas, 2), has_ai, len(ai_vids)]],
                                range_name=gspread.utils.rowcol_to_a1(r_i, col_idx_ads_start)
                            )
                            break

                    prog3.progress((idx + 1) / len(selected_pids))
                    time.sleep(1.1)

                st.success(f"Đã check xong Ads & Video AI cho {len(selected_pids)} sản phẩm!")
                st.rerun()
    except Exception as e:
        st.error(f"Lỗi tải Dashboard: {e}")

# ==========================================
# TAB 2: LẤY NHANH TOP 100 (API ĐƠN)
# ==========================================
with tab2:
    if st.button(f"Gọi API lấy Top {page_size} (Trang {page_number}) & Lưu vào Sheet — 0.1 điểm", type="primary"):
        with st.spinner("Đang gọi Kalodata API..."):
            try:
                res_json = call_kalodata_api("product/rank", api_payload)
                items = res_json.get("data", [])

                if not items:
                    st.warning("Không tìm thấy sản phẩm nào khớp bộ lọc.")
                else:
                    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                    rows = []
                    for item in items:
                        pri = item.get("pri_category") or {}
                        sec = item.get("sec_category") or {}
                        ter = item.get("ter_category") or {}
                        rows.append({
                            "Ngày lấy": crawl_time,
                            "Ảnh SP": item.get("master_image_url", ""),
                            "Mã SP": str(item.get("product_id", "")),
                            "Tên sản phẩm": item.get("product_name", ""),
                            "Đơn giá (VNĐ)": item.get("unit_price", 0),
                            "Hoa hồng (%)": item.get("commission_rate", 0),
                            "Lượt bán": item.get("sales_volumn", 0),
                            "Doanh thu Video": item.get("video_revenue", 0),
                            "Doanh thu Live": item.get("live_revenue", 0),
                            "Doanh thu Tủ trưng bày": item.get("showcase_revenue", 0),
                            "Tổng doanh thu": item.get("revenue", 0),
                            "Tăng trưởng (%)": item.get("revenue_growth_rate", 0),
                            "Ngày ra mắt": item.get("launch_date", ""),
                            "Mã Shop": str(item.get("seller_id", "")),
                            "Tên Shop": item.get("seller_name", ""),
                            "Số SKU": item.get("sku_count", ""),
                            "Mã ngành cấp 1": str(pri.get("category_id", "")),
                            "Ngành cấp 1": pri.get("category_name", ""),
                            "Mã ngành cấp 2": str(sec.get("category_id", "")),
                            "Ngành cấp 2": sec.get("category_name", ""),
                            "Mã ngành cấp 3": str(ter.get("category_id", "")),
                            "Ngành cấp 3": ter.get("category_name", ""),
                            "Trạng thái": "Chưa làm"
                        })

                    df_new = pd.DataFrame(rows)
                    st.session_state["last_df"] = df_new

                    data_ws = get_data_sheet()
                    if not data_ws.get_all_values():
                        data_ws.append_row(df_new.columns.tolist())
                    data_ws.append_rows(df_new.fillna("").values.tolist())

                    added_count = save_master_entries(extract_master_entries_from_api(items))
                    if added_count > 0:
                        load_master_data.clear()
                        st.toast(f"Đã tự động học thêm {added_count} mục mới vào Master Data!", icon="🧠")

                    st.success(f"Đã lấy và lưu thành công {len(df_new)} sản phẩm lúc {crawl_time}!")
            except Exception as e:
                st.error(f"Lỗi khi gọi API hoặc lưu Sheet: {e}")

    if "last_df" in st.session_state:
        df_filtered_new = filter_dataframe(st.session_state["last_df"], key_prefix="tab2")
        st.caption(f"Đang hiển thị {len(df_filtered_new)} / {len(st.session_state['last_df'])} sản phẩm")
        st.dataframe(df_filtered_new, column_config=COLUMN_CONFIG, use_container_width=True, height=550)

# ==========================================
# TAB 3: KHO LƯU TRỮ GOOGLE SHEETS (DATA)
# ==========================================
with tab3:
    if st.button("Tải lại dữ liệu từ Google Sheets"):
        load_master_data.clear()
        st.rerun()
    try:
        data_ws = get_data_sheet()
        data = data_ws.get_all_records()
        if data:
            df_all = pd.DataFrame(data)
            dates = ["Tất cả"] + sorted(df_all["Ngày lấy"].astype(str).unique().tolist(), reverse=True)
            selected_date = st.selectbox("Lọc nhanh theo đợt lấy dữ liệu", dates)

            df_view = df_all if selected_date == "Tất cả" else df_all[df_all["Ngày lấy"].astype(str) == selected_date]
            df_filtered_all = filter_dataframe(df_view, key_prefix="tab3")

            st.caption(f"Đang hiển thị {len(df_filtered_all)} / {len(df_view)} sản phẩm")
            st.dataframe(df_filtered_all, column_config=COLUMN_CONFIG, use_container_width=True, height=600)
        else:
            st.info("Google Sheet chưa có dữ liệu.")
    except Exception as e:
        st.error(f"Lỗi đọc Google Sheets: {e}")

# ==========================================
# TAB 4: QUẢN LÝ MASTER DATA
# ==========================================
with tab4:
    st.subheader("Kho Master Data tự động tích lũy")
    if st.button("Làm mới Master Data"):
        load_master_data.clear()
        st.rerun()

    if df_master.empty:
        st.info("Chưa có Master Data.")
    else:
        loai_list = ["Tất cả"] + sorted(df_master["loai_du_lieu"].unique().tolist())
        sel_loai = st.selectbox("Lọc theo loại Master Data", loai_list)
        df_m_view = df_master if sel_loai == "Tất cả" else df_master[df_master["loai_du_lieu"] == sel_loai]
        st.caption(f"Tổng cộng: {len(df_m_view)} mục")
        st.dataframe(df_m_view, use_container_width=True, height=500)
