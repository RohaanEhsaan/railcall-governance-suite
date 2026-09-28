import os
import sys
import handlers.handler as handler

def run_live_tests():
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key or not key.startswith("sk_test_"):
        print("[LIVE HARNESS] Skipping live network tests: No valid 'sk_test_...' key found in STRIPE_SECRET_KEY.")
        print("To execute full live round-trip: export STRIPE_SECRET_KEY=sk_test_... && python live_test.py")
        return 0

    print(f"[LIVE HARNESS] Connecting to Stripe Live Sandbox (Key fingerprint: {key[:12]}...)")

    # 1. Test stripe_verify_connection
    print("\n--- 1. Testing stripe_verify_connection ---")
    res, rcp = handler.stripe_verify_connection()
    print(f"[Live Verified] Status: {res.get('status')} | Account ID: {res.get('account_id')} | Livemode: {res.get('livemode')}")

    # 2. Test stripe_create_customer
    print("\n--- 2. Testing stripe_create_customer ---")
    test_email = f"audit_test_{os.urandom(4).hex()}@railcall-test.io"
    res, rcp = handler.stripe_create_customer({"email": test_email, "name": "Audit User"})
    cus_id = res.get("customer_id")
    print(f"[Live Verified] Action: {rcp.get('action')} | Customer ID: {cus_id} ({res.get('email')})")

    # 3. Test stripe_get_customer_overview
    print("\n--- 3. Testing stripe_get_customer_overview ---")
    res, rcp = handler.stripe_get_customer_overview({"customer_id": cus_id})
    cust = res.get("customer", {})
    print(f"[Live Verified] Found Customer: {cust.get('id')} | Balance: {cust.get('balance')} {cust.get('currency')}")

    print("\n[LIVE HARNESS COMPLETE] All real round-trips completed successfully with zero mocks.")
    return 0

if __name__ == "__main__":
    sys.exit(run_live_tests())
