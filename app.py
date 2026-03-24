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

# ── Session state init ────────────────────────────────────────────────────────────
if "rec_order_overrides" not in st.session_state:
    st.session_state.rec_order_overrides = {}

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

# ── Table Header ─────────────────────────────────────────────────────────────────
st.markdown(
    f"<h3 style='margin-top:0;margin-bottom:0.75rem'>Order List "
    f"<span style='font-family:Poppins,sans-serif;font-size:0.85rem;font-weight:300;color:#888'>"
    f"({len(filtered)} items)</span></h3>",
    unsafe_allow_html=True
)

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
        "days_cover", "rec_order", "pcs_per_box", "cost_usd", "order_value_aud"
    ]].copy()

    display["status"]     = display["status"].map(STATUS_EMOJI)
    display["avg_daily"]  = display["avg_daily"].apply(lambda x: round(x, 2))
    display["days_cover"] = display["days_cover"].apply(lambda x: x if x < 999 else None)
    display["exclude"]    = False

    display.columns = [
        "", "Product", "SKU", "Supplier SKU",
        "On Hand", "On Order", "Sold 90d", "Avg/Day",
        "Days Cover", "Rec. Order", "Pcs/Box", "Cost (USD)", "Order Value (AUD)", "Exclude"
    ]

    # Apply any session-level rec_order overrides
    for idx, row in display.iterrows():
        sku_ = row["SKU"]
        if sku_ in st.session_state.rec_order_overrides:
            display.at[idx, "Rec. Order"] = st.session_state.rec_order_overrides[sku_]

    read_only_cols = ["", "Product", "SKU", "On Hand", "On Order",
                      "Sold 90d", "Avg/Day", "Days Cover", "Order Value (AUD)"]

    edited = st.data_editor(
        display,
        use_container_width=True,
        hide_index=True,
        disabled=read_only_cols,
        column_config={
            "Exclude":          st.column_config.CheckboxColumn(
                                    "✕", help="Exclude — hides this SKU from the dashboard. "
                                    "Restore it any time from the Exclusion List below.",
                                    width="small", default=False),
            "Rec. Order":       st.column_config.NumberColumn(
                                    "Rec. Order", help="Override the calculated quantity for this order",
                                    min_value=0, step=1, format="%d units"),
            "Pcs/Box":          st.column_config.NumberColumn(
                                    "Pcs/Box", help="Units per box — saved to memory. "
                                    "Rec. Order will always round up to a full box.",
                                    min_value=1, step=1, format="%d"),
            "On Hand":          st.column_config.NumberColumn(format="%d"),
            "On Order":         st.column_config.NumberColumn(format="%d"),
            "Sold 90d":         st.column_config.NumberColumn(format="%d"),
            "Avg/Day":          st.column_config.NumberColumn(format="%.2f"),
            "Days Cover":       st.column_config.NumberColumn(format="%d"),
            "Cost (USD)":       st.column_config.NumberColumn(
                                    "Cost (USD)", help="Unit cost in USD — type to edit",
                                    min_value=0.0, step=0.5, format="%.2f"),
            "Order Value (AUD)":st.column_config.NumberColumn(format="%.2f"),
            "Supplier SKU":     st.column_config.TextColumn(help="Watersino JD- code"),
        },
        key="order_table"
    )

    # ── Merge edits back into session_state.supplier_data ─────────────────────────
    newly_excluded = []
    pcs_per_box_changed = False
    for _, row in edited.iterrows():
        sku = row.get("SKU", "")
        if not sku:
            continue
        entry = st.session_state.supplier_data.setdefault(sku, {})

        # Exclusion
        if row.get("Exclude"):
            entry["excluded"] = True
            newly_excluded.append(sku)

        # Rec. Order override (session-only)
        try:
            new_qty = int(row.get("Rec. Order") or 0)
            if new_qty >= 0:
                st.session_state.rec_order_overrides[sku] = new_qty
        except (TypeError, ValueError):
            pass

        # Supplier SKU edit
        new_supp_sku = str(row.get("Supplier SKU") or "").strip()
        if new_supp_sku:
            entry["supplier_sku"] = new_supp_sku

        # Pcs/Box (saved to GitHub memory)
        try:
            new_ppb = row.get("Pcs/Box")
            if new_ppb and int(new_ppb) > 0:
                if entry.get("pcs_per_box") != int(new_ppb):
                    entry["pcs_per_box"] = int(new_ppb)
                    pcs_per_box_changed = True
        except (TypeError, ValueError):
            pass

        # Cost edit
        try:
            new_cost = float(row.get("Cost (USD)") or 0)
            if new_cost > 0:
                entry["cost_usd"] = round(new_cost, 2)
        except (TypeError, ValueError):
            pass

    if newly_excluded:
        st.rerun()
    if pcs_per_box_changed:
        st.rerun()  # recalculate rec_order with new box rounding

# ── Manual Additions (session only — resets on refresh) ──────────────────────────
if "manual_additions" not in st.session_state:
    st.session_state.manual_additions = []

st.markdown("<hr>", unsafe_allow_html=True)
st.markdown(
    "<h3 style='margin-top:0;margin-bottom:0.5rem'>Manual Additions "
    "<span style='font-family:Poppins,sans-serif;font-size:0.75rem;font-weight:300;color:#aaa'>"
    "session only · clears on refresh</span></h3>",
    unsafe_allow_html=True
)

# Build a flat lookup of all product variants for the search selectbox
variant_index = {}
for _p in products:
    for _v in _p.get("variants", []):
        _sku = _v.get("sku", "")
        _vt  = _v.get("title", "")
        _label = _p["title"]
        if _vt and _vt not in ("Default Title", ""):
            _label += f" — {_vt}"
        if _sku:
            _label += f"  ({_sku})"
        variant_index[_label] = {"sku": _sku, "product": _p["title"]}

add_col1, add_col2, add_col3 = st.columns([4, 1, 1])
with add_col1:
    selected_label = st.selectbox(
        "Product", label_visibility="collapsed",
        options=[""] + sorted(variant_index.keys()),
        placeholder="Search product name or SKU…",
        key="manual_add_select"
    )
with add_col2:
    add_qty = st.number_input("Qty", min_value=1, value=15,
                               label_visibility="collapsed", key="manual_add_qty")
with add_col3:
    add_btn = st.button("➕  Add to Order", use_container_width=True, key="manual_add_btn")

if add_btn and selected_label:
    variant_info = variant_index.get(selected_label, {})
    sku = variant_info.get("sku", "")
    product_name = variant_info.get("product", selected_label)
    supp = supplier_data.get(sku, {})
    cost_usd = supp.get("cost_usd")
    supplier_sku = supp.get("supplier_sku", "")
    order_value_usd = round(add_qty * cost_usd, 2) if cost_usd else None
    order_value_aud = round(order_value_usd * usd_to_aud, 2) if order_value_usd else None
    # Avoid adding the same SKU twice
    existing_skus = [r["sku"] for r in st.session_state.manual_additions]
    if sku and sku not in existing_skus:
        st.session_state.manual_additions.append({
            "sku": sku, "supplier_sku": supplier_sku,
            "product": product_name, "rec_order": add_qty,
            "cost_usd": cost_usd, "order_value_usd": order_value_usd,
            "order_value_aud": order_value_aud,
        })
        st.rerun()

if st.session_state.manual_additions:
    ma_df = pd.DataFrame([{
        "Remove": False,
        "Product": r["product"],
        "SKU": r["sku"],
        "Supplier SKU": r.get("supplier_sku") or "",
        "Qty": r["rec_order"],
        "Cost (USD)": r.get("cost_usd"),
        "Order Value (AUD)": r.get("order_value_aud"),
    } for r in st.session_state.manual_additions])

    edited_ma = st.data_editor(
        ma_df, use_container_width=True, hide_index=True,
        disabled=["Product", "SKU", "Order Value (AUD)"],
        column_config={
            "Remove":       st.column_config.CheckboxColumn("✕", width="small"),
            "Qty":          st.column_config.NumberColumn(format="%d units"),
            "Supplier SKU": st.column_config.TextColumn(help="Watersino JD- code"),
            "Cost (USD)":   st.column_config.NumberColumn(format="%.2f", min_value=0.0, step=0.5,
                                                           help="Unit cost in USD — type to edit"),
            "Order Value (AUD)": st.column_config.NumberColumn(format="%.2f"),
        },
        key="manual_add_table"
    )

    # Merge edits back into manual_additions and supplier_data
    changed_ma = False
    for i, row in edited_ma.iterrows():
        if i >= len(st.session_state.manual_additions):
            continue
        entry = st.session_state.manual_additions[i]
        sku = entry["sku"]

        new_supp_sku = str(row.get("Supplier SKU") or "").strip()
        if new_supp_sku:
            entry["supplier_sku"] = new_supp_sku
            st.session_state.supplier_data.setdefault(sku, {})["supplier_sku"] = new_supp_sku
            changed_ma = True

        try:
            new_cost = float(row.get("Cost (USD)") or 0)
            if new_cost > 0:
                entry["cost_usd"] = round(new_cost, 2)
                entry["order_value_usd"] = round(entry["rec_order"] * new_cost, 2)
                entry["order_value_aud"] = round(entry["order_value_usd"] * usd_to_aud, 2)
                st.session_state.supplier_data.setdefault(sku, {})["cost_usd"] = round(new_cost, 2)
                changed_ma = True
        except (TypeError, ValueError):
            pass

    to_remove = [i for i, r in edited_ma.iterrows() if r.get("Remove")]
    if to_remove:
        st.session_state.manual_additions = [
            r for i, r in enumerate(st.session_state.manual_additions) if i not in to_remove
        ]
        st.rerun()
