import streamlit as st
import sqlite3
import pandas as pd
import altair as alt

# --- CONFIGURATION ---
DB_NAME = "inventory.db"

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
    # --- THE FIX: Handle mixed time formats (clean and microseconds) ---
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    
    # Sort by time
    df = df.sort_values('timestamp')

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filters")
    
    # 1. Site Selector
    available_sites = df['site'].unique()
    selected_site = st.sidebar.selectbox("Select Competitor", available_sites, index=0)
    
    # Filter data by site
    site_df = df[df['site'] == selected_site].copy()

    # 2. Product Selector (Dynamic based on Site)
    all_products = site_df['product_name'].unique()
    selected_products = st.sidebar.multiselect("Select Products", all_products, default=all_products[:5])

    # --- MAIN DASHBOARD ---
    
    # Filter by products
    if selected_products:
        filtered_df = site_df[site_df['product_name'].isin(selected_products)]
    else:
        filtered_df = site_df

    # Create Tabs
    tab1, tab2 = st.tabs(["📉 Stock History", "📋 Raw Data"])

    with tab1:
        st.subheader(f"Inventory Levels: {selected_site}")
        
        # Area Chart
        chart = alt.Chart(filtered_df).mark_line(point=True).encode(
            x=alt.X('timestamp:T', title='Time'),
            y=alt.Y('stock_count:Q', title='Stock Level'),
            color='product_name:N',
            tooltip=['timestamp', 'product_name', 'stock_count']
        ).interactive()
        
        st.altair_chart(chart, use_container_width=True)

    with tab2:
        st.subheader("Recent Scans")
        st.dataframe(filtered_df.sort_values('timestamp', ascending=False))