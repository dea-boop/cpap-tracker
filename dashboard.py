import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from datetime import datetime, timedelta

# --- CONFIGURATION ---
DB_NAME = "inventory.db"

# --- FAVORITES (Pinned SKUs) ---
# The dashboard will look for these EXACT SKUs when you check the "Favorites" box.
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
    # 1. Fix Timestamps & Ensure SKUs are strings for matching
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    df['sku'] = df['sku'].astype(str)  
    df = df.sort_values('timestamp')

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filters")
    
    # Site Selector
    available_sites = df['site'].unique()
    selected_site = st.sidebar.selectbox("Select Competitor", available_sites, index=0)
    
    # Filter by site
    site_df = df[df['site'] == selected_site].copy()

    # Favorites Toggle
    show_favs = st.sidebar.checkbox("⭐ Show Favorites Only")
    
    # Product Selector logic
    all_products = sorted(site_df['product_name'].unique())
    
    # --- LOGIC UPDATE: Filter by SKU ---
    if show_favs:
        # Find product names that match the Favorite SKUs
        fav_products = site_df[site_df['sku'].isin(FAVORITE_SKUS)]['product_name'].unique()
        default_selection = list(fav_products)
        
        # Optional: If you want the dropdown to ONLY show favorites when checked:
        # options_list = sorted(list(fav_products))
        # But keeping all options is usually safer so you can add others if needed.
        options_list = all_products
    else:
        default_selection = all_products[:5]
        options_list = all_products

    selected_products = st.sidebar.multiselect("Select Products", options_list, default=default_selection)

    # Apply Product Filter
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
                    alt.Tooltip('sku', title='SKU'),
                    alt.Tooltip('stock_count', title='Stock')
                ]
            ).interactive()
            
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No matching products found for this site.")

    # --- TAB 2: MOVERS (DAILY CHANGES) ---
    with tab2:
        st.subheader(f"Stock Changes (Last 7 Days) - {selected_site}")
        
        report_data = []
        products_to_check = site_df['product_name'].unique()
        
        now = df['timestamp'].max()
        one_day_ago = now - timedelta(hours=24)
        seven_days_ago = now - timedelta(days=7)
        
        for product in products_to_check:
            p_data = site_df[site_df['product_name'] == product]
            if p_data.empty: continue
            
            # Get latest SKU for reference
            current_sku = p_data.iloc[-1]['sku']

            # Get latest stock
            current_stock = p_data.iloc[-1]['stock_count']
            
            # Get stock ~24h ago
            past_24h = p_data[p_data['timestamp'] <= one_day_ago]
            stock_24h = past_24h.iloc[-1]['stock_count'] if not past_24h.empty else current_stock
            
            # Get stock ~7d ago
            past_7d = p_data[p_data['timestamp'] <= seven_days_ago]
            stock_7d = past_7d.iloc[-1]['stock_count'] if not past_7d.empty else stock_24h
            
            change_24h = current_stock - stock_24h
            change_7d = current_stock - stock_7d
            
            # Filter Logic for Table:
            # If Favorites is checked, ONLY show rows matching the Favorite SKUs
            is_fav = str(current_sku) in FAVORITE_SKUS
            
            # Display if: (Favorites OFF AND Selected) OR (Favorites ON AND is_fav)
            if (not show_favs and (not selected_products or product in selected_products)) or \
               (show_favs and is_fav):
                
                report_data.append({
                    "Product": product,
                    "SKU": current_sku,
                    "Current Stock": current_stock,
                    "24h Change": int(change_24h),
                    "7d Change": int(change_7d)
                })
        
        change_df = pd.DataFrame(report_data)
        
        if not change_df.empty:
            change_df = change_df.sort_values("24h Change", ascending=True)
            st.dataframe(change_df, use_container_width=True)
        else:
            st.info("No data to display.")

    # --- TAB 3: RAW DATA ---
    with tab3:
        st.subheader("Raw Data Log")
        st.dataframe(filtered_df.sort_values('timestamp', ascending=False))