else:
    st.caption("No manual additions yet. Use the search above to add any product.")

# ── Combined Totals + Exports ─────────────────────────────────────────────────────
rec_overrides = st.session_state.rec_order_overrides
calc_order_rows = []
if not filtered.empty:
    for r in filtered.to_dict("records"):
        qty = rec_overrides.get(r["sku"], r["rec_order"])
        if qty > 0:
            r = r.copy()
            r["rec_order"] = qty
            if r.get("cost_usd"):
                r["order_value_usd"] = round(qty * r["cost_usd"], 2)
                r["order_value_aud"] = round(r["order_value_usd"] * usd_to_aud, 2)
            calc_order_rows.append(r)
all_order_rows = calc_order_rows + st.session_state.manual_additions

if all_order_rows:
    total_usd = sum((r.get("order_value_usd") or 0) for r in all_order_rows)
    total_aud = sum((r.get("order_value_aud") or 0) for r in all_order_rows)
    po_number = f"RC-{datetime.now().strftime('%Y%m%d')}-{len(all_order_rows):03d}"

    st.markdown("<hr>", unsafe_allow_html=True)
    ta, tb, tc = st.columns([1, 1, 2])
    ta.metric("Total Order (USD)", f"${total_usd:,.0f}")
    tb.metric(f"Total Order (AUD) @ {usd_to_aud:.4f}", f"${total_aud:,.0f}")
    with tc:
        st.caption(f"Live exchange rate: 1 USD = {usd_to_aud:.4f} AUD")

    st.markdown("<hr>", unsafe_allow_html=True)

    def _validate_order_rows(rows):
        return [r.get("sku", "?") for r in rows if not r.get("supplier_sku") or not r.get("cost_usd")]

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        bad = _validate_order_rows(all_order_rows)
        if bad:
            st.button("Export Order PDF", use_container_width=True, disabled=True,
                      help=f"Missing data for: {', '.join(bad)}")
        else:
            pdf_bytes = generate_po_pdf(all_order_rows, usd_to_aud, po_number)
            if st.download_button(
                "Export Order PDF",
                data=pdf_bytes,
                file_name=f"{po_number}.pdf",
                mime="application/pdf",
                use_container_width=True
            ):
                save_supplier_data(st.session_state.supplier_data)

    with col2:
        order_df = pd.DataFrame([{
            "SKU": r.get("sku"), "Supplier SKU": r.get("supplier_sku"),
            "Product": r.get("product"), "Qty to Order": r.get("rec_order"),
            "Cost USD": r.get("cost_usd"), "Order Value USD": r.get("order_value_usd"),
            "Order Value AUD": r.get("order_value_aud"),
        } for r in all_order_rows])
        st.download_button(
            "Export Order CSV",
            data=order_df.to_csv(index=False).encode(),
            file_name=f"{po_number}.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col3:
        bad = _validate_order_rows(all_order_rows)
        if bad:
            st.button("Send to ShipHero", use_container_width=True, disabled=True,
                      help=f"Missing data for: {', '.join(bad)}")
        else:
            if st.button("Send to ShipHero", use_container_width=True):
                with st.spinner("Creating PO in ShipHero…"):
                    result = push_po_to_shiphero(all_order_rows, po_number)
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
