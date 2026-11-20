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

# --- 2. ĐỒNG BỘ MASTER DATA TỔNG QUÁT TỪ DỮ LIỆU API ---
# Các trường không đưa vào Master Data (ID sản phẩm, ảnh, số liệu biến động theo ngày)
EXCLUDED_AUTO_FIELDS = {
    "product_id", "product_name", "master_image_url", "revenue", "commission_rate",
    "revenue_growth_rate", "sales_volumn", "unit_price", "live_revenue",
    "video_revenue", "showcase_revenue", "launch_date", "sku_count",
    "pri_category", "sec_category", "ter_category", "seller_id", "seller_name"
}

def extract_master_entries_from_api(items: list) -> list:
    """Trích xuất toàn bộ Master Data từ JSON gốc của API (Ngành 3 cấp, Shop, và các trường phân loại khác)."""
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

        # Tự động gom thêm nếu sau này API trả về trường phân loại mới dạng chuỗi hoặc object
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

def extract_master_entries_from_df(df: pd.DataFrame) -> list:
    """Trích xuất Master Data từ tab Data cũ (chạy 1 lần nếu MasterData đang trống)."""
    entries = []
    for _, row in df.iterrows():
        c1_id, c1_name = str(row.get("Mã ngành cấp 1", "")).strip(), str(row.get("Ngành cấp 1", "")).strip()
        c2_id, c2_name = str(row.get("Mã ngành cấp 2", "")).strip(), str(row.get("Ngành cấp 2", "")).strip()
        c3_id, c3_name = str(row.get("Mã ngành cấp 3", "")).strip(), str(row.get("Ngành cấp 3", "")).strip()
        s_id, s_name = str(row.get("Mã Shop", "")).strip(), str(row.get("Tên Shop", "")).strip()

        if c1_id and c1_name:
            entries.append(("nganh_cap_1", c1_id, c1_name, ""))
        if c2_id and c2_name:
            entries.append(("nganh_cap_2", c2_id, c2_name, c1_id))
        if c3_id and c3_name:
            entries.append(("nganh_cap_3", c3_id, c3_name, c2_id))
        if s_id and s_name:
            entries.append(("shop", s_id, s_name, ""))
    return entries

def save_master_entries(entries: list) -> int:
    """Lưu bổ sung các bản ghi Master Data chưa tồn tại vào tab MasterData."""
    if not entries:
        return 0
    ws = get_master_sheet()
    existing = ws.get_all_records()
    existing_keys = {
        (str(r.get("loai_du_lieu", "")).strip(), str(r.get("ma_id", "")).strip(), str(r.get("ma_cha", "")).strip())
        for r in existing
    }

    new_rows = []
    seen = set()
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

    # Nếu MasterData chưa có gì, tự động quét tab Data cũ để khởi tạo
    if not records:
        try:
            old_data = get_data_sheet().get_all_records()
            if old_data:
                entries = extract_master_entries_from_df(pd.DataFrame(old_data))
                save_master_entries(entries)
                records = ws.get_all_records()
        except Exception:
            pass

    if not records:
        return pd.DataFrame(columns=["loai_du_lieu", "ma_id", "ten_hien_thi", "ma_cha"])

    df_m = pd.DataFrame(records).astype(str)
    for col in df_m.columns:
        df_m[col] = df_m[col].str.strip()
    return df_m

# --- 3. HÀM LỌC ĐỘNG THEO TỪNG CỘT ---
def filter_dataframe(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    df = df.copy()
    with st.expander("🔍 Bộ lọc chi tiết theo từng cột", expanded=False):
        filterable_cols = [c for c in df.columns if c != "Ảnh SP"]
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

# --- 4. HÀM GỌI API KALODATA ---
def fetch_kalodata(payload: dict):
    url = "https://www.kalodata.com/openapi/v1/tiktok/product/rank"
    headers = {
        "Content-Type": "application/json",
        "secret-key": st.secrets["KALODATA_SECRET_KEY"]
    }
    res = requests.post(url, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()

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
}

df_master = load_master_data()

# --- THANH BỘ LỌC API (100% TIẾNG VIỆT + ĐỌC TỪ MASTER DATA) ---
with st.sidebar:
    st.header("⚙️ Bộ lọc gọi API")

    # 1. Ngành hàng 3 cấp (lấy từ MasterData)
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

    # 2. Bộ lọc cơ bản
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

    keyword = st.text_input("Từ khóa tìm kiếm", value="", placeholder="VD: bánh tráng, khô gà...")
    commission = st.text_input("Tỷ lệ hoa hồng (%)", value=">=10", help="VD: >=10, 15-35, <20")
    price_range = st.text_input("Khoảng đơn giá", value="25000-150000", help="VD: 25000-150000")

    # 3. Bộ lọc nâng cao (Tích hợp luôn chọn Shop từ Master Data)
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
        creator_id = st.text_input("Lọc theo Mã Nhà sáng tạo (Creator ID)", value="")
        video_id = st.text_input("Lọc theo Mã Video (Video ID)", value="")
        livestream_id = st.text_input("Lọc theo Mã Livestream (Livestream ID)", value="")

    # 4. Thị trường & Phân trang
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
if creator_id.strip():
    api_payload["creator_id"] = creator_id.strip()
if video_id.strip():
    api_payload["video_id"] = video_id.strip()
if livestream_id.strip():
    api_payload["livestream_id"] = livestream_id.strip()

# --- 3 TAB CHÍNH ---
tab1, tab2, tab3 = st.tabs(["Lấy dữ liệu mới (Gọi API)", "Kho lưu trữ Google Sheets", "Quản lý Master Data"])

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

                    # 1. Lưu sản phẩm vào tab Data
                    data_ws = get_data_sheet()
                    if not data_ws.get_all_values():
                        data_ws.append_row(df_new.columns.tolist())
                    data_ws.append_rows(df_new.fillna("").values.tolist())

                    # 2. Tự động trích xuất và cập nhật toàn bộ Master Data từ JSON API
                    master_entries = extract_master_entries_from_api(items)
                    added_count = save_master_entries(master_entries)
                    if added_count > 0:
                        load_master_data.clear()
                        st.toast(f"Đã tự động học thêm {added_count} mục mới vào Master Data!", icon="🧠")

                    st.success(f"Đã lấy và lưu thành công {len(df_new)} sản phẩm lúc {crawl_time}!")
            except Exception as e:
                st.error(f"Lỗi khi gọi API hoặc lưu Sheet: {e}")

    if "last_df" in st.session_state:
        df_filtered_new = filter_dataframe(st.session_state["last_df"], key_prefix="tab1")
        st.caption(f"Đang hiển thị {len(df_filtered_new)} / {len(st.session_state['last_df'])} sản phẩm")
        st.dataframe(df_filtered_new, column_config=COLUMN_CONFIG, use_container_width=True, height=550)

with tab2:
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
            df_filtered_all = filter_dataframe(df_view, key_prefix="tab2")

            st.caption(f"Đang hiển thị {len(df_filtered_all)} / {len(df_view)} sản phẩm")
            st.dataframe(df_filtered_all, column_config=COLUMN_CONFIG, use_container_width=True, height=600)
        else:
            st.info("Google Sheet chưa có dữ liệu. Hãy qua Tab 1 để gọi API lần đầu.")
    except Exception as e:
        st.error(f"Lỗi đọc Google Sheets: {e}")

with tab3:
    st.subheader("Kho Master Data tự động tích lũy")
    if st.button("Làm mới Master Data"):
        load_master_data.clear()
        st.rerun()

    if df_master.empty:
        st.info("Chưa có Master Data. Hãy qua Tab 1 gọi API để hệ thống tự động thu thập.")
    else:
        loai_list = ["Tất cả"] + sorted(df_master["loai_du_lieu"].unique().tolist())
        sel_loai = st.selectbox("Lọc theo loại Master Data", loai_list)
        df_m_view = df_master if sel_loai == "Tất cả" else df_master[df_master["loai_du_lieu"] == sel_loai]
        st.caption(f"Tổng cộng: {len(df_m_view)} mục")
        st.dataframe(df_m_view, use_container_width=True, height=500)
