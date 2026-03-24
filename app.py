import streamlit as st
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
    page_icon="https://rainco.com.au/cdn/shop/files/Dark_Slate_Green_Logo.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  html, body, [class*="css"], .stApp {
    font-family: 'Poppins', sans-serif !important;
    font-weight: 300;
    background-color: #f8f8f6;
  }
  h1, h2, h3, h4 {
    font-family: 'Playfair Display', serif !important;
    font-weight: 400 !important;
    color: #1c1c1c !important;
  }
  /* Sidebar */
  section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #e0e0dc !important;
  }
  section[data-testid="stSidebar"] * {
    font-family: 'Poppins', sans-serif !important;
  }
  /* Buttons */
  .stButton > button {
    background-color: #344d47 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 0 !important;
    font-family: 'Poppins', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    padding: 0.5rem 1.2rem !important;
  }
  .stButton > button:hover {
    background-color: #263a35 !important;
  }
  .stDownloadButton > button {
    background-color: transparent !important;
    color: #344d47 !important;
    border: 1px solid #344d47 !important;
    border-radius: 0 !important;
    font-family: 'Poppins', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
  }
  .stDownloadButton > button:hover {
    background-color: #344d47 !important;
    color: #ffffff !important;
  }
  /* Metrics */
  [data-testid="stMetric"] {
    background-color: #ffffff !important;
    border: 1px solid #e0e0dc !important;
    padding: 1rem 1.2rem !important;
    border-radius: 0 !important;
  }
  [data-testid="stMetricLabel"] {
    font-family: 'Poppins', sans-serif !important;
    font-size: 0.62rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #344d47 !important;
  }
  [data-testid="stMetricValue"] {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.9rem !important;
    font-weight: 400 !important;
    color: #1c1c1c !important;
  }
  /* Inputs */
  .stTextInput input, .stNumberInput input {
    border-radius: 0 !important;
    border-color: #e0e0dc !important;
    font-family: 'Poppins', sans-serif !important;
    font-size: 0.85rem !important;
  }
  .stMultiSelect [data-baseweb="select"] {
    border-radius: 0 !important;
  }
  /* Dataframe */
  .stDataFrame {
    border: 1px solid #e0e0dc !important;
  }
  /* Hide Streamlit chrome */
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 2rem !important; }
  hr { border: none !important; border-top: 1px solid #e0e0dc !important; margin: 1rem 0 !important; }
  /* Sidebar labels */
  .sidebar-label {
    font-size: 0.62rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #344d47;
    font-family: 'Poppins', sans-serif;
    margin-bottom: 4px;
    margin-top: 12px;
    display: block;
  }
</style>
""", unsafe_allow_html=True)

STATUS_EMOJI = {"critical": "🔴", "order_soon": "🟡", "ok": "🟢", "no_sales": "⚪"}
STATUS_LABEL = {
    "critical":   "🔴 Critical (< 30 days)",
    "order_soon": "🟡 Order Soon (30–60 days)",
    "ok":         "🟢 OK (> 60 days)",
    "no_sales":   "⚪ No Sales (90 days)",
}

# ── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://rainco.com.au/cdn/shop/files/Dark_Slate_Green_Logo.png", width=140)
    st.markdown("<hr>", unsafe_allow_html=True)

    if st.button("⟳  Sync Data Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<span class="sidebar-label">Filters</span>', unsafe_allow_html=True)

    filter_status = st.multiselect(
        "Status", label_visibility="collapsed",
        options=["critical", "order_soon", "ok", "no_sales"],
        default=["critical", "order_soon"],
        format_func=lambda x: STATUS_LABEL[x]
    )
    filter_search = st.text_input("Search product", placeholder="Name, SKU or type…")
    only_order = st.checkbox("Only items to order", value=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<span class="sidebar-label">Settings</span>', unsafe_allow_html=True)

    lead_time  = st.number_input("Lead time (days)", value=120, min_value=1)
    safety     = st.number_input("Safety stock (days)", value=30, min_value=0)
    global_moq = st.number_input("Min. order qty (MOQ)", value=15, min_value=1)
    st.caption(f"Target cover: {lead_time + safety} days")

# ── Header ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='margin-bottom:0.25rem'>
  <span style='font-family:"Playfair Display",serif;font-size:2rem;font-weight:400;color:#1c1c1c;letter-spacing:0.03em'>
    Procurement Dashboard
  </span>
</div>
<div style='font-family:Poppins,sans-serif;font-size:0.65rem;font-weight:400;letter-spacing:0.2em;text-transform:uppercase;color:#344d47;margin-bottom:1.5rem'>
  Inventory · Orders · Reorder Planning
</div>
""", unsafe_allow_html=True)

