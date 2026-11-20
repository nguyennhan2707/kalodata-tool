import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

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

# --- 2. HÀM GỌI API KALODATA ---
def fetch_kalodata(date_range, sort_by, commission, price_range, keyword):
    url = "https://www.kalodata.com/openapi/v1/tiktok/product/rank"
    headers = {
        "Content-Type": "application/json",
        "secret-key": st.secrets["KALODATA_SECRET_KEY"]
    }
    payload = {
        "region": "VN",
        "language": "vi-VN",
        "currency": "VND",
        "date_range": date_range,
        "sort_field": {"field": sort_by, "type": "DESC"},
        "page_size": 100,  # Luôn lấy 100 để tối ưu 0.1 điểm
        "page_number": 1,
        "is_affiliate": 1,
        "commission_rate": commission,
        "unit_price_range": price_range,
        "need_image": 1,
        "need_extra": True
    }
    if keyword.strip():
        payload["keyword"] = keyword.strip()

    res = requests.post(url, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()

# --- 3. GIAO DIỆN WEB ---
st.title("Tool Săn Sản Phẩm TikTok Shop")

tab1, tab2 = st.tabs(["Lấy dữ liệu mới (Gọi API)", "Kho lưu trữ Google Sheets"])

with tab1:
    with st.sidebar:
        st.header("Bộ lọc API")
        date_range = st.selectbox("Khoảng thời gian", ["lastDay", "last7Day", "last30Day"], index=1)
        sort_by = st.selectbox("Sắp xếp giảm dần theo", [
            "video_revenue", "revenue_growth_rate", "revenue", "sales_volumn", "commission_rate"
        ])
        commission = st.text_input("Hoa hồng (%)", value=">=10")
        price_range = st.text_input("Khoảng giá (VND)", value="25000-150000")
        keyword = st.text_input("Từ khóa (để trống nếu lấy toàn bộ)", value="")

    if st.button("Gọi API lấy Top 100 & Lưu vào Sheet (0.1 điểm)", type="primary"):
        with st.spinner("Đang gọi Kalodata API..."):
            try:
                res_json = fetch_kalodata(date_range, sort_by, commission, price_range, keyword)
                items = res_json.get("data", [])
                
                if not items:
                    st.warning("Không tìm thấy sản phẩm nào khớp bộ lọc.")
                else:
                    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                    rows = []
                    for item in items:
                        rows.append({
                            "ngay_lay": crawl_time,
                            "image": item.get("master_image_url", ""),
                            "product_id": str(item.get("product_id", "")),
                            "product_name": item.get("product_name", ""),
                            "unit_price": item.get("unit_price", 0),
                            "commission_rate": item.get("commission_rate", 0),
                            "sales_volumn": item.get("sales_volumn", 0),
                            "video_revenue": item.get("video_revenue", 0),
                            "revenue": item.get("revenue", 0),
                            "growth_rate": item.get("revenue_growth_rate", 0),
                            "seller_name": item.get("seller_name", ""),
                            "trang_thai": "Chưa làm"
                        })
                    
                    df_new = pd.DataFrame(rows)
                    
                    # Lưu nối tiếp vào Google Sheets
                    sheet = get_gsheet()
                    if not sheet.get_all_values():
                        sheet.append_row(df_new.columns.tolist())
                    sheet.append_rows(df_new.fillna("").values.tolist())
                    
                    st.success(f"Đã lấy và lưu thành công {len(df_new)} sản phẩm lúc {crawl_time}!")
                    st.dataframe(
                        df_new,
                        column_config={"image": st.column_config.ImageColumn("Ảnh SP")},
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"Lỗi khi gọi API hoặc lưu Sheet: {e}")

with tab2:
    if st.button("Tải lại dữ liệu từ Google Sheets"):
        st.cache_data.clear()
    try:
        sheet = get_gsheet()
        data = sheet.get_all_records()
        if data:
            df_all = pd.DataFrame(data)
            dates = ["Tất cả"] + sorted(df_all["ngay_lay"].unique().tolist(), reverse=True)
            selected_date = st.selectbox("Lọc theo đợt lấy dữ liệu", dates)
            
            df_view = df_all if selected_date == "Tất cả" else df_all[df_all["ngay_lay"] == selected_date]
            st.dataframe(
                df_view,
                column_config={"image": st.column_config.ImageColumn("Ảnh SP")},
                use_container_width=True,
                height=600
            )
        else:
            st.info("Google Sheet chưa có dữ liệu. Hãy qua Tab 1 để gọi API lần đầu.")
    except Exception as e:
        st.error(f"Lỗi đọc Google Sheets: {e}")
