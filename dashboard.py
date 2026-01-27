import streamlit as st
import pandas as pd
import sqlite3
import pytz
from datetime import datetime

# Config
DB_NAME = "inventory.db"
MY_TIMEZONE = pytz.timezone('US/Pacific')

st.set_page_config(page_title="CPAP Inventory Tracker", layout="wide")

def load_data():
    try:
        conn = sqlite3.connect(DB_NAME)
        # We select SKU as well now
        df = pd.read_sql_query("SELECT * FROM inventory_log", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

st.title("📊 CPAP Outlet Inventory Tracker")

# Load Data
df = load_data()

if df.empty:
    st.warning("Database is empty. The tracker hasn't saved any data yet.")
else:
    # Process Data
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filters")
    
    # Date Picker
    selected_date = st.sidebar.date_input("Select Date", datetime.now(MY_TIMEZONE).date())
    
    # Search Box (Filters by Name or SKU)
    search_term = st.sidebar.text_input("🔍 Search (SKU or Name)", "")

    # Apply Search Filter to the main dataframe
    if search_term:
        # Filter if SKU or Product Name contains the search term (case insensitive)
        df = df[
            df['product_name'].str.contains(search_term, case=False, na=False) | 
            df['sku'].str.contains(search_term, case=False, na=False)
        ]

    # Show Raw Data Stats
    st.markdown(f"**Total Scans Recorded:** {len(df)}")
    st.markdown(f"**Unique Products Tracked:** {df['product_url'].nunique()}")

    # Sort and Calculate Sales (Diff)
    # We sort by URL/Variant to track changes over time
    df = df.sort_values(by=['product_url', 'variant_id', 'timestamp'])
    df['diff'] = df.groupby(['product_url', 'variant_id'])['stock_count'].diff()
    
    # Filter for Sales (Negative drops only)
    sales_df = df[df['diff'] < 0].copy()
    
    if not sales_df.empty:
        sales_df['sales_count'] = sales_df['diff'].abs()
        sales_df['date'] = sales_df['timestamp'].dt.tz_localize('UTC').dt.tz_convert(MY_TIMEZONE).dt.date
        
        # Filter sales by the selected date
        daily_sales = sales_df[sales_df['date'] == selected_date]
        
        # -- METRICS ROW --
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Items Sold Today", int(daily_sales['sales_count'].sum()) if not daily_sales.empty else 0)
        with col2:
            st.metric("Unique Products Sold", daily_sales['product_name'].nunique() if not daily_sales.empty else 0)

        # -- TOP SELLING TABLE --
        st.markdown(f"### 📦 Sales for {selected_date}")
        if not daily_sales.empty:
            # Group by product AND SKU to sum sales
            report = daily_sales.groupby(['product_name', 'sku'])['sales_count'].sum().reset_index()
            report = report.sort_values(by='sales_count', ascending=False)
            
            # Display Table with SKU column
            st.dataframe(
                report, 
                column_config={
                    "product_name": "Product Name",
                    "sku": "SKU",
                    "sales_count": st.column_config.NumberColumn("Items Sold", format="%d")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info(f"No sales detected yet for {selected_date} (Wait for the next hourly scan!)")
    else:
        st.info("No sales detected yet. (This is normal! We need at least 2 scans to calculate drops.)")

    st.markdown("---")
    st.markdown("### 📈 Latest Inventory Checks (Raw Data)")
    
    # Show the raw log with the SKU column
    display_df = df.sort_values(by='timestamp', ascending=False)
    
    st.dataframe(
        display_df,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Time Scanned", format="D MMM, HH:mm"),
            "product_name": "Product Name",
            "sku": "SKU",
            "stock_count": "Stock Level",
            "product_url": st.column_config.LinkColumn("Product Link")
        },
        use_container_width=True,
        hide_index=True
    )
    