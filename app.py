import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

st.set_page_config(page_title="Săn Sản Phẩm Affiliate", layout="wide")

# --- 1. KẾT NỐI GOOGLE SHEETS ---
@st.cache_resource
def get_gsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(st.secrets["SHEET_ID"]).worksheet("Data")
    return sheet

# --- 2. HÀM LỌC ĐỘNG THEO TỪNG CỘT ---
def filter_dataframe(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    df = df.copy()
    with st.expander("🔍 Bộ lọc chi tiết theo từng cột", expanded=False):
        filterable_cols = [c for c in df.columns if c != "Ảnh SP"]
        selected_cols = st.multiselect(
            "Chọn các cột muốn lọc:",
            options=filterable_cols,
            key=f"{key_prefix}_cols"
        )
        for col in selected_cols:
            numeric_series = pd.to_numeric(df[col], errors="coerce")
            is_numeric = (
                numeric_series.notna().sum() > 0
                and numeric_series.notna().sum() == df[col].replace("", pd.NA).notna().sum()
            )

            if is_numeric and col not in ["Mã SP", "Mã Shop", "Mã ngành cấp 1", "Mã ngành cấp 2", "Mã ngành cấp 3"]:
                _min = float(numeric_series.min())
                _max = float(numeric_series.max())
                if _min < _max:
                    user_range = st.slider(
                        f"Khoảng giá trị cho [{col}]",
                        min_value=_min,
                        max_value=_max,
                        value=(_min, _max),
                        key=f"{key_prefix}_{col}"
                    )
                    df = df[numeric_series.between(user_range[0], user_range[1])]
                else:
                    st.caption(f"Cột [{col}] chỉ có 1 giá trị duy nhất: {_min}")
            else:
                unique_vals = df[col].astype(str).unique().tolist()
                if len(unique_vals) <= 30:
                    chosen = st.multiselect(
                        f"Chọn giá trị cho [{col}]",
                        options=unique_vals,
                        default=unique_vals,
                        key=f"{key_prefix}_{col}"
                    )
                    df = df[df[col].astype(str).isin(chosen)]
                else:
                    search_text = st.text_input(
                        f"Tìm kiếm từ khóa trong [{col}]",
                        key=f"{key_prefix}_{col}"
                    )
                    if search_text.strip():
                        df = df[df[col].astype(str).str.contains(search_text.strip(), case=False, na=False)]
    return df

# --- 3. HÀM GỌI API KALODATA ---
def fetch_kalodata(payload: dict):
    url = "https://www.kalodata.com/openapi/v1/tiktok/product/rank"
    headers = {
        "Content-Type": "application/json",
        "secret-key": st.secrets["KALODATA_SECRET_KEY"]
    }
    res = requests.post(url, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()

# --- 4. GIAO DIỆN WEB ---
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
}

# --- THANH BỘ LỌC API (100% TIẾNG VIỆT) ---
with st.sidebar:
    st.header("⚙️ Bộ lọc gọi API")

    # Nhóm 1: Bộ lọc cơ bản
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
        "Doanh thu Tủ trưng bày": "showcase_revenue",
        "Tên sản phẩm": "product_name",
        "Mã sản phẩm": "product_id"
    }
    sort_field_label = st.selectbox("Sắp xếp theo", list(sort_field_options.keys()), index=0)

    sort_type_options = {"Giảm dần (Cao → Thấp)": "DESC", "Tăng dần (Thấp → Cao)": "ASC"}
    sort_type_label = st.selectbox("Thứ tự sắp xếp", list(sort_type_options.keys()), index=0)

    category_ids_str = st.text_input(
        "Mã ngành hàng",
        value="",
        help="Nhập 1 hoặc nhiều mã ngành cách nhau bằng dấu phẩy. VD: 700437"
    )
    keyword = st.text_input("Từ khóa tìm kiếm", value="", placeholder="VD: bánh tráng, khô gà...")
    commission = st.text_input("Tỷ lệ hoa hồng (%)", value=">=10", help="VD: >=10, 15-35, <20")
    price_range = st.text_input("Khoảng đơn giá", value="25000-150000", help="VD: 25000-150000")

    # Nhóm 2: Bộ lọc nâng cao (Tất cả trường còn lại của API, không tốn phí)
    with st.expander("🎯 Bộ lọc nâng cao (Affiliate, Vận chuyển, ID)"):
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
        tts_label = st.selectbox("
