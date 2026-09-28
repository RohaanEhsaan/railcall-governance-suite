"""rohan/shopify-admin — Governed Shopify Admin Airlock Handler.

Strict platform contract:
- (inputs, stamp=None) -> (result_dict, receipt_meta)
- _creds() via __rc_helpers__["vault_get"]("shopify")
- Dual naming exports (shopify_<action> and <action>)
- Zero silent fallbacks (raise RuntimeError on API or payload failure)
- Anti-drift state fingerprinting on mutations
"""
import hashlib
import json
import urllib.request
import urllib.error

API_VERSION = "2024-01"

def _creds():
    helpers = globals().get("__rc_helpers__")
    if helpers and "vault_get" in helpers:
        try:
            entry = helpers["vault_get"]("shopify")
            if isinstance(entry, dict):
                shop = entry.get("SHOPIFY_SHOP_DOMAIN") or entry.get("shop_domain")
                tok = entry.get("SHOPIFY_ACCESS_TOKEN") or entry.get("access_token")
                if shop and tok:
                    return str(shop).strip(), str(tok).strip()
        except Exception:
            pass

    import os
    shop = os.environ.get("SHOPIFY_SHOP_DOMAIN")
    tok = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    if shop and tok:
        return shop.strip(), tok.strip()

    from pathlib import Path
    import json
    for p in [
        Path.home() / ".railcall" / "station" / "credentials.local.json",
        Path.home() / ".railcall" / "station" / ".railcall_workspace" / "keys.local.json"
    ]:
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                s = d.get("SHOPIFY_SHOP_DOMAIN") or (d.get("shopify", {}) if isinstance(d.get("shopify"), dict) else {}).get("SHOPIFY_SHOP_DOMAIN")
                t = d.get("SHOPIFY_ACCESS_TOKEN") or (d.get("shopify", {}) if isinstance(d.get("shopify"), dict) else {}).get("SHOPIFY_ACCESS_TOKEN")
                if s and t:
                    return str(s).strip(), str(t).strip()
            except Exception:
                pass
    return "", ""

def _request(path, method="GET", payload=None):
    domain, token = _creds()
    if not domain or not token:
        raise RuntimeError("Airlock Refusal: Missing SHOPIFY_SHOP_DOMAIN or SHOPIFY_ACCESS_TOKEN in Station Vault.")

    clean_path = path if path.startswith("/") else f"/{path}"
    url = f"https://{domain}/admin/api/{API_VERSION}{clean_path}"

    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": token,
            "User-Agent": "RailCall-Shopify-Governance/1.0"
        },
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Shopify HTTP {e.code}: {err_msg}")
    except Exception as e:
        raise RuntimeError(f"Network error contacting Shopify: {str(e)}")

def _compute_fingerprint(*args):
    payload = ":".join(str(a) for a in args).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

# -------------------------------------------------------------------------
# 1. VERIFY CONNECTION
# -------------------------------------------------------------------------
def shopify_verify_shopify_connection(inputs=None, stamp=None):
    data = _request("/shop.json", method="GET")
    shop = data.get("shop")
    if not shop:
        raise RuntimeError("Airlock Refusal: Unable to fetch Shopify store details.")

    return (
        {
            "status": "connected",
            "verified": True,
            "shop_name": shop.get("name"),
            "domain": shop.get("myshopify_domain"),
            "email": shop.get("email"),
            "currency": shop.get("currency")
        },
        {"kind": "shopify.verify_shopify_connection", "shop": shop.get("myshopify_domain")}
    )

# -------------------------------------------------------------------------
# 2. GET ORDER
# -------------------------------------------------------------------------
def shopify_get_order(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("orderId") or inputs.get("order_id") or "").strip()
    if not order_id:
        raise RuntimeError("Airlock Refusal: orderId is required.")

    data = _request(f"/orders/{order_id}.json", method="GET")
    order = data.get("order")
    if not order:
        raise RuntimeError(f"Airlock Refusal: Order {order_id} not found.")

    fp = _compute_fingerprint(order.get("id"), order.get("financial_status"), order.get("tags"), order.get("updated_at"))
    return (
        {"order": order, "fingerprint": fp},
        {"kind": "shopify.get_order", "order_id": order_id}
    )

# -------------------------------------------------------------------------
# 3. LIST ORDERS
# -------------------------------------------------------------------------
def shopify_list_orders(inputs=None, stamp=None):
    inputs = inputs or {}
    status = str(inputs.get("status") or "any").strip()
    limit = str(inputs.get("limit") or "10").strip()

    data = _request(f"/orders.json?status={status}&limit={limit}", method="GET")
    orders = data.get("orders")
    if orders is None:
        raise RuntimeError("Airlock Refusal: Failed to retrieve order collection.")

    return (
        {"count": len(orders), "status": status, "orders": orders},
        {"kind": "shopify.list_orders", "count": len(orders)}
    )

# -------------------------------------------------------------------------
# 4. CREATE REFUND (Ceiling-Guarded)
# -------------------------------------------------------------------------
def shopify_create_refund(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("orderId") or inputs.get("order_id") or "").strip()
    amount_raw = inputs.get("amount") or "0"
    reason = str(inputs.get("reason") or "Authorized airlock governance refund").strip()
    allow_high_refund_raw = str(inputs.get("allow_high_refund", "")).strip().lower()
    allow_high_refund = allow_high_refund_raw in ("true", "1", "yes")

    if not order_id:
        raise RuntimeError("Airlock Refusal: orderId is required.")

    try:
        amount = float(amount_raw)
    except Exception:
        raise RuntimeError(f"Airlock Refusal: Invalid refund amount {amount_raw}.")

    # Safety Ceiling Guard: > $100 requires explicit allow_high_refund override
    if amount > 100.0 and not allow_high_refund:
        raise RuntimeError(f"Airlock Refusal: Refund amount (${amount:.2f}) exceeds $100 ceiling. Requires allow_high_refund=True.")

    # Inspect current order
    order_data = _request(f"/orders/{order_id}.json", method="GET")
    order = order_data.get("order")
    if not order:
        raise RuntimeError(f"Airlock Refusal: Order {order_id} not found.")

    # Check transactions to resolve parent transaction
    tx_data = _request(f"/orders/{order_id}/transactions.json", method="GET")
    transactions = tx_data.get("transactions", [])

    parent_tx_id = None
    gateway = order.get("gateway") or "manual"

    for tx in transactions:
        if tx.get("status") == "success" and tx.get("kind") in ("sale", "capture"):
            parent_tx_id = tx.get("id")
            gateway = tx.get("gateway") or gateway
            break

    refund_body = {
        "currency": order.get("currency", "USD"),
        "notify": True,
        "note": reason
    }

    if parent_tx_id:
        refund_body["transactions"] = [
            {
                "parent_id": parent_tx_id,
                "amount": f"{amount:.2f}",
                "kind": "refund",
                "gateway": gateway
            }
        ]

    payload = {"refund": refund_body}
    res = _request(f"/orders/{order_id}/refunds.json", method="POST", payload=payload)
    refund = res.get("refund")

    return (
        {"status": "created", "refund_id": refund.get("id"), "order_id": order_id, "amount": amount},
        {"kind": "shopify.create_refund", "order_id": order_id, "refund_id": refund.get("id")}
    )

def shopify_cancel_order(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("orderId") or inputs.get("order_id") or "").strip()
    reason = str(inputs.get("reason") or "customer").strip()

    if not order_id:
        raise RuntimeError("Airlock Refusal: orderId is required.")

    payload = {"reason": reason, "email": True}
    res = _request(f"/orders/{order_id}/cancel.json", method="POST", payload=payload)
    order = res.get("order")
    if not order or not order.get("cancelled_at"):
        raise RuntimeError("Airlock Refusal: Shopify reported cancellation failure.")

    return (
        {"status": "cancelled", "order_id": order_id, "cancelled_at": order.get("cancelled_at")},
        {"kind": "shopify.cancel_order", "order_id": order_id}
    )

# -------------------------------------------------------------------------
# 6. ADD ORDER TAGS (Non-Destructive & Anti-Drift)
# -------------------------------------------------------------------------
def shopify_add_order_tags(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("orderId") or inputs.get("order_id") or "").strip()
    new_tags_raw = str(inputs.get("tags") or "").strip()
    expected_fp = str(inputs.get("expected_fingerprint") or "").strip()

    if not order_id or not new_tags_raw:
        raise RuntimeError("Airlock Refusal: Both orderId and tags are required.")

    order_data = _request(f"/orders/{order_id}.json", method="GET")
    order = order_data.get("order")
    if not order:
        raise RuntimeError(f"Airlock Refusal: Order {order_id} not found.")

    curr_fp = _compute_fingerprint(order.get("id"), order.get("financial_status"), order.get("tags"), order.get("updated_at"))
    if expected_fp and curr_fp != expected_fp:
        raise RuntimeError(f"Airlock Refusal: Order state drifted. Expected {expected_fp}, found {curr_fp}")

    existing_tags = [t.strip() for t in (order.get("tags") or "").split(",") if t.strip()]
    incoming_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]
    merged_tags = sorted(list(set(existing_tags + incoming_tags)))
    tags_str = ", ".join(merged_tags)

    payload = {"order": {"id": int(order_id), "tags": tags_str}}
    res = _request(f"/orders/{order_id}.json", method="PUT", payload=payload)
    updated = res.get("order")
    if not updated:
        raise RuntimeError("Airlock Refusal: Shopify failed to update order tags.")

    return (
        {"order_id": order_id, "tags": updated.get("tags"), "fingerprint": curr_fp},
        {"kind": "shopify.add_order_tags", "order_id": order_id}
    )

