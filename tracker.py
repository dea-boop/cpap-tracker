import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import schedule
from datetime import datetime
import pandas as pd
import pytz
import re

# --- Configuration ---
BASE_URL = "https://www.cpapoutlet.ca"
COLLECTION_URL = "https://www.cpapoutlet.ca/collections/all"
DB_NAME = "inventory.db"
MY_TIMEZONE = pytz.timezone('US/Pacific')

# Headers to mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def init_db():
    """Initialize the SQLite database and handle upgrades."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Create table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            product_name TEXT,
            sku TEXT,
            product_url TEXT,
            variant_id TEXT,
            stock_count INTEGER
        )
    ''')
    
    # --- Auto-Migration: Add SKU column if it's missing ---
    # (This prevents errors if you are using an old database file)
    c.execute("PRAGMA table_info(inventory_log)")
    columns = [info[1] for info in c.fetchall()]
    if 'sku' not in columns:
        print("Upgrading database: Adding 'sku' column...")
        c.execute("ALTER TABLE inventory_log ADD COLUMN sku TEXT")
        
    conn.commit()
    conn.close()

def get_all_product_urls():
    """Crawls the 'All Products' collection to get a list of product URLs."""
    product_urls = set()
    page = 1
    
    print("Finding products...")
    while True:
        url = f"{COLLECTION_URL}?page={page}"
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
                    # Clean URL (remove query parameters)
                    full_url = BASE_URL + href.split('?')[0]
                    if full_url not in product_urls:
                        product_urls.add(full_url)
                        found_on_page += 1
            
            if found_on_page == 0:
                break
                
            print(f"  Found {found_on_page} products on page {page}...")
            page += 1
            time.sleep(1)
            
        except Exception as e:
            print(f"  Error scanning page {page}: {e}")
            break
            
    print(f"Total unique products found: {len(product_urls)}")
    return list(product_urls)

def check_inventory():
    """Main job: Scans all products and saves stock + SKU to DB."""
    run_time = datetime.now(MY_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{run_time}] Starting inventory scan...")
    
    urls = get_all_product_urls()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    items_added = 0
    
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # 1. Get Product Name
                title_tag = soup.find('h1')
                product_name = title_tag.text.strip() if title_tag else "Unknown Product"
                
                # 2. Get SKU (Try multiple strategies)
                sku = "N/A"
                
                # Strategy A: Look for class="sku" or "product-sku"
                sku_tag = soup.find(class_=re.compile(r'sku', re.I))
                if sku_tag:
                    # Clean up text (remove "SKU: " prefix if present)
                    sku = sku_tag.text.replace('SKU:', '').strip()
                
                # Strategy B: Look for text "SKU: XXXXX"
                if sku == "N/A":
                    sku_text_node = soup.find(string=re.compile(r'SKU:', re.I))
                    if sku_text_node:
                        sku = sku_text_node.replace('SKU:', '').strip()

                # 3. Get Stock Count
                stock_count = None
                variant_id = 'default'

                # Strategy A: Look for <variant-inventory> tag (ResMed style)
                inventory_tag = soup.find('variant-inventory')
                if inventory_tag:
                    span = inventory_tag.find('span')
                    if span and 'in stock' in span.text:
                        text = span.text.strip()
                        variant_id = span.get('data-variant-id', 'default')
                        stock_count = int(''.join(filter(str.isdigit, text)))

                # Strategy B: Look for ANY text saying "X in stock" (Universal fallback)
                if stock_count is None:
                    stock_text = soup.find(string=re.compile(r'\d+\s+in\s+stock'))
                    if stock_text:
                        numbers = re.findall(r'\d+', stock_text)
                        if numbers:
                            stock_count = int(numbers[0])
                
                # If we found stock, save it
                if stock_count is not None:
                    c.execute('''
                        INSERT INTO inventory_log (timestamp, product_name, sku, product_url, variant_id, stock_count)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (run_time, product_name, sku, url, variant_id, stock_count))
                    items_added += 1

            time.sleep(0.5) # Be polite
            
        except Exception as e:
            print(f"Error checking {url}: {e}")
            
    conn.commit()
    conn.close()
    print(f"[{run_time}] Scan complete. Added {items_added} inventory records.")

# --- Execution ---

if __name__ == "__main__":
    init_db()
    
    # Run once immediately to test
    check_inventory()
    
    # Schedule to run every hour
    schedule.every().hour.do(check_inventory)
    
    print("\nTracker is running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)