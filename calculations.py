LEAD_TIME_DAYS = 120
SAFETY_STOCK_DAYS = 30
TARGET_COVER_DAYS = LEAD_TIME_DAYS + SAFETY_STOCK_DAYS  # 150 days
LOOKBACK_DAYS = 90
GLOBAL_MOQ = 15

def calculate_procurement(products, inventory_by_inv_id, sales_by_variant_id, on_order_by_sku, global_moq=None):
    """
    Build the full procurement table.
    Returns list of dicts, one per variant.
    """
    if global_moq is None:
        global_moq = GLOBAL_MOQ

    rows = []
    for product in products:
        for variant in product.get("variants", []):
            variant_id = variant["id"]
            inv_item_id = variant.get("inventory_item_id")
            sku = variant.get("sku", "") or ""
            title = product["title"]
            option = variant.get("title", "")
            product_type = product.get("product_type", "")
            tags = product.get("tags", "")

            # Stock on hand at Tullamarine
            on_hand = inventory_by_inv_id.get(inv_item_id, 0) or 0

            # Units sold last 90 days
            sold_90d = sales_by_variant_id.get(variant_id, 0)

            # On order (from POs or manual override)
            on_order = on_order_by_sku.get(sku, 0) if sku else 0

            # Calculations
            avg_daily = round(sold_90d / LOOKBACK_DAYS, 3)
            target_stock = round(avg_daily * TARGET_COVER_DAYS)
            rec_order = max(0, target_stock - on_hand - on_order)

            # Days of cover
            if avg_daily > 0:
                days_cover = round(on_hand / avg_daily)
            else:
                days_cover = 999  # effectively infinite if no sales

            # Round up to global MOQ
            moq = global_moq
            if rec_order > 0 and rec_order < moq:
                rec_order = moq

            # Status
            if avg_daily == 0:
                status = "no_sales"
            elif days_cover < 30:
                status = "critical"
            elif days_cover < 60:
                status = "order_soon"
            else:
                status = "ok"

            rows.append({
                "product_id": product["id"],
                "variant_id": variant_id,
                "sku": sku,
                "product": title,
                "variant": option,
                "type": product_type,
                "tags": tags,
                "on_hand": on_hand,
                "on_order": on_order,
                "sold_90d": sold_90d,
                "avg_daily": avg_daily,
                "days_cover": days_cover,
                "target_stock": target_stock,
                "rec_order": rec_order,
                "moq": moq,
                "status": status,
            })

    return sorted(rows, key=lambda x: (
        0 if x["status"] == "critical" else
        1 if x["status"] == "order_soon" else
        2 if x["status"] == "ok" else 3,
        x["days_cover"]
    ))
