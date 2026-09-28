# Stripe Financial Governance Airlock

An enterprise-grade governance module for Stripe billing operations built for the RailCall platform.

Every mutating action follows RailCall's governance airlock: **preview -> approve -> execute -> signed receipt**.

## Capabilities
* `refund_charge` (External Mutation): Inspects live Stripe charges, calculates balances, formats human-readable previews, and executes partial or full refunds upon operator approval.

## Setup & Quickstart (< 5 minutes)

1. **Store credentials in the RailCall vault:**
   ```bash
   railcall secrets set STRIPE_SECRET_KEY=sk_test_...
   ```
2. **Simulate a Preview (Dry-Run):**
   ```bash
   railcall run . --action refund_charge --dry-run --data '{"charge_id": "pi_...", "amount_cents": 1000}'
   ```
3. **Execute upon human sign-off:**
   ```bash
   railcall run . --action refund_charge --data '{"charge_id": "pi_...", "amount_cents": 1000}'
   ```
## Trust & Safe Auth Surface
   * Zero Secret Retention: API keys are retrieved via memory-only runtime injection and are never written to disk, databases, or logs.
   * Cryptographic Receipts: Every executed action produces an offline-verifiable Ed25519 signed receipt.
   * Deterministic Previews: Pre-flight calculations verify charge state against Stripe before requesting human sign-off.