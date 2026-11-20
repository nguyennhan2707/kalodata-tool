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
        tts_label = st.selectbox("Hình thức vận hành Shop", list(tts_options.keys()), index=0)

        launch_options = {
            "Tất cả thời gian ra mắt": None,
            "Mới ra mắt trong 3 ngày (<3)": "<3",
            "Mới ra mắt trong 7 ngày (<7)": "<7",
            "Mới ra mắt trong 30 ngày (<30)": "<30",
            "Đã ra mắt trên 30 ngày (>30)": ">30"
        }
        launch_label = st.selectbox("Thời gian ra mắt sản phẩm", list(launch_options.keys()), index=0)

        revenue_range = st.text_input("Khoảng doanh thu", value="", placeholder="VD: >10000000 hoặc 1000000-50000000")
        need_all = st.checkbox("Bao gồm cả sản phẩm chưa có doanh số", value=False)

        st.markdown("---")
        shop_id = st.text_input("Lọc theo Mã Cửa hàng (Shop ID)", value="")
        creator_id = st.text_input("Lọc theo Mã Nhà sáng tạo (Creator ID)", value="")
        video_id = st.text_input("Lọc theo Mã Video (Video ID)", value="")
        livestream_id = st.text_input("Lọc theo Mã Livestream (Livestream ID)", value="")

    # Nhóm 3: Cài đặt thị trường & Phân trang (Khóa tối đa 100 dòng = 0.1 điểm)
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
        page_number = st.number_input("Số trang (Lấy trang 2 để lấy top 101-200)", min_value=1, value=1)
        need_image = st.checkbox("Lấy link ảnh sản phẩm (Miễn phí)", value=True)
        need_extra = st.checkbox("Lấy thêm Tên Shop & Số SKU (Miễn phí)", value=True)

# Xây dựng payload gửi API
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
    "need_image": 1 if need_image else 0,  # Chỉ dùng 1 (miễn phí) hoặc 0, tuyệt đối không dùng 2 (tốn phí)
    "need_extra": need_extra
}

if category_ids_str.strip():
    api_payload["category_ids"] = [c.strip() for c in category_ids_str.split(",") if c.strip()]
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
if shop_id.strip():
    api_payload["shop_id"] = shop_id.strip()
if creator_id.strip():
    api_payload["creator_id"] = creator_id.strip()
if video_id.strip():
    api_payload["video_id"] = video_id.strip()
if livestream_id.strip():
    api_payload["livestream_id"] = livestream_id.strip()

# --- 2 TAB CHÍNH ---
tab1, tab2 = st.tabs(["Lấy dữ liệu mới (Gọi API)", "Kho lưu trữ Google Sheets"])

with tab1:
    if st.button(f"Gọi API lấy Top {page_size} (Trang {page_number}) & Lưu vào Sheet — 0.1 điểm", type="primary"):
        with st.spinner("Đang gọi Kalodata API..."):
            try:
                res_json = fetch_kalodata(api_payload)
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

                    sheet = get_gsheet()
                    if not sheet.get_all_values():
                        sheet.append_row(df_new.columns.tolist())
                    sheet.append_rows(df_new.fillna("").values.tolist())

                    st.success(f"Đã lấy và lưu thành công {len(df_new)} sản phẩm lúc {crawl_time}!")
            except Exception as e:
                st.error(f"Lỗi khi gọi API hoặc lưu Sheet: {e}")

    if "last_df" in st.session_state:
        df_filtered_new = filter_dataframe(st.session_state["last_df"], key_prefix="tab1")
        st.caption(f"Đang hiển thị {len(df_filtered_new)} / {len(st.session_state['last_df'])} sản phẩm")
        st.dataframe(df_filtered_new, column_config=COLUMN_CONFIG, use_container_width=True, height=550)

with tab2:
    if st.button("Tải lại dữ liệu từ Google Sheets"):
        st.cache_data.clear()
    try:
        sheet = get_gsheet()
        data = sheet.get_all_records()
        if data:
            df_all = pd.DataFrame(data)
            dates = ["Tất cả"] + sorted(df_all["Ngày lấy"].astype(str).unique().tolist(), reverse=True)
            selected_date = st.selectbox("Lọc nhanh theo đợt lấy dữ liệu", dates)

            df_view = df_all if selected_date == "Tất cả" else df_all[df_all["Ngày lấy"].astype(str) == selected_date]
            df_filtered_all = filter_dataframe(df_view, key_prefix="tab2")

            st.caption(f"Đang hiển thị {len(df_filtered_all)} / {len(df_view)} sản phẩm")
            st.dataframe(df_filtered_all, column_config=COLUMN_CONFIG, use_container_width=True, height=600)
        else:
            st.info("Google Sheet chưa có dữ liệu. Hãy qua Tab 1 để gọi API lần đầu.")
    except Exception as e:
        st.error(f"Lỗi đọc Google Sheets: {e}")
