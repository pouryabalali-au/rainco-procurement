import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

API_VERSION = "2024-01"
TULLAMARINE_ID = 78206304573

def _get_creds():
    try:
        import streamlit as st
        store = st.secrets["SHOPIFY_STORE"]
        token = st.secrets["SHOPIFY_ACCESS_TOKEN"]
    except Exception:
        store = os.getenv("SHOPIFY_STORE")
        token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    return store, token

def _headers():
    _, token = _get_creds()
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

def _base_url():
    store, _ = _get_creds()
    return f"https://{store}/admin/api/{API_VERSION}"

def get_products():
    products = []
    url = f"{_base_url()}/products.json?limit=250&fields=id,title,vendor,variants,product_type,tags,status"
    while url:
        r = requests.get(url, headers=_headers())
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return products

def get_inventory_costs(products):
    """Fetch cost price (USD) per inventory_item_id in batches of 100"""
    inv_ids = [
        v["inventory_item_id"]
        for p in products
        for v in p.get("variants", [])
        if v.get("inventory_item_id")
    ]
    costs = {}
    for i in range(0, len(inv_ids), 100):
        batch = inv_ids[i:i+100]
        ids_str = ",".join(str(x) for x in batch)
        r = requests.get(
            f"{_base_url()}/inventory_items.json?ids={ids_str}&limit=100",
            headers=_headers()
        )
        for item in r.json().get("inventory_items", []):
            cost = item.get("cost")
            if cost is not None:
                costs[item["id"]] = float(cost)
    return costs  # {inventory_item_id: cost_usd}

def get_usd_to_aud_rate():
    """Fetch live USD→AUD exchange rate"""
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
        return r.json()["rates"]["AUD"]
    except Exception:
        return 1.58  # fallback rate

def get_inventory_levels():
    """Get inventory levels at Tullamarine only"""
    all_levels = {}
    url = f"{_base_url()}/inventory_levels.json?location_ids={TULLAMARINE_ID}&limit=250"
    while url:
        r = requests.get(url, headers=_headers())
        for level in r.json().get("inventory_levels", []):
            inv_id = level["inventory_item_id"]
            qty = level.get("available", 0) or 0
            all_levels[inv_id] = qty
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return all_levels

def get_orders_last_90_days():
    since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    orders = []
    url = f"{_base_url()}/orders.json?status=any&created_at_min={since}&limit=250&fields=id,line_items,created_at,financial_status,cancel_reason"
    while url:
        r = requests.get(url, headers=_headers())
        orders.extend(r.json().get("orders", []))
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return orders

def get_purchase_orders():
    """Get open purchase orders"""
    store, _ = _get_creds()
    r = requests.get(
        f"https://{store}/admin/api/{API_VERSION}/inventory_orders.json?status=open&limit=250",
        headers=_headers()
    )
    if r.status_code == 200:
        pos = r.json().get("inventory_orders", [])
        if pos:
            return pos
    r2 = requests.get(
        f"https://{store}/admin/api/2024-04/purchase_orders.json?status=open&limit=250",
        headers=_headers()
    )
    if r2.status_code == 200:
        pos2 = r2.json().get("purchase_orders", [])
        if pos2:
            return pos2
    return []

def build_sales_by_variant(orders):
    """Count units sold per variant_id in last 90 days, excluding cancelled/refunded"""
    sales = {}
    for order in orders:
        if order.get("financial_status") in ["voided", "refunded"] or order.get("cancel_reason"):
            continue
        for item in order.get("line_items", []):
            vid = item.get("variant_id")
            qty = item.get("quantity", 0)
            if vid:
                sales[vid] = sales.get(vid, 0) + qty
    return sales

def build_on_order_by_sku(purchase_orders):
    """Count outstanding units per SKU from open POs"""
    on_order = {}
    for po in purchase_orders:
        for item in po.get("line_items", []):
            sku = item.get("variant_sku") or item.get("sku", "")
            ordered = item.get("quantity", 0)
            received = item.get("received_quantity", 0)
            outstanding = ordered - received
            if sku and outstanding > 0:
                on_order[sku] = on_order.get(sku, 0) + outstanding
    return on_order

if __name__ == "__main__":
    print("🔌 Testing Shopify API (Tullamarine only)...\n")

    print("📦 Fetching inventory levels at Tullamarine...")
    inv = get_inventory_levels()
    non_zero = {k: v for k, v in inv.items() if v > 0}
    print(f"   Total tracked items: {len(inv)}, Non-zero stock: {len(non_zero)}")

    print("\n📋 Fetching purchase orders...")
    pos = get_purchase_orders()
    print(f"   Purchase orders found: {len(pos)}")

    print("\n🛒 Fetching orders (last 90 days)...")
    orders = get_orders_last_90_days()
    sales = build_sales_by_variant(orders)
    print(f"   Total orders: {len(orders)}, Variants with sales: {len(sales)}")
    top5 = sorted(sales.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"   Top 5 variant IDs by units sold: {top5}")

    print("\n🏷️  Fetching products...")
    products = get_products()
    total_variants = sum(len(p["variants"]) for p in products)
    print(f"   Products: {len(products)}, Total variants: {total_variants}")
