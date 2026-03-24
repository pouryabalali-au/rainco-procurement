import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from shopify_api import (
    get_products, get_inventory_levels, get_orders_last_90_days,
    get_purchase_orders, build_sales_by_variant, build_on_order_by_sku,
    get_inventory_costs, get_usd_to_aud_rate
)
from calculations import calculate_procurement
from pdf_generator import generate_po_pdf
from shiphero import push_po_to_shiphero
from github_storage import load_supplier_data, save_supplier_data

st.set_page_config(
    page_title="RainCo Procurement",
    page_icon="https://rainco.com.au/cdn/shop/files/Dark_Slate_Green_Logo.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
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
  section[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #e0e0dc !important;
  }
  section[data-testid="stSidebar"] * {
    font-family: 'Poppins', sans-serif !important;
  }
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
  .stButton > button:hover { background-color: #263a35 !important; }
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
  .stTextInput input, .stNumberInput input {
    border-radius: 0 !important;
    border-color: #e0e0dc !important;
    font-family: 'Poppins', sans-serif !important;
    font-size: 0.85rem !important;
  }
  .stMultiSelect [data-baseweb="select"] { border-radius: 0 !important; }
  .stDataFrame { border: 1px solid #e0e0dc !important; }
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 2rem !important; }
  hr { border: none !important; border-top: 1px solid #e0e0dc !important; margin: 1rem 0 !important; }
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
        if "supplier_data" in st.session_state:
            del st.session_state["supplier_data"]
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<span class="sidebar-label">Filters</span>', unsafe_allow_html=True)

    filter_status = st.multiselect(
        "Status", label_visibility="collapsed",
        options=["critical", "order_soon", "ok", "no_sales"],
        default=["critical", "order_soon"],
        format_func=lambda x: STATUS_LABEL[x]
    )
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

# ── Load Supplier Data ────────────────────────────────────────────────────────────
if "supplier_data" not in st.session_state:
    with st.spinner("Loading supplier data…"):
        st.session_state.supplier_data = load_supplier_data()

supplier_data = st.session_state.supplier_data

# Build excluded set from supplier_data flags
excluded_skus = {sku for sku, v in supplier_data.items() if isinstance(v, dict) and v.get("excluded")}

# ── Load Shopify Data ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data():
    products   = get_products()
    inventory  = get_inventory_levels()
    orders     = get_orders_last_90_days()
    pos        = get_purchase_orders()
    sales      = build_sales_by_variant(orders)
    on_order   = build_on_order_by_sku(pos)
    costs      = get_inventory_costs(products)
    usd_to_aud = get_usd_to_aud_rate()
    fetched_at = datetime.now().strftime("%d %b %Y, %H:%M")
    return products, inventory, sales, on_order, costs, usd_to_aud, fetched_at

with st.spinner("Loading Shopify data…"):
    products, inventory, sales, on_order, costs, usd_to_aud, fetched_at = fetch_all_data()

import calculations
calculations.LEAD_TIME_DAYS    = lead_time
calculations.SAFETY_STOCK_DAYS = safety
calculations.TARGET_COVER_DAYS = lead_time + safety

rows = calculate_procurement(products, inventory, sales, on_order, global_moq, costs, usd_to_aud, supplier_data)
df   = pd.DataFrame(rows)

# ── Metric Cards ─────────────────────────────────────────────────────────────────
# Metrics exclude excluded SKUs
df_active = df[~df.sku.isin(excluded_skus)]
total      = len(df_active)
critical   = len(df_active[df_active.status == "critical"])
order_soon = len(df_active[df_active.status == "order_soon"])
to_order   = len(df_active[df_active.rec_order > 0])

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Active SKUs",   total)
c2.metric("🔴 Critical",    critical,   help="Less than 30 days of stock")
c3.metric("🟡 Order Soon",  order_soon, help="30–60 days of stock")
c4.metric("To Order",      to_order,   help="SKUs with recommended order qty > 0")
c5.metric("Last Synced",   fetched_at)

st.markdown("<hr>", unsafe_allow_html=True)

# ── Filters ───────────────────────────────────────────────────────────────────────
filtered = df[~df.sku.isin(excluded_skus)].copy()
if filter_status:
    filtered = filtered[filtered.status.isin(filter_status)]
if only_order:
    filtered = filtered[filtered.rec_order > 0]

# ── Table Header + Search ─────────────────────────────────────────────────────────
hcol1, hcol2 = st.columns([2, 2])
with hcol1:
    st.markdown(
        f"<h3 style='margin-top:0.4rem;margin-bottom:0'>Order List "
        f"<span style='font-family:Poppins,sans-serif;font-size:0.85rem;font-weight:300;color:#888'>"
        f"({len(filtered)} items)</span></h3>",
        unsafe_allow_html=True
    )
with hcol2:
    filter_search = st.text_input(
        "search", label_visibility="collapsed",
        placeholder="🔍  Search by product name, SKU or supplier SKU…",
        key="main_search"
    )

if filter_search:
    q = filter_search.strip()
    mask = (
        filtered.product.str.contains(q, case=False, na=False) |
        filtered.sku.str.contains(q, case=False, na=False) |
        filtered.supplier_sku.str.contains(q, case=False, na=False)
    )
    filtered = filtered[mask]

# ── Missing data warning ──────────────────────────────────────────────────────────
order_items      = filtered[filtered.rec_order > 0]
missing_supp_sku = order_items[order_items.supplier_sku.fillna("") == ""]
missing_cost     = order_items[order_items.cost_usd.isna() | (order_items.cost_usd == 0)]
missing_skus     = set(missing_supp_sku.sku.tolist()) | set(missing_cost.sku.tolist())

if missing_skus:
    st.warning(
        f"⚠️  **{len(missing_skus)} item(s) missing supplier SKU or cost** — "
        f"edit the highlighted cells before exporting.  "
        f"SKUs: `{'`, `'.join(sorted(missing_skus))}`",
        icon=None
    )

# ── Main Table ────────────────────────────────────────────────────────────────────
if filtered.empty:
    st.info("No items match the current filters.")
else:
    display = filtered[[
        "status", "product", "sku", "supplier_sku",
        "on_hand", "on_order", "sold_90d", "avg_daily",
        "days_cover", "rec_order", "cost_usd", "order_value_aud"
    ]].copy()

    display.insert(0, "exclude", False)   # checkbox column — all False (excluded rows never appear here)

    display["status"]     = display["status"].map(STATUS_EMOJI)
    display["avg_daily"]  = display["avg_daily"].apply(lambda x: round(x, 2))
    display["days_cover"] = display["days_cover"].apply(lambda x: x if x < 999 else None)

    display.columns = [
        "Exclude", "", "Product", "SKU", "Supplier SKU",
        "On Hand", "On Order", "Sold 90d", "Avg/Day",
        "Days Cover", "Rec. Order", "Cost (USD)", "Order Value (AUD)"
    ]

    read_only_cols = ["", "Product", "SKU", "On Hand", "On Order",
                      "Sold 90d", "Avg/Day", "Days Cover", "Rec. Order", "Order Value (AUD)"]

    edited = st.data_editor(
        display,
        use_container_width=True,
        hide_index=True,
        disabled=read_only_cols,
        column_config={
            "Exclude":          st.column_config.CheckboxColumn(
                                    "✕", help="Exclude this SKU — it will be hidden from the dashboard. "
                                    "You can restore it from the Exclusion List below.",
                                    width="small"),
            "Rec. Order":       st.column_config.NumberColumn(format="%d units"),
            "On Hand":          st.column_config.NumberColumn(format="%d"),
            "On Order":         st.column_config.NumberColumn(format="%d"),
            "Sold 90d":         st.column_config.NumberColumn(format="%d"),
            "Avg/Day":          st.column_config.NumberColumn(format="%.2f"),
            "Days Cover":       st.column_config.NumberColumn(format="%d"),
            "Cost (USD)":       st.column_config.NumberColumn(format="$%.2f", min_value=0.0, step=0.5),
            "Order Value (AUD)":st.column_config.NumberColumn(format="$%.2f"),
            "Supplier SKU":     st.column_config.TextColumn(help="Watersino JD- code"),
        },
        key="order_table"
    )

    # ── Merge edits back into session_state.supplier_data ─────────────────────────
    newly_excluded = []
    for _, row in edited.iterrows():
        sku = row.get("SKU", "")
        if not sku:
            continue
        entry = st.session_state.supplier_data.setdefault(sku, {})

        # Exclusion
        if row.get("Exclude"):
            entry["excluded"] = True
            newly_excluded.append(sku)

        # Supplier SKU edit
        new_supp_sku = str(row.get("Supplier SKU") or "").strip()
        if new_supp_sku and new_supp_sku != entry.get("supplier_sku", ""):
            entry["supplier_sku"] = new_supp_sku

        # Cost edit
        new_cost = row.get("Cost (USD)")
        if new_cost and float(new_cost) > 0 and float(new_cost) != entry.get("cost_usd", 0):
            entry["cost_usd"] = round(float(new_cost), 2)

    if newly_excluded:
        st.rerun()  # immediately remove excluded rows from view

    # ── AUD Totals ────────────────────────────────────────────────────────────────
    total_aud = filtered["order_value_aud"].dropna().sum()
    total_usd = filtered["order_value_usd"].dropna().sum()
    st.markdown("<hr>", unsafe_allow_html=True)
    ta, tb, tc = st.columns([1, 1, 2])
    ta.metric("Total Order (USD)", f"${total_usd:,.0f}")
    tb.metric(f"Total Order (AUD) @ {usd_to_aud:.4f}", f"${total_aud:,.0f}")
    with tc:
        st.caption(f"Live exchange rate: 1 USD = {usd_to_aud:.4f} AUD")

    st.markdown("<hr>", unsafe_allow_html=True)

    order_rows = filtered[filtered["rec_order"] > 0].to_dict("records")
    po_number  = f"RC-{datetime.now().strftime('%Y%m%d')}-{len(order_rows):03d}"

    def _validate_order_rows(rows):
        return [r.get("sku", "?") for r in rows if not r.get("supplier_sku") or not r.get("cost_usd")]

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        bad = _validate_order_rows(order_rows)
        if bad:
            st.button("Export Order PDF", use_container_width=True, disabled=True,
                      help=f"Missing data for: {', '.join(bad)}")
        else:
            pdf_bytes = generate_po_pdf(order_rows, usd_to_aud, po_number)
            if st.download_button(
                "Export Order PDF",
                data=pdf_bytes,
                file_name=f"{po_number}.pdf",
                mime="application/pdf",
                use_container_width=True
            ):
                save_supplier_data(st.session_state.supplier_data)

    with col2:
        order_df = filtered[filtered["rec_order"] > 0][[
            "sku", "supplier_sku", "product", "rec_order", "cost_usd", "order_value_usd", "order_value_aud"
        ]].copy()
        order_df.columns = ["SKU", "Supplier SKU", "Product", "Qty to Order",
                             "Cost USD", "Order Value USD", "Order Value AUD"]
        st.download_button(
            "Export Order CSV",
            data=order_df.to_csv(index=False).encode(),
            file_name=f"{po_number}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col3:
        bad = _validate_order_rows(order_rows)
        if bad:
            st.button("Send to ShipHero", use_container_width=True, disabled=True,
                      help=f"Missing data for: {', '.join(bad)}")
        else:
            if st.button("Send to ShipHero", use_container_width=True):
                with st.spinner("Creating PO in ShipHero…"):
                    result = push_po_to_shiphero(order_rows, po_number)
                if result["success"]:
                    st.success(f"PO {result['po_number']} created in ShipHero")
                else:
                    st.error(f"ShipHero error: {result['error']}")

    with col4:
        if st.button("Save Supplier Data", use_container_width=True):
            with st.spinner("Saving to GitHub…"):
                ok = save_supplier_data(st.session_state.supplier_data)
            if ok:
                st.success("Saved.")
            else:
                st.error("Failed — check GitHub token.")

# ── Exclusion List ────────────────────────────────────────────────────────────────
excluded_skus_current = {
    sku for sku, v in st.session_state.supplier_data.items()
    if isinstance(v, dict) and v.get("excluded")
}

excl_label = f"Exclusion List ({len(excluded_skus_current)} SKUs)" if excluded_skus_current else "Exclusion List"
with st.expander(excl_label, expanded=bool(excluded_skus_current)):
    if not excluded_skus_current:
        st.caption("No SKUs excluded. Tick the ✕ checkbox on any row to hide it from the dashboard.")
    else:
        st.caption("These SKUs are hidden from the dashboard. Tick the checkbox to restore them.")

        # Build a display table of excluded SKUs
        excl_rows = []
        for sku in sorted(excluded_skus_current):
            entry = st.session_state.supplier_data.get(sku, {})
            # Try to find product name from df
            match = df[df.sku == sku]
            product_name = match.iloc[0]["product"] if not match.empty else "—"
            excl_rows.append({
                "Restore": False,
                "SKU": sku,
                "Product": product_name,
                "Supplier SKU": entry.get("supplier_sku", ""),
                "Cost (USD)": entry.get("cost_usd", None),
            })

        excl_df = pd.DataFrame(excl_rows)
        edited_excl = st.data_editor(
            excl_df,
            use_container_width=True,
            hide_index=True,
            disabled=["SKU", "Product", "Supplier SKU", "Cost (USD)"],
            column_config={
                "Restore": st.column_config.CheckboxColumn(
                    "↩ Restore", help="Tick to restore this SKU to the dashboard", width="small"
                ),
                "Cost (USD)": st.column_config.NumberColumn(format="$%.2f"),
            },
            key="excl_table"
        )

        restored = [r["SKU"] for _, r in edited_excl.iterrows() if r.get("Restore")]
        if restored:
            for sku in restored:
                if sku in st.session_state.supplier_data:
                    st.session_state.supplier_data[sku].pop("excluded", None)
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        ecol1, ecol2 = st.columns([1, 3])
        with ecol1:
            if st.button("Save Exclusion List", use_container_width=True):
                with st.spinner("Saving…"):
                    ok = save_supplier_data(st.session_state.supplier_data)
                if ok:
                    st.success("Saved.")
                else:
                    st.error("Failed — check GitHub token.")

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
