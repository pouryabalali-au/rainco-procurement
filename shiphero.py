import requests
import os
from dotenv import load_dotenv

load_dotenv()

GQL = "https://public-api.shiphero.com/graphql"
RAINCO_VENDOR_ID = "VmVuZG9yOjExOTgzNzI="

def _token():
    try:
        import streamlit as st
        key    = st.secrets["SHIPHERO_KEY"]
        secret = st.secrets["SHIPHERO_SECRET"]
        email  = st.secrets["SHIPHERO_EMAIL"]
        pw     = st.secrets["SHIPHERO_PASSWORD"]
    except Exception:
        key    = os.getenv("SHIPHERO_KEY")
        secret = os.getenv("SHIPHERO_SECRET")
        email  = os.getenv("SHIPHERO_EMAIL")
        pw     = os.getenv("SHIPHERO_PASSWORD")
    r = requests.post(
        "https://public-api.shiphero.com/auth/token",
        json={"grant_type": "password", "username": email, "password": pw,
              "client_id": key, "client_secret": secret}
    )
    return r.json().get("access_token")

def push_po_to_shiphero(order_rows: list, po_number: str) -> dict:
    """
    Push a purchase order to ShipHero under the RainCo vendor.
    order_rows: list of dicts with keys: sku, rec_order, cost_usd
    Returns: {"success": bool, "po_number": str, "error": str}
    """
    token = _token()
    if not token:
        return {"success": False, "error": "Could not authenticate with ShipHero"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Build line items
    line_items = []
    for row in order_rows:
        sku = row.get("sku", "")
        qty = int(row.get("rec_order", 0))
        cost = float(row.get("cost_usd") or 0)
        if sku and qty > 0:
            line_items.append({
                "sku": sku,
                "quantity": qty,
                "price": round(cost, 2),
            })

    if not line_items:
        return {"success": False, "error": "No valid line items to order"}

    # Format line items for GraphQL
    li_str = ""
    for li in line_items:
        li_str += f'{{ sku: "{li["sku"]}", quantity: {li["quantity"]}, price: "{li["price"]}" }}\n'

    mutation = f'''
    mutation {{
      purchase_order_create(data: {{
        po_number: "{po_number}"
        vendor_id: "{RAINCO_VENDOR_ID}"
        line_items: [
          {li_str}
        ]
      }}) {{
        request_id
        data {{
          id
          po_number
          fulfillment_status
        }}
      }}
    }}
    '''

    r = requests.post(GQL, json={"query": mutation}, headers=headers)
    data = r.json()

    if "errors" in data:
        return {"success": False, "error": data["errors"][0]["message"]}

    po_data = data.get("data", {}).get("purchase_order_create", {}).get("data", {})
    if po_data:
        return {"success": True, "po_number": po_data.get("po_number", po_number)}

    return {"success": False, "error": "Unexpected response from ShipHero"}
