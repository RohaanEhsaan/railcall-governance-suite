# Stripe Financial Governance Airlock (`rohan/stripe-governance`)

`contest:round2`

Autonomous enterprise governance airlock for Stripe API operations, featuring optional anti-drift state locks, strict credit ceiling guards, and deterministic preflight previews.

---

## 10-Minute Setup Guide

### 1. Installation

Install the cryptographically signed module into your local Station:

```bash
railcall market install rohan/stripe-governance
```

### 2. Configure Scoped Stripe API Key

Obtain a restricted API key from your [Stripe Dashboard](https://dashboard.stripe.com/apikeys).

Store your key in the Station Vault or export it in your environment:

```bash
export STRIPE_API_KEY="rk_live_..."
```

> **CREDENTIAL HANDLING**: This module accesses `STRIPE_API_KEY` strictly via Station Vault (`vault_get("stripe")`) or controlled environment discovery via `_creds()`. Secrets are never persisted to disk, never logged to stdout, and never included in receipts or return payloads.

### 3. Verify in Studio

Confirm the module displays as **Loaded** with 9 registered commands, and run `stripe_verify_connection` to confirm Stripe identity.

---

## Governed Commands (9 Actions)

| Command ID | Mode | Impact Tier | Guardrail Architecture |
| :--- | :--- | :--- | :--- |
| `stripe_verify_connection` | Read | READ_ONLY | Validates API key, account identity, and testmode status. |
| `stripe_create_customer` | Write | MEDIUM | Provisions new customer records with email deduplication metadata. |
| `stripe_create_invoice` | Write | MEDIUM | Creates line-item charges via invoiceitems before issuing invoice; enforces positive amount floor. |
| `stripe_create_payment_link` | Write | MEDIUM | Generates governed checkout links; validates positive quantity. |
| `stripe_refund_charge` | Write | HIGH | Supports optional caller-supplied `expected_fingerprint` to abort if charge state drifted mid-review. |
| `stripe_adjust_credit_balance` | Write | HIGH | $1,000 (100,000 cents) ceiling floor guard; requires explicit `override_ceiling=true` for larger deltas. |
| `stripe_cancel_subscription` | Write | HIGH | Guards against immediate cancellation by defaulting to safe end-of-period termination. |
| `stripe_void_invoice` | Write | HIGH | Preflight state verification; refuses void requests on terminal (already void/paid) invoices. |
| `stripe_get_customer_overview` | Read | READ_ONLY | Retrieves consolidated customer profile, balance, and delinquency state for pre-mutation discovery. |

---

## Defensive Engineering Highlights

* **Caller-Supplied Anti-Drift Verification (`stripe_refund_charge`)**: Accepts an optional `expected_fingerprint` from a prior inspection call — aborts if charge state drifted mid-review; omitting it skips drift check.
* **Ceiling Guard Floor (`stripe_adjust_credit_balance`)**: Blocks adjustments exceeding $1,000 unless callers explicitly assert `override_ceiling=true`.
* **Preflight Lifecycle Guard (`stripe_void_invoice`)**: Fetches invoice state prior to mutation to block invalid voids on terminal states.
* **Station v1.5 Airlock Contract**: All mutations return strict `(result, receipt)` tuples with deterministic verification metadata.

---

## Verification & Testing

### 1. Offline Deterministic Test Suite (Zero Network Egress)
Verifies payload framing, ceiling guards, and lifecycle validation completely offline:

```bash
python test_handler.py
```

```text
Ran 12 tests in 0.010s - OK
```

### 2. Live API Round-Trip Harness (No Mocks / No Stubs)
Performs live end-to-end API calls against Stripe live/test APIs:

```bash
export STRIPE_API_KEY="rk_test_..."
python live_test.py
```
