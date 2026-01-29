import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from datetime import datetime, timedelta

# --- CONFIGURATION ---
DB_NAME = "inventory.db"

# --- FAVORITES (Pinned SKUs) ---
FAVORITE_SKUS = [
    "39007",   # AirSense 11
    "38113",   # AirMini
    "62900",   # AirFit P10
    "63801",   # AirFit F20
    "63850",
    "506001",
    "37403",
    "37382"
]

st.set_page_config(page_title="CPAP Inventory Tracker", layout="wide")
st.title("📊 CPAP Inventory Tracker")

# --- LOAD DATA ---
def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM inventory_log", conn)
    conn.close()
    return df

df = load_data()

if df.empty:
    st.warning("No data found yet. The tracker is running...")
else:
    # 1. Fix Timestamps & SKUs
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    df['sku'] = df['sku'].astype(str)
    df = df.sort_values('timestamp')

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filters")
    
    available_sites = df['site'].unique()
    selected_site = st.sidebar.selectbox("Select Competitor", available_sites, index=0)
    
    site_df = df[df['site'] == selected_site].copy()

    show_favs = st.sidebar.checkbox("⭐ Show Favorites Only")
    
    all_products = sorted(site_df['product_name'].unique())
    
    # Filter Logic
    if show_favs:
        fav_products = site_df[site_df['sku'].isin(FAVORITE_SKUS)]['product_name'].unique()
        options_list = all_products # Keep all visible in dropdown if needed
        default_selection = list(fav_products)
    else:
        default_selection = all_products[:5]
        options_list = all_products

    selected_products = st.sidebar.multiselect("Select Products", options_list, default=default_selection)

    # Apply Filter
    if selected_products:
        filtered_df = site_df[site_df['product_name'].isin(selected_products)]
    else:
        filtered_df = site_df

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📉 Stock History", "📊 Daily Changes", "📋 Raw Data"])

    # --- TAB 1: CHART ---
    with tab1:
        st.subheader(f"Inventory History: {selected_site}")
        if not filtered_df.empty:
            chart = alt.Chart(filtered_df).mark_line(point=True).encode(
                x=alt.X('timestamp:T', title='Date & Time', axis=alt.Axis(format='%b %d %H:%M')),
                y=alt.Y('stock_count:Q', title='Stock Level'),
                color='product_name:N',
                tooltip=[
                    alt.Tooltip('timestamp', title='Time', format='%b %d %H:%M'),
                    alt.Tooltip('product_name', title='Product'),
                    alt.Tooltip('stock_count', title='Stock')
                ]
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No matching products found.")

    # --- TAB 2: MOVERS (UPDATED LOGIC) ---
    with tab2:
        st.subheader(f"Inventory Changes - {selected_site}")
        
        report_data = []
        products_to_check = site_df['product_name'].unique()
        
        # Time Reference Points
        now = df['timestamp'].max()
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_yesterday = midnight_today - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)
        
        for product in products_to_check:
            p_data = site_df[site_df['product_name'] == product].sort_values('timestamp')
            if p_data.empty: continue
            
            # 1. Current Stock (Latest)
            current_stock = p_data.iloc[-1]['stock_count']
            current_sku = p_data.iloc[-1]['sku']

            # 2. Stock at Start of Today (Midnight)
            # Find the last record BEFORE or AT midnight today. 
            # If no record exists before midnight today, we use the FIRST record of today.
            recs_before_today = p_data[p_data['timestamp'] <= midnight_today]
            if not recs_before_today.empty:
                stock_today_open = recs_before_today.iloc[-1]['stock_count']
            else:
                # If they started tracking at 10am today, "Start of Day" is that 10am record.
                stock_today_open = p_data.iloc[0]['stock_count']
            
            # 3. Stock at Start of Yesterday (Midnight Yesterday)
            recs_before_yesterday = p_data[p_data['timestamp'] <= midnight_yesterday]
            if not recs_before_yesterday.empty:
                stock_yesterday_open = recs_before_yesterday.iloc[-1]['stock_count']
            else:
                # If data doesn't go back that far, "Yesterday's Change" is N/A or 0
                stock_yesterday_open = None

            # 4. Stock 7 Days Ago
            # logic: If we have data > 7 days, take that.
            # If NOT, take the OLDEST record available (start of tracking).
            recs_7d = p_data[p_data['timestamp'] <= seven_days_ago]
            if not recs_7d.empty:
                stock_7d = recs_7d.iloc[-1]['stock_count']
            else:
                stock_7d = p_data.iloc[0]['stock_count']

            # Calculations
            change_today = current_stock - stock_today_open
            
            if stock_yesterday_open is not None:
                change_yesterday = stock_today_open - stock_yesterday_open
            else:
                change_yesterday = 0 # or None

            change_7d = current_stock - stock_7d
            
            # Filter Logic (Show favorites or selected)
            is_fav = str(current_sku) in FAVORITE_SKUS
            should_show = (not show_favs and (not selected_products or product in selected_products)) or \
                          (show_favs and is_fav)

            if should_show:
                report_data.append({
                    "Product": product,
                    "SKU": current_sku,
                    "Current": current_stock,
                    "Today's Change": int(change_today),
                    "Yesterday's Change": int(change_yesterday),
                    "7d Change": int(change_7d)
                })
        
        change_df = pd.DataFrame(report_data)
        
        if not change_df.empty:
            # Sort by Today's Change (Biggest drops first)
            change_df = change_df.sort_values("Today's Change", ascending=True)
            st.dataframe(change_df, use_container_width=True)
        else:
            st.info("No data available.")

    # --- TAB 3: RAW DATA ---
    with tab3:
        st.subheader("Raw Data Log")
        st.dataframe(filtered_df.sort_values('timestamp', ascending=False))