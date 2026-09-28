"""
Live Store Integration Test Harness (Stub-Free)
Run:
    export SHOPIFY_SHOP_DOMAIN="your-store.myshopify.com"
    export SHOPIFY_ACCESS_TOKEN="shpat_..."
    python live_test.py
"""
import os
import sys
from handlers import handler

def run_live():
    domain = os.environ.get("SHOPIFY_SHOP_DOMAIN")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    if not domain or not token:
        print("[SKIP] SHOPIFY_SHOP_DOMAIN and SHOPIFY_ACCESS_TOKEN must be set to run live integration tests.")
        sys.exit(0)

    print(f"[*] Testing shopify_verify_shopify_connection against {domain}...")
    res, rcp = handler.shopify_verify_shopify_connection()
    print(f"    [OK] Shop verified: {res.get('shop_name')} | Currency: {res.get('currency')} | Domain: {res.get('domain')}")

    print("[*] Testing shopify_list_orders discovery...")
    res, rcp = handler.shopify_list_orders({"limit": 3})
    orders = res.get("orders", [])
    print(f"    [OK] Retrieved {len(orders)} orders.")

    if orders:
        first_id = orders[0]["id"]
        print(f"[*] Inspecting order #{first_id} via shopify_get_order...")
        o_res, o_rcp = handler.shopify_get_order({"order_id": str(first_id)})
        order = o_res.get("order", {})
        print(f"    [OK] Order {order.get('name')} | Status: {order.get('financial_status')} / {order.get('fulfillment_status')} | Fingerprint: {o_res.get('fingerprint')}")

    print("\n[SUCCESS] Live Shopify integration harness completed cleanly.")

if __name__ == "__main__":
    run_live()