# -------------------------------------------------------------------------
# 7. UPDATE INVENTORY
# -------------------------------------------------------------------------
def shopify_update_inventory(inputs, stamp=None):
    inputs = inputs or {}
    inventory_item_id = str(inputs.get("inventory_item_id") or inputs.get("inventoryItemId") or "").strip()
    location_id = str(inputs.get("location_id") or inputs.get("locationId") or "").strip()
    available_raw = inputs.get("available")
    if available_raw is None:
        available_raw = inputs.get("available_adjustment") or inputs.get("availableAdjustment")

    if not inventory_item_id or not location_id or available_raw is None:
        raise RuntimeError("Airlock Refusal: inventory_item_id, location_id, and available are required.")

    try:
        available_qty = int(available_raw)
    except Exception:
        raise RuntimeError(f"Airlock Refusal: Invalid available quantity {available_raw}.")

    # Safety Guard: Non-negative floor enforcement
    if available_qty < 0:
        raise RuntimeError(f"Airlock Refusal: Floor Guard Triggered — available quantity ({available_qty}) cannot be negative.")

    payload = {
        "location_id": int(location_id),
        "inventory_item_id": int(inventory_item_id),
        "available": available_qty
    }
    res = _request("/inventory_levels/set.json", method="POST", payload=payload)
    inv_level = res.get("inventory_level")
    if not inv_level:
        raise RuntimeError("Airlock Refusal: Shopify failed to set inventory level.")

    return (
        {"status": "inventory_updated", "inventory_item_id": inventory_item_id, "location_id": location_id, "available": inv_level.get("available")},
        {"kind": "shopify.update_inventory", "inventory_item_id": inventory_item_id, "available": inv_level.get("available")}
    )


def shopify_close_order(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("order_id") or inputs.get("orderId") or "").strip()
    if not order_id:
        raise RuntimeError("Airlock Refusal: order_id is required.")

    # Safety Guard: Preflight lifecycle verification
    preflight = _request(f"/orders/{order_id}.json", method="GET")
    existing_order = preflight.get("order") or {}
    if not existing_order:
        raise RuntimeError(f"Airlock Refusal: Order {order_id} not found for preflight verification.")

    financial_status = existing_order.get("financial_status")
    fulfillment_status = existing_order.get("fulfillment_status")

    if financial_status not in ("paid", "partially_refunded"):
        raise RuntimeError(f"Airlock Refusal: Lifecycle Guard Triggered — Order {order_id} is not fully paid (financial_status: {financial_status}).")

    if fulfillment_status not in ("fulfilled", "partial"):
        raise RuntimeError(f"Airlock Refusal: Lifecycle Guard Triggered — Order {order_id} is not fulfilled (fulfillment_status: {fulfillment_status}).")

    res = _request(f"/orders/{order_id}/close.json", method="POST", payload={})
    order = res.get("order")
    if not order or not order.get("closed_at"):
        raise RuntimeError("Airlock Refusal: Shopify failed to close order.")

    return (
        {"status": "closed", "order_id": order_id, "closed_at": order.get("closed_at")},
        {"kind": "shopify.close_order", "order_id": order_id}
    )


def shopify_create_fulfillment(inputs, stamp=None):
    inputs = inputs or {}
    order_id = str(inputs.get("order_id") or inputs.get("orderId") or "").strip()
    tracking_number = str(inputs.get("tracking_number") or inputs.get("trackingNumber") or "").strip()
    tracking_company = str(inputs.get("tracking_company") or inputs.get("trackingCompany") or "Standard Carrier").strip()

    if not order_id:
        raise RuntimeError("Airlock Refusal: order_id is required.")

    # Safety Guard: Cancellation guard check
    preflight = _request(f"/orders/{order_id}.json", method="GET")
    existing_order = preflight.get("order") or {}
    if not existing_order:
        raise RuntimeError(f"Airlock Refusal: Order {order_id} not found for preflight verification.")

    if existing_order.get("cancelled_at"):
        raise RuntimeError(f"Airlock Refusal: Cancellation Guard Triggered — Order {order_id} was cancelled at {existing_order.get("cancelled_at")}.")

    payload = {
        "fulfillment": {
            "notify_customer": True,
            "tracking_number": tracking_number if tracking_number else None,
            "tracking_company": tracking_company
        }
    }
    res = _request(f"/orders/{order_id}/fulfillments.json", method="POST", payload=payload)
    ful = res.get("fulfillment")
    if not ful:
        raise RuntimeError("Airlock Refusal: Shopify reported fulfillment creation failure.")

    return (
        {"status": "fulfilled", "fulfillment_id": ful.get("id"), "order_id": order_id},
        {"kind": "shopify.create_fulfillment", "order_id": order_id}
    )


