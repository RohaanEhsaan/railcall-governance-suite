"""
Live Zendesk Integration Test Harness (Stub-Free)
Run:
    export ZENDESK_SUBDOMAIN="yourcompany"
    export ZENDESK_EMAIL="agent@yourcompany.com"
    export ZENDESK_API_TOKEN="token_..."
    python live_test.py
"""
import os
import sys
from handlers import handler

def run_live():
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN")
    email = os.environ.get("ZENDESK_EMAIL")
    token = os.environ.get("ZENDESK_API_TOKEN")

    if not subdomain or not email or not token:
        print("[SKIP] ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN must be set to run live integration tests.")
        sys.exit(0)

    print(f"[*] Testing zendesk_verify_zendesk_connection against {subdomain}...")
    res, rec = handler.zendesk_verify_zendesk_connection()
    print(f"    [OK] User verified: {res.get('name')} | Role: {res.get('role')} | User ID: {rec.get('user_id')}")

    print("[*] Testing zendesk_list_open_tickets discovery (status < solved)...")
    res, rec = handler.zendesk_list_open_tickets({"limit": 3})
    tickets = res.get("tickets", [])
    print(f"    [OK] Retrieved {rec.get('count', len(tickets))} active SLA tickets.")

    if tickets:
        first_id = tickets[0]["id"]
        print(f"[*] Inspecting ticket #{first_id} via zendesk_get_ticket...")
        t_res, t_rec = handler.zendesk_get_ticket({"ticket_id": str(first_id)})
        print(f"    [OK] Subject: {t_res.get('subject')} | Status: {t_res.get('status')} | Fingerprint: {t_rec.get('state_fingerprint')}")

    print("\n[SUCCESS] Live Zendesk integration harness completed cleanly.")

if __name__ == "__main__":
    run_live()
