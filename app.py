import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import os
from datetime import datetime
from shopify_api import (
    get_products, get_inventory_levels, get_orders_last_90_days,
    get_purchase_orders, build_sales_by_variant, build_on_order_by_sku
)
from calculations import calculate_procurement

st.set_page_config(
    page_title="RainCo Procurement",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject CSS via component (most reliable method)
components.html("""
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --green: #344d47;
    --green-dark: #263a35;
    --black: #1c1c1c;
    --white: #ffffff;
    --off-white: #f8f8f6;
    --border: #dddddd;
  }
</style>
<script>
  // Inject fonts + styles into parent Streamlit frame
  const parent = window.parent.document;
  if (!parent.getElementById('rainco-styles')) {
    const link = parent.createElement('link');
    link.id = 'rainco-fonts';
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=Poppins:wght@300;400;500&display=swap';
    parent.head.appendChild(link);

    const style = parent.createElement('style');
    style.id = 'rainco-styles';
    style.textContent = `
      html, body, [class*="css"] {
        font-family: 'Poppins', sans-serif !important;
        font-weight: 300;
      }
      h1, h2, h3 {
        font-family: 'Playfair Display', serif !important;
        font-weight: 400 !important;
        letter-spacing: 0.05em !important;
        color: #1c1c1c !important;
      }
      section[data-testid="stSidebar"] {
        background-color: #f8f8f6 !important;
        border-right: 1px solid #dddddd !important;
      }
      div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #344d47 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 0 !important;
        font-family: 'Poppins', sans-serif !important;
        font-size: 0.75rem !important;
        font-weight: 400 !important;
        letter-spacing: 0.12em !important;
        text-transform: uppercase !important;
      }
      div[data-testid="stButton"] > button[kind="primary"]:hover {
        background-color: #263a35 !important;
      }
      div[data-testid="stButton"] > button:not([kind="primary"]),
      div[data-testid="stDownloadButton"] > button {
        background-color: transparent !important;
        color: #344d47 !important;
        border: 1px solid #344d47 !important;
        border-radius: 0 !important;
        font-family: 'Poppins', sans-serif !important;
        font-size: 0.75rem !important;
        font-weight: 400 !important;
        letter-spacing: 0.12em !important;
        text-transform: uppercase !important;
      }
      div[data-testid="stButton"] > button:not([kind="primary"]):hover,
      div[data-testid="stDownloadButton"] > button:hover {
        background-color: #344d47 !important;
        color: #ffffff !important;
      }
      div[data-testid="stMetric"] {
        background-color: #f8f8f6 !important;
        border: 1px solid #dddddd !important;
        padding: 1rem 1.2rem !important;
        border-radius: 0 !important;
      }
      div[data-testid="stMetric"] label {
        font-family: 'Poppins', sans-serif !important;
        font-size: 0.65rem !important;
        font-weight: 400 !important;
        letter-spacing: 0.15em !important;
        text-transform: uppercase !important;
        color: #344d47 !important;
      }
      div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-family: 'Playfair Display', serif !important;
        font-size: 1.8rem !important;
        font-weight: 400 !important;
        color: #1c1c1c !important;
      }
      span[data-baseweb="tag"] {
        background-color: #344d47 !important;
        border-radius: 0 !important;
      }
      div[data-baseweb="input"] input,
      div[data-baseweb="select"] {
        border-radius: 0 !important;
        font-family: 'Poppins', sans-serif !important;
      }
      hr { border: none !important; border-top: 1px solid #dddddd !important; }
      #MainMenu, footer { visibility: hidden; }
    `;
    parent.head.appendChild(style);
  }
</script>
""", height=0)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data():
    products = get_products()
    inventory = get_inventory_levels()
    orders = get_orders_last_90_days()
    pos = get_purchase_orders()
    sales = build_sales_by_variant(orders)
    on_order = build_on_order_by_sku(pos)
    fetched_at = datetime.now().strftime("%d %b %Y %H:%M")
    return products, inventory, sales, on_order, fetched_at

STATUS_EMOJI  = {"critical": "🔴", "order_soon": "🟡", "ok": "🟢", "no_sales": "⚪"}
STATUS_LABEL  = {
    "critical":   "Critical (< 30 days)",
    "order_soon": "Order Soon (30–60 days)",
    "ok":         "OK (> 60 days)",
    "no_sales":   "No Sales (90 days)",
}

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://rainco.com.au/cdn/shop/files/Dark_Slate_Green_Logo.png", width=150)
    st.markdown("---")

    if st.button("Sync Data Now", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("<p style='font-size:0.65rem;letter-spacing:0.15em;text-transform:uppercase;color:#344d47;font-family:Poppins,sans-serif;margin-bottom:4px'>Filters</p>", unsafe_allow_html=True)
    filter_status = st.multiselect(
        "Status", label_visibility="collapsed",
        options=["critical", "order_soon", "ok", "no_sales"],
        default=["critical", "order_soon"],
        format_func=lambda x: STATUS_LABEL[x]
    )
    filter_type = st.text_input("Product type", placeholder="e.g. Tapware")
    only_order  = st.checkbox("Only show items to order", value=True)

    st.markdown("---")
    st.markdown("<p style='font-size:0.65rem;letter-spacing:0.15em;text-transform:uppercase;color:#344d47;font-family:Poppins,sans-serif;margin-bottom:4px'>Settings</p>", unsafe_allow_html=True)
    lead_time  = st.number_input("Lead time (days)", value=120, min_value=1)
    safety     = st.number_input("Safety stock (days)", value=30, min_value=0)
    global_moq = st.number_input("Min. order qty (MOQ)", value=15, min_value=1)
    st.caption(f"Target cover: {lead_time + safety} days")

# ── Main ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='font-family:"Playfair Display",serif;font-size:1.8rem;font-weight:400;letter-spacing:0.05em;color:#1c1c1c;margin-bottom:2px'>Procurement Dashboard</div>
<div style='font-family:Poppins,sans-serif;font-size:0.7rem;font-weight:400;letter-spacing:0.18em;text-transform:uppercase;color:#344d47;margin-bottom:1.5rem'>Inventory · Orders · Reorder Planning</div>
""", unsafe_allow_html=True)

with st.spinner("Loading Shopify data..."):
    products, inventory, sales, on_order, fetched_at = fetch_all_data()

import calculations
calculations.LEAD_TIME_DAYS    = lead_time
calculations.SAFETY_STOCK_DAYS = safety
calculations.TARGET_COVER_DAYS = lead_time + safety

rows = calculate_procurement(products, inventory, sales, on_order, global_moq)
df   = pd.DataFrame(rows)

# ── Metric cards ───────────────────────────────────────────────────────────────
total      = len(df)
critical   = len(df[df.status == "critical"])
order_soon = len(df[df.status == "order_soon"])
to_order   = len(df[df.rec_order > 0])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total SKUs",      total)
c2.metric("Critical",        critical,   help="< 30 days cover")
c3.metric("Order Soon",      order_soon, help="30–60 days cover")
c4.metric("SKUs to Order",   to_order)
c5.metric("Last Synced",     fetched_at)

st.markdown("---")

# ── Filters ────────────────────────────────────────────────────────────────────
filtered = df.copy()
if filter_status:
    filtered = filtered[filtered.status.isin(filter_status)]
if filter_type:
    filtered = filtered[filtered.type.str.contains(filter_type, case=False, na=False)]
if only_order:
    filtered = filtered[filtered.rec_order > 0]

# ── Table ──────────────────────────────────────────────────────────────────────
st.markdown(f"<h3 style='margin-top:0;font-family:\"Playfair Display\",serif;font-weight:400'>Order List <span style='font-family:Poppins,sans-serif;font-size:0.85rem;font-weight:300;color:#666'>({len(filtered)} items)</span></h3>", unsafe_allow_html=True)

if filtered.empty:
    st.info("No items match the current filters.")
else:
    display = filtered[[
        "status", "product", "variant", "sku", "type",
        "on_hand", "on_order", "sold_90d", "avg_daily",
        "days_cover", "target_stock", "rec_order", "moq"
    ]].copy()
    display["status"]    = display["status"].map(STATUS_EMOJI)
    display["avg_daily"] = display["avg_daily"].apply(lambda x: f"{x:.2f}")
    display.columns = ["", "Product", "Variant", "SKU", "Type",
                        "On Hand", "On Order", "Sold 90d", "Avg/Day",
                        "Days Cover", "Target Stock", "Rec. Order", "MOQ"]

    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Days Cover":  st.column_config.NumberColumn(format="%d days"),
            "Rec. Order":  st.column_config.NumberColumn(format="%d units"),
        }
    )

    st.markdown("---")
    col1, _ = st.columns([1, 3])
    with col1:
        st.download_button(
            "Export to CSV",
            data=filtered.to_csv(index=False).encode(),
            file_name=f"rainco_order_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ── (MOQ is a global setting in the sidebar) ──────────────────────────────────

# ── Manual On-Order Overrides ──────────────────────────────────────────────────
with st.expander("Manual On-Order Overrides"):
    st.caption("Use this if Shopify PO sync isn't returning data.")
    manual_file = "manual_on_order.json"
    manual = json.load(open(manual_file)) if os.path.exists(manual_file) else {}
    manual_df = pd.DataFrame(
        [{"SKU": k, "On Order Qty": v} for k, v in manual.items()] or [{"SKU": "", "On Order Qty": 0}]
    )
    edited_m = st.data_editor(manual_df, use_container_width=True, hide_index=True, num_rows="dynamic")
    if st.button("Save On-Order Overrides"):
        new_m = {r["SKU"]: int(r["On Order Qty"]) for _, r in edited_m.iterrows()
                 if r["SKU"] and int(r["On Order Qty"]) > 0}
        with open(manual_file, "w") as f:
            json.dump(new_m, f, indent=2)
        st.success("Saved! Click Sync Data Now to recalculate.")
