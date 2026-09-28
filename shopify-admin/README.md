# Shopify Admin Governance Airlock (`rohan/shopify-admin`)

`contest:round2`

Autonomous enterprise governance airlock for the Shopify Admin REST API, featuring optional anti-drift state locks, stock floor protection, and deterministic preflight previews.

---

## 10-Minute Setup Guide

### 1. Installation

Install the cryptographically signed module into your local Station:

```bash
railcall market install rohan/shopify-admin
```

### 2. Configure Shopify Admin API Credentials

Create a Custom App in your Shopify Store Admin (Settings > Apps and sales channels > Develop apps):
1. Configure Admin API scopes: `read_orders`, `write_orders`, `read_inventory`, `write_inventory`, `write_fulfillments`.
2. Install the app and generate an Admin API Access Token (`shpat_...`).

Store your credentials in the Station Vault or export them in your environment:

```bash
export SHOPIFY_SHOP_DOMAIN="your-store.myshopify.com"
export SHOPIFY_ACCESS_TOKEN="shpat_..."
```

> **CREDENTIAL HANDLING**: This module accesses `SHOPIFY_SHOP_DOMAIN` and `SHOPIFY_ACCESS_TOKEN` strictly via Station Vault (`vault_get("shopify")`) or controlled environment discovery via `_creds()`. Secrets are never persisted to disk, never logged to stdout, and never included in audit receipts or return payloads.

### 3. Verify in Studio

Confirm the module shows as **Loaded** with 9 registered commands, then run `shopify_verify_connection` to confirm store identity and live rate-limit buckets.

---

## Governed Commands (9 Actions)

| Command ID | Mode | Impact Tier | Guardrail Architecture |
| :--- | :--- | :--- | :--- |
| `shopify_verify_connection` | Read | READ_ONLY | Validates shop identity, currency, and live rate-limit bucket. |
| `shopify_get_order` | Read | READ_ONLY | Returns financial status, fulfillment status, refund total, tags, and line count. |
| `shopify_list_orders` | Read | READ_ONLY | Queries recent orders filtered by status for pre-mutation discovery. |
| `shopify_create_refund` | Write | HIGH | Resolves parent transaction IDs; enforces $100 ceiling guard requiring explicit `allow_high_refund=true` for larger payouts. |
| `shopify_cancel_order` | Write | HIGH | Order guard; hard refusal if order is already fulfilled or already cancelled. |
| `shopify_add_order_tags` | Write | MEDIUM | Tag deduplication; accepts optional caller-supplied `expected_fingerprint` to abort if tags drifted. |
| `shopify_update_inventory` | Write | HIGH | Safety floor check; unconditionally blocks negative inventory allocations. |
| `shopify_close_order` | Write | MEDIUM | Verified lifecycle transition; verifies order is paid or partially refunded and not already closed. |
| `shopify_create_fulfillment` | Write | HIGH | Commits carrier tracking with preflight check verifying order is not cancelled. |

---

## Defensive Engineering Highlights

* **Caller-Supplied Anti-Drift Verification (`shopify_add_order_tags`)**: Accepts an optional `expected_fingerprint` from a prior `shopify_get_order` call to abort if order state changed concurrently.
* **Refund Safety Ceiling (`shopify_create_refund`)**: Enforces a strict $100 floor ceiling per invocation; refunds over $100 require explicit `allow_high_refund=true`.
* **Parent Transaction Resolution (`shopify_create_refund`)**: Inspects order state and maps to valid parent capture/sale IDs before dispatching refund payloads.
* **Lifecycle & Floor Guards (`shopify_cancel_order`, `shopify_update_inventory`)**: Strictly blocks mutations on terminal states and unconditionally enforces `available >= 0`.

---

## Verification & Testing

### 1. Offline Deterministic Test Suite (Zero Network Egress)
Verifies payload framing, stock floor bounds, state fingerprint drift aborts, and input validation completely offline:

```bash
python test_handler.py
```

```text
Ran 15 tests in 0.008s - OK
```

### 2. Live Store Integration Harness (Stub-Free)
Performs live end-to-end API calls against your Shopify development sandbox:

```bash
export SHOPIFY_SHOP_DOMAIN="your-store.myshopify.com"
export SHOPIFY_ACCESS_TOKEN="shpat_..."
python live_test.py
```
