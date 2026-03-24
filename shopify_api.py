import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

try:
    import streamlit as st
    STORE = st.secrets.get("SHOPIFY_STORE") or os.getenv("SHOPIFY_STORE")
    TOKEN = st.secrets.get("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_ACCESS_TOKEN")
except Exception:
    STORE = os.getenv("SHOPIFY_STORE")
    TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")
API_VERSION = "2024-01"
BASE_URL = f"https://{STORE}/admin/api/{API_VERSION}"
TULLAMARINE_ID = 78206304573

HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json"
}

def get_products():
    products = []
    url = f"{BASE_URL}/products.json?limit=250&fields=id,title,variants,product_type,tags,status"
    while url:
        r = requests.get(url, headers=HEADERS)
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return products

def get_inventory_levels():
    """Get inventory levels at Tullamarine only"""
    all_levels = {}
    url = f"{BASE_URL}/inventory_levels.json?location_ids={TULLAMARINE_ID}&limit=250"
    while url:
        r = requests.get(url, headers=HEADERS)
        for level in r.json().get("inventory_levels", []):
            inv_id = level["inventory_item_id"]
            qty = level.get("available", 0) or 0
            all_levels[inv_id] = qty
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return all_levels  # {inventory_item_id: qty}

def get_orders_last_90_days():
    since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    orders = []
    url = f"{BASE_URL}/orders.json?status=any&created_at_min={since}&limit=250&fields=id,line_items,created_at,financial_status,cancel_reason"
    while url:
        r = requests.get(url, headers=HEADERS)
        orders.extend(r.json().get("orders", []))
        link = r.headers.get("Link", "")
        url = next((p.split(";")[0].strip().strip("<>") for p in link.split(",") if 'rel="next"' in p), None)
    return orders

def get_purchase_orders():
    """Get open purchase orders - try multiple endpoints"""
    # Try GraphQL inventoryOrder
    query = """
    {
      purchaseOrders: draftOrders(first: 50, query: "status:open") {
        edges {
          node {
            id
            name
            lineItems(first: 100) {
              edges {
                node {
                  variant { id sku }
                  quantity
                }
              }
            }
          }
        }
      }
    }
    """
    # Try REST - Inventory Orders (the actual PO feature)
    r = requests.get(
        f"https://{STORE}/admin/api/{API_VERSION}/inventory_orders.json?status=open&limit=250",
        headers=HEADERS
    )
    if r.status_code == 200:
        pos = r.json().get("inventory_orders", [])
        if pos:
            return pos

    # Try newer API version for purchase orders
    r2 = requests.get(
        f"https://{STORE}/admin/api/2024-04/purchase_orders.json?status=open&limit=250",
        headers=HEADERS
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
