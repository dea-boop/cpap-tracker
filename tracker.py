import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import schedule
from datetime import datetime
import pandas as pd
import pytz
import re
import json

# --- Configuration ---
DB_NAME = "inventory.db"
MY_TIMEZONE = pytz.timezone('US/Pacific')

# Site A: CPAP Outlet
SITE_A_BASE = "https://www.cpapoutlet.ca"
SITE_A_COLLECTION = "https://www.cpapoutlet.ca/collections/all"

# Site B: Airvoel
SITE_B_BASE = "https://airvoel.ca"
SITE_B_COLLECTION = "https://airvoel.ca/collections/all"
SITE_B_GRAPHQL_URL = "https://airvoel.ca/api/2023-01/graphql.json" # Common Shopify Endpoint

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Create table
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            site TEXT,
            product_name TEXT,
            sku TEXT,
            product_url TEXT,
            variant_id TEXT,
            stock_count INTEGER
        )
    ''')
    
    # --- Auto-Migration: Add 'site' column if missing ---
    c.execute("PRAGMA table_info(inventory_log)")
    columns = [info[1] for info in c.fetchall()]
    
    if 'site' not in columns:
        print("Upgrading database: Adding 'site' column...")
        c.execute("ALTER TABLE inventory_log ADD COLUMN site TEXT")
        c.execute("UPDATE inventory_log SET site = 'CPAP Outlet' WHERE site IS NULL")

    # Add 'sku' if missing (from previous update)
    if 'sku' not in columns:
        c.execute("ALTER TABLE inventory_log ADD COLUMN sku TEXT")

    conn.commit()
    conn.close()

def get_product_urls(collection_url, base_url):
    """Generic crawler to get all product URLs from a Shopify collection."""
    product_urls = set()
    page = 1
    print(f"  Crawling {base_url}...")
    
    while True:
        url = f"{collection_url}?page={page}"
        try:
            r = requests.get(url, headers=HEADERS)
            if r.status_code != 200:
                break
            
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', href=True)
            found_on_page = 0
            
            for link in links:
                href = link['href']
                if '/products/' in href:
                    full_url = base_url + href.split('?')[0]
                    if full_url not in product_urls:
                        product_urls.add(full_url)
                        found_on_page += 1
            
            if found_on_page == 0:
                break
            page += 1
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break
            
    print(f"  Found {len(product_urls)} products.")
    return list(product_urls)

# --- SITE A LOGIC (HTML Scraper) ---
def scan_cpap_outlet(run_time, conn):
    print("--- Scanning CPAP Outlet ---")
    urls = get_product_urls(SITE_A_COLLECTION, SITE_A_BASE)
    c = conn.cursor()
    items_added = 0
    
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.find('h1').text.strip() if soup.find('h1') else "Unknown"
                
                # SKU
                sku = "N/A"
                sku_tag = soup.find(class_=re.compile(r'sku', re.I))
                if sku_tag: sku = sku_tag.text.replace('SKU:', '').strip()
                
                # Stock (HTML Tag Strategy)
                stock_count = None
                variant_id = 'default'
                
                # Strategy 1: <variant-inventory> tag
                tag = soup.find('variant-inventory')
                if tag and tag.find('span') and 'in stock' in tag.find('span').text:
                    stock_count = int(''.join(filter(str.isdigit, tag.find('span').text)))
                    if tag.find('span').get('data-variant-id'):
                        variant_id = tag.find('span').get('data-variant-id')

                # Strategy 2: Regex Fallback
                if stock_count is None:
                    stock_text = soup.find(string=re.compile(r'\d+\s+in\s+stock'))
                    if stock_text:
                        stock_count = int(re.findall(r'\d+', stock_text)[0])

                if stock_count is not None:
                    c.execute('''INSERT INTO inventory_log (timestamp, site, product_name, sku, product_url, variant_id, stock_count)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                                 (run_time, "CPAP Outlet", title, sku, url, variant_id, stock_count))
                    items_added += 1
            time.sleep(0.2)
        except Exception: pass
        
    print(f"  CPAP Outlet: Saved {items_added} records.")

# --- SITE B LOGIC (GraphQL Sniper) ---
def get_airvoel_token():
    """Tries to scrape the public Storefront Access Token from the homepage."""
    try:
        r = requests.get(SITE_B_BASE, headers=HEADERS)
        # Look for "accessToken":"kb123..." pattern common in Shopify JS
        match = re.search(r'"accessToken":"([a-zA-Z0-9]+)"', r.text)
        if match: return match.group(1)
        
        # Fallback: Look for specific meta tags
        match = re.search(r'access_token: "([a-zA-Z0-9]+)"', r.text)
        if match: return match.group(1)
        
    except Exception: pass
    return None

def scan_airvoel(run_time, conn):
    print("--- Scanning Airvoel ---")
    
    # 1. Get Token
    token = get_airvoel_token()
    if not token:
        print("  ❌ Could not find Airvoel API Token. Skipping scan.")
        return

    # 2. Get Product Handles
    urls = get_product_urls(SITE_B_COLLECTION, SITE_B_BASE)
    c = conn.cursor()
    items_added = 0
    
    # 3. Setup GraphQL Query
    gql_url = f"{SITE_B_BASE}/api/2023-01/graphql.json"
    gql_headers = HEADERS.copy()
    gql_headers['X-Shopify-Storefront-Access-Token'] = token
    gql_headers['Content-Type'] = 'application/json'

    query = """
    query product($handle: String!) {
      product(handle: $handle) {
        id
        title
        totalInventory
        variants(first: 5) {
          nodes {
            id
            sku
            quantityAvailable
            title
          }
        }
      }
    }
    """

    for url in urls:
        handle = url.split('/')[-1] # Extract 'resmed-airmini' from URL
        try:
            payload = {'query': query, 'variables': {'handle': handle}}
            r = requests.post(gql_url, json=payload, headers=gql_headers)
            
            if r.status_code == 200:
                data = r.json().get('data', {}).get('product')
                if data:
                    title = data.get('title')
                    # We can iterate over variants to get precise SKU/stock
                    for variant in data.get('variants', {}).get('nodes', []):
                        v_title = variant.get('title')
                        sku = variant.get('sku') or "N/A"
                        qty = variant.get('quantityAvailable')
                        vid = variant.get('id', '').split('/')[-1]
                        
                        # Full name includes variant (e.g., "Mask - Small")
                        full_name = f"{title} ({v_title})" if v_title != 'Default Title' else title
                        
                        if qty is not None:
                            c.execute('''INSERT INTO inventory_log (timestamp, site, product_name, sku, product_url, variant_id, stock_count)
                                         VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                                         (run_time, "Airvoel", full_name, sku, url, vid, qty))
                            items_added += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"Error checking {handle}: {e}")

    print(f"  Airvoel: Saved {items_added} records.")


def job():
    run_time = datetime.now(MY_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{run_time}] Starting Global Scan...")
    
    conn = sqlite3.connect(DB_NAME)
    scan_cpap_outlet(run_time, conn)
    scan_airvoel(run_time, conn)
    conn.commit()
    conn.close()
    print(f"[{run_time}] Global Scan Complete.")

if __name__ == "__main__":
    init_db()
    
    # Run once immediately
    job()
    
    schedule.every().hour.do(job)
    
    print("\nMulti-Site Tracker is running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)