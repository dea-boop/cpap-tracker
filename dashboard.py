import streamlit as st
import pandas as pd
import sqlite3
import pytz
from datetime import datetime

# Config
DB_NAME = "inventory.db"
MY_TIMEZONE = pytz.timezone('US/Pacific')

st.set_page_config(page_title="Inventory Tracker", layout="wide")

def load_data():
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM inventory_log", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

st.title("📊 Multi-Store Inventory Tracker")

# Load Data
df = load_data()

if df.empty:
    st.warning("Database is empty. Waiting for data...")
    st.stop()

# Pre-process
df['timestamp'] = pd.to_datetime(df['timestamp'])
if 'site' not in df.columns:
    df['site'] = 'CPAP Outlet' # Fallback for old data

# --- TABS FOR SITES ---
sites = df['site'].unique()
# Ensure we have tabs even if data is missing for one
all_sites = ["CPAP Outlet", "Airvoel"]
tabs = st.tabs(all_sites)

for i, site_name in enumerate(all_sites):
    with tabs[i]:
        # Filter data for this specific site
        site_df = df[df['site'] == site_name].copy()
        
        if site_df.empty:
            st.info(f"No data found for {site_name} yet.")
            continue

        # --- Sidebar Controls (Unique Key per tab to prevent conflict) ---
        col_filters_1, col_filters_2 = st.columns(2)
        with col_filters_1:
            date_key = f"date_{site_name}"
            selected_date = st.date_input(f"Select Date ({site_name})", datetime.now(MY_TIMEZONE).date(), key=date_key)
        
        with col_filters_2:
            search_key = f"search_{site_name}"
            search_term = st.text_input(f"🔍 Search SKU/Name", "", key=search_key)

        # Apply Search
        if search_term:
            site_df = site_df[
                site_df['product_name'].str.contains(search_term, case=False, na=False) | 
                site_df['sku'].str.contains(search_term, case=False, na=False)
            ]

        # Calculate Sales
        site_df = site_df.sort_values(by=['product_url', 'variant_id', 'timestamp'])
        site_df['diff'] = site_df.groupby(['product_url', 'variant_id'])['stock_count'].diff()
        
        sales_df = site_df[site_df['diff'] < 0].copy()
        
        if not sales_df.empty:
            sales_df['sales_count'] = sales_df['diff'].abs()
            sales_df['date'] = sales_df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(MY_TIMEZONE).dt.date
            
            daily_sales = sales_df[sales_df['date'] == selected_date]
            
            # Metrics
            c1, c2 = st.columns(2)
            c1.metric("Items Sold", int(daily_sales['sales_count'].sum()) if not daily_sales.empty else 0)
            c2.metric("Unique Products", daily_sales['product_name'].nunique() if not daily_sales.empty else 0)

            # Sales Table
            st.markdown(f"### 📦 Sales for {selected_date}")
            if not daily_sales.empty:
                report = daily_sales.groupby(['product_name', 'sku'])['sales_count'].sum().reset_index()
                report = report.sort_values(by='sales_count', ascending=False)
                
                st.dataframe(
                    report, 
                    column_config={
                        "product_name": "Product",
                        "sku": "SKU",
                        "sales_count": st.column_config.NumberColumn("Sold", format="%d")
                    },
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("No sales detected yet.")

        st.markdown("---")
        st.markdown("### 📈 Live Inventory")
        
        # Show latest stock
        latest_stock = site_df.sort_values('timestamp', ascending=False).drop_duplicates(subset=['product_url', 'variant_id'])
        
        st.dataframe(
            latest_stock[['timestamp', 'product_name', 'sku', 'stock_count', 'product_url']],
            column_config={
                "timestamp": st.column_config.DatetimeColumn("Last Check", format="HH:mm"),
                "product_url": st.column_config.LinkColumn("Link")
            },
            use_container_width=True,
            hide_index=True
        )