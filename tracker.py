import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import schedule
from datetime import datetime
import pytz
import re

# --- CONFIGURATION ---
DB_NAME = "inventory.db"
# FORCE VANCOUVER TIME
MY_TIMEZONE = pytz.timezone('US/Pacific')

# Site A: CPAP Outlet
SITE_A_BASE = "https://www.cpapoutlet.ca"
SITE_A_COLLECTION = "https://www.cpapoutlet.ca/collections/all"

# Site B: Airvoel
SITE_B_BASE = "https://airvoel.ca"
AIRVOEL_TOKEN = "d13c4ed1a6015418d712cc6bf6cd8cba"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
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
    c.execute("PRAGMA table_info(inventory_log)")
    columns = [info[1] for info in c.fetchall()]
    if 'site' not in columns:
        c.execute("ALTER TABLE inventory_log ADD COLUMN site TEXT")
        c.execute("UPDATE inventory_log SET site = 'CPAP Outlet' WHERE site IS NULL")
    if 'sku' not in columns:
        c.execute("ALTER TABLE inventory_log ADD COLUMN sku TEXT")
    conn.commit()
    conn.close()

# --- SITE A: CPAP OUTLET ---
def get_cpap_urls():
    product_urls = set()
    page = 1
    print(f"  Crawling {SITE_A_BASE}...")
    while True:
        url = f"{SITE_A_COLLECTION}?page={page}"
        try:
            r = requests.get(url, headers=HEADERS)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', href=True)
            found_on_page = 0
            for link in links:
                href = link['href']
                if '/products/' in href:
                    full_url = SITE_A_BASE + href.split('?')[0]
                    if full_url not in product_urls:
                        product_urls.add(full_url)
                        found_on_page += 1
            if found_on_page == 0: break
            page += 1
            time.sleep(0.5)
        except Exception: break
    return list(product_urls)

def scan_cpap_outlet(run_time, conn):
    print("--- Scanning CPAP Outlet ---")
    urls = get_cpap_urls()
    c = conn.cursor()
    items_added = 0
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.find('h1').text.strip() if soup.find('h1') else "Unknown"
                sku = "N/A"
                sku_tag = soup.find(class_=re.compile(r'sku', re.I))
                if sku_tag: sku = sku_tag.text.replace('SKU:', '').strip()
                
                stock_count = None
                variant_id = 'default'
                tag = soup.find('variant-inventory')
                if tag and tag.find('span') and 'in stock' in tag.find('span').text:
                    stock_count = int(''.join(filter(str.isdigit, tag.find('span').text)))
                    if tag.find('span').get('data-variant-id'):
                        variant_id = tag.find('span').get('data-variant-id')

                if stock_count is None:
                    stock_text = soup.find(string=re.compile(r'\d+\s+in\s+stock'))
                    if stock_text: stock_count = int(re.findall(r'\d+', stock_text)[0])

                if stock_count is not None:
                    c.execute('''INSERT INTO inventory_log (timestamp, site, product_name, sku, product_url, variant_id, stock_count)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)''', (run_time, "CPAP Outlet", title, sku, url, variant_id, stock_count))
                    items_added += 1
            time.sleep(0.2)
        except Exception: pass
    print(f"  CPAP Outlet: Saved {items_added} records.")

# --- SITE B: AIRVOEL ---
def scan_airvoel(run_time, conn):
    print("--- Scanning Airvoel ---")
    c = conn.cursor()
    items_added = 0
    
    gql_url = f"{SITE_B_BASE}/api/2023-01/graphql.json"
    headers = HEADERS.copy()
    headers['X-Shopify-Storefront-Access-Token'] = AIRVOEL_TOKEN
    headers['Content-Type'] = 'application/json'

    query = """
    query GetCollection($cursor: String) {
      products(first: 250, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          title
          handle
          variants(first: 5) {
            nodes {
              id
              sku
              title
              quantityAvailable
            }
          }
        }
      }
    }
    """

    cursor = None
    has_next_page = True
    page_num = 1

    while has_next_page:
        print(f"  Fetching Page {page_num}...")
        try:
            payload = {'query': query, 'variables': {'cursor': cursor}}
            r = requests.post(gql_url, json=payload, headers=headers)
            if r.status_code != 200: break
            data = r.json().get('data', {}).get('products', {})
            products = data.get('nodes', [])
            if not products: break

            for p in products:
                title = p.get('title')
                handle = p.get('handle')
                url = f"{SITE_B_BASE}/products/{handle}"
                for v in p.get('variants', {}).get('nodes', []):
                    v_title = v.get('title')
                    sku = v.get('sku') or "N/A"
                    qty = v.get('quantityAvailable')
                    vid = v.get('id', '').split('/')[-1]
                    full_name = f"{title} ({v_title})" if v_title != 'Default Title' else title
                    
                    if qty is not None:
                        c.execute('''INSERT INTO inventory_log (timestamp, site, product_name, sku, product_url, variant_id, stock_count)
                                     VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                                     (run_time, "Airvoel", full_name, sku, url, vid, qty))
                        items_added += 1

            has_next_page = data.get('pageInfo', {}).get('hasNextPage', False)
            cursor = data.get('pageInfo', {}).get('endCursor')
            page_num += 1
            time.sleep(1)
        except Exception: break
    print(f"  Airvoel: Scan Complete. Saved {items_added} records.")

def job():
    # Force Pacific Time here
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
    job()
    schedule.every().hour.do(job)
    while True:
        schedule.run_pending()
        time.sleep(60)