# ── Load Data ────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data():
    products  = get_products()
    inventory = get_inventory_levels()
    orders    = get_orders_last_90_days()
    pos       = get_purchase_orders()
    sales     = build_sales_by_variant(orders)
    on_order  = build_on_order_by_sku(pos)
    fetched_at = datetime.now().strftime("%d %b %Y, %H:%M")
    return products, inventory, sales, on_order, fetched_at

with st.spinner("Loading Shopify data…"):
    products, inventory, sales, on_order, fetched_at = fetch_all_data()

import calculations
calculations.LEAD_TIME_DAYS    = lead_time
calculations.SAFETY_STOCK_DAYS = safety
calculations.TARGET_COVER_DAYS = lead_time + safety

rows = calculate_procurement(products, inventory, sales, on_order, global_moq)
df   = pd.DataFrame(rows)

# ── Metric Cards ─────────────────────────────────────────────────────────────────
total      = len(df)
critical   = len(df[df.status == "critical"])
order_soon = len(df[df.status == "order_soon"])
to_order   = len(df[df.rec_order > 0])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total SKUs",    total)
c2.metric("🔴 Critical",    critical,   help="Less than 30 days of stock")
c3.metric("🟡 Order Soon",  order_soon, help="30–60 days of stock")
c4.metric("To Order",      to_order,   help="SKUs with recommended order qty > 0")
c5.metric("Last Synced",   fetched_at)

st.markdown("<hr>", unsafe_allow_html=True)

# ── Filters ───────────────────────────────────────────────────────────────────────
filtered = df.copy()
if filter_status:
    filtered = filtered[filtered.status.isin(filter_status)]
if filter_search:
    mask = (
        filtered.product.str.contains(filter_search, case=False, na=False) |
        filtered.sku.str.contains(filter_search, case=False, na=False) |
        filtered.type.str.contains(filter_search, case=False, na=False)
    )
    filtered = filtered[mask]
if only_order:
    filtered = filtered[filtered.rec_order > 0]

# ── Table ─────────────────────────────────────────────────────────────────────────
st.markdown(
    f"<h3 style='margin-top:0;margin-bottom:0.75rem'>Order List "
    f"<span style='font-family:Poppins,sans-serif;font-size:0.85rem;font-weight:300;color:#888'>"
    f"({len(filtered)} items)</span></h3>",
    unsafe_allow_html=True
)

if filtered.empty:
    st.info("No items match the current filters.")
else:
    display = filtered[[
        "status", "product", "variant", "sku", "type",
        "on_hand", "on_order", "sold_90d", "avg_daily",
        "days_cover", "target_stock", "rec_order"
    ]].copy()

    display["status"]    = display["status"].map(STATUS_EMOJI)
    display["avg_daily"] = display["avg_daily"].apply(lambda x: f"{x:.2f}")
    display["days_cover"] = display["days_cover"].apply(lambda x: x if x < 999 else "—")

    display.columns = [
        "", "Product", "Variant", "SKU", "Type",
        "On Hand", "On Order", "Sold 90d", "Avg/Day",
        "Days Cover", "Target Stock", "Rec. Order"
    ]

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rec. Order": st.column_config.NumberColumn(format="%d units"),
            "Target Stock": st.column_config.NumberColumn(format="%d units"),
        }
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    col1, col2, _ = st.columns([1, 1, 3])
    with col1:
        st.download_button(
            "Export CSV",
            data=filtered.to_csv(index=False).encode(),
            file_name=f"rainco_order_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col2:
        # Export only what to order, grouped nicely
        order_df = filtered[filtered["rec_order"] > 0][[
            "sku", "product", "variant", "type", "rec_order"
        ]].copy()
        order_df.columns = ["SKU", "Product", "Variant", "Type", "Qty to Order"]
        st.download_button(
            "Export Order",
            data=order_df.to_csv(index=False).encode(),
            file_name=f"rainco_purchase_order_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ── Manual On-Order Overrides ─────────────────────────────────────────────────────
with st.expander("Manual On-Order Overrides (if Shopify PO sync is missing data)"):
    st.caption("Enter SKUs and quantities for any open orders not yet in Shopify.")
    manual_file = "manual_on_order.json"
    manual = json.load(open(manual_file)) if os.path.exists(manual_file) else {}
    manual_df = pd.DataFrame(
        [{"SKU": k, "On Order Qty": v} for k, v in manual.items()] or [{"SKU": "", "On Order Qty": 0}]
    )
    edited_m = st.data_editor(manual_df, use_container_width=True, hide_index=True, num_rows="dynamic")
    if st.button("Save Overrides"):
        new_m = {r["SKU"]: int(r["On Order Qty"]) for _, r in edited_m.iterrows()
                 if r["SKU"] and int(r["On Order Qty"]) > 0}
        with open(manual_file, "w") as f:
            json.dump(new_m, f, indent=2)
        st.success("Saved. Click 'Sync Data Now' to recalculate.")
