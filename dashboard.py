import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
from datetime import datetime, timedelta

# --- CONFIGURATION ---
DB_NAME = "inventory.db"

# --- FAVORITES (Pinned Products) ---
# Add partial names of products you want to watch closely here.
# The sidebar will have a checkbox to show ONLY these items.
FAVORITES = [
    "AirSense",
    "AirCurve",
    "DreamStation",
    "Mask",
    "P10",
    "F20"
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
    # 1. Fix Timestamps
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
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
    
    # Filter list if Favorites is checked
    if show_favs:
        # Filter products that match any string in the FAVORITES list (case insensitive)
        default_selection = [p for p in all_products if any(f.lower() in p.lower() for f in FAVORITES)]
    else:
        # Default to top 5 products if not filtering
        default_selection = all_products[:5]

    selected_products = st.sidebar.multiselect("Select Products", all_products, default=default_selection)

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

    # --- TAB 2: MOVERS (DAILY CHANGES) ---
    with tab2:
        st.subheader(f"Stock Changes (Last 7 Days) - {selected_site}")
        
        # Logic to calculate changes
        # We need the Latest Stock, Stock 24h ago, and Stock 7d ago for every product
        report_data = []
        
        # Get list of unique products for this site
        products_to_check = site_df['product_name'].unique()
        
        now = df['timestamp'].max()
        one_day_ago = now - timedelta(hours=24)
        seven_days_ago = now - timedelta(days=7)
        
        for product in products_to_check:
            p_data = site_df[site_df['product_name'] == product]
            if p_data.empty: continue
            
            # Get latest stock
            current_stock = p_data.iloc[-1]['stock_count']
            
            # Get stock ~24h ago (find closest timestamp)
            # We filter for records before the cutoff, then take the last one
            past_24h = p_data[p_data['timestamp'] <= one_day_ago]
            stock_24h = past_24h.iloc[-1]['stock_count'] if not past_24h.empty else current_stock
            
            # Get stock ~7d ago
            past_7d = p_data[p_data['timestamp'] <= seven_days_ago]
            stock_7d = past_7d.iloc[-1]['stock_count'] if not past_7d.empty else stock_24h # Fallback to 24h if 7d not avail
            
            change_24h = current_stock - stock_24h
            change_7d = current_stock - stock_7d
            
            # Only add to list if selected in sidebar (or if user wants to see all)
            # For this table, let's show ALL products unless the list is huge, 
            # but respecting the "Selected Products" makes it cleaner.
            if not selected_products or product in selected_products:
                report_data.append({
                    "Product": product,
                    "Current Stock": current_stock,
                    "24h Change": change_24h,
                    "7d Change": change_7d
                })
        
        # Create Dataframe
        change_df = pd.DataFrame(report_data)
        
        if not change_df.empty:
            # Sort by biggest absolute change in 24h
            change_df = change_df.sort_values("24h Change", ascending=True)
            
            # Styling function to highlight drops in red
            def color_negative_red(val):
                color = 'red' if val < 0 else 'green' if val > 0 else 'black'
                return f'color: {color}'

            st.dataframe(change_df.style.applymap(color_negative_red, subset=['24h Change', '7d Change']))
        else:
            st.info("Not enough data history to calculate changes yet.")

    # --- TAB 3: RAW DATA ---
    with tab3:
        st.subheader("Raw Data Log")
        st.dataframe(filtered_df.sort_values('timestamp', ascending=False))