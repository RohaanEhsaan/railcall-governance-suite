"""
generate_digest_csv.py

Pulls real, live ticket data through rohan/zendesk-governance's own
list_open_tickets() function -- the same governed, tested code from the
module itself, not a raw API call -- and writes it as a CSV shaped for
`railcall workflow run <csv> --template '...' --live`.

This is the bridge between your governed module and RailCall's native
CSV/webhook broadcaster: the READ is airlocked and signed the same way
every other command in your module is; the CSV output is just this
script's own plain file write (which is exactly what a workflow's own
"transform" step would do, just done here in one call for simplicity).

Run:
    export ZENDESK_SUBDOMAIN="yourcompany"
    export ZENDESK_EMAIL="agent@yourcompany.com"
    export ZENDESK_API_TOKEN="token_..."
    python generate_digest_csv.py --limit 10 --out escalations.csv
"""
import argparse
import csv
import os
import sys

# Adjust this import path to wherever your zendesk-governance handler.py
# actually lives on disk (e.g. C:/zendesk_governance/handlers/handler.py)
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from handlers import handler as zendesk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", default="escalations.csv")
    args = parser.parse_args()

    secrets = {
        "ZENDESK_SUBDOMAIN": os.environ.get("ZENDESK_SUBDOMAIN", ""),
        "ZENDESK_EMAIL": os.environ.get("ZENDESK_EMAIL", ""),
        "ZENDESK_API_TOKEN": os.environ.get("ZENDESK_API_TOKEN", ""),
    }
    if not all(secrets.values()):
        print("[ERROR] Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN first.")
        sys.exit(1)

    gen = zendesk.list_open_tickets({"limit": args.limit}, secrets)
    preview = next(gen)
    print(f"[PREVIEW] {preview['message']}")
    result = next(gen)
    tickets = result["receipt"]["tickets"]
    print(f"[OK] Retrieved {len(tickets)} live open tickets.")

    if not tickets:
        print("[WARN] No open tickets found -- nothing to write. "
              "Create a test ticket in Zendesk first, or the digest will be empty.")
        return

    fieldnames = ["id", "subject", "status", "priority", "updated_at"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in tickets:
            writer.writerow({k: t.get(k, "") for k in fieldnames})

    print(f"[OK] Wrote {len(tickets)} rows to {args.out}")
    print("\nNext steps:")
    print(f"  railcall build {args.out}")
    print(f"  railcall set discord-webhook <your-discord-webhook-url>")
    print(f"  railcall workflow run {args.out} "
          "--template '🎫 Ticket #{{id}}: {{subject}} — {{status}} / {{priority}} (updated {{updated_at}})'")
    print(f"  railcall workflow run {args.out} --template '...' --live")


if __name__ == "__main__":
    main()
