"""rohan/stripe-governance — Governed Airlock Handler.

Strict execution contract: def stripe_<cmd>(inputs=None, stamp=None) -> (result, receipt)
Vault binding: globals()["__rc_helpers__"]["vault_get"]("stripe")
Airlock safety: Anti-drift checks, ceiling/floor guards, idempotency assertions.
"""
import hashlib
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

STRIPE_API_BASE = "https://api.stripe.com/v1"

def _creds():
    helpers = globals().get("__rc_helpers__")
    if helpers and "vault_get" in helpers:
        try:
            entry = helpers["vault_get"]("stripe")
            if isinstance(entry, str):
                return entry.strip()
            if isinstance(entry, dict):
                return str(entry.get("STRIPE_SECRET_KEY") or entry.get("api_key") or "").strip()
        except Exception:
            pass
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()

def _stripe_request(endpoint, token, method="GET", form_data=None, idempotency_key=None):
    if not token:
        token = _creds()
    if not token:
        raise RuntimeError("Airlock Refusal: No Stripe credentials found in Station Vault.")

    url = f"{STRIPE_API_BASE}{endpoint}"
    data_bytes = None
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "RailCall-Stripe-Governance/1.0"
    }

    if idempotency_key:
        headers["Idempotency-Key"] = str(idempotency_key)

    if method in ("POST", "DELETE"):
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if form_data:
            data_bytes = urllib.parse.urlencode(form_data, doseq=True).encode("utf-8")
        else:
            data_bytes = b""
    elif method == "GET" and form_data:
        url = f"{url}?{urllib.parse.urlencode(form_data, doseq=True)}"

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Stripe API Error ({e.code}): {err_body}")
    except Exception as e:
        raise RuntimeError(f"Network error contacting Stripe: {str(e)}")

# -------------------------------------------------------------------------
# 1. VERIFY CONNECTION
# -------------------------------------------------------------------------
def stripe_verify_connection(inputs=None, stamp=None):
    tok = _creds()
    if not tok:
        raise RuntimeError("Airlock Refusal: Missing STRIPE_SECRET_KEY in Station Vault.")

    account = _stripe_request("/account", tok, method="GET")
    acc_id = account.get("id", "unknown")
    livemode = account.get("charges_enabled", False)

    return (
        {"status": "connected", "verified": True, "account_id": acc_id, "livemode": livemode},
        {"kind": "stripe.verify_connection", "account_id": acc_id}
    )

# -------------------------------------------------------------------------
# 2. CREATE CUSTOMER (Deduplication Guarded)
# -------------------------------------------------------------------------
def stripe_create_customer(inputs=None, stamp=None):
    inputs = inputs or {}
    email = str(inputs.get("email") or "").strip()
    name = str(inputs.get("name") or "").strip()
    phone = str(inputs.get("phone") or "").strip()

    if not email:
        raise RuntimeError("Airlock Refusal: email is required to register customer.")

    tok = _creds()
    existing = _stripe_request("/customers", tok, method="GET", form_data={"email": email, "limit": 1})
    if existing.get("data"):
        cust = existing["data"][0]
        return (
            {"status": "already_exists", "customer_id": cust.get("id"), "email": email, "reused": True},
            {"kind": "stripe.create_customer", "customer_id": cust.get("id"), "action": "reused"}
        )

    form = {"email": email}
    if name:
        form["name"] = name
    if phone:
        form["phone"] = phone

    idem_key = f"cust_create_{hashlib.sha256(email.encode()).hexdigest()[:16]}"
    cust = _stripe_request("/customers", tok, method="POST", form_data=form, idempotency_key=idem_key)

    return (
        {"status": "created", "customer_id": cust.get("id"), "email": email},
        {"kind": "stripe.create_customer", "customer_id": cust.get("id"), "action": "created"}
    )

# -------------------------------------------------------------------------
# 3. CREATE INVOICE (Safety Checked)
# -------------------------------------------------------------------------
def stripe_create_invoice(inputs=None, stamp=None):
    inputs = inputs or {}
    customer_id = str(inputs.get("customer_id") or "").strip()
    auto_advance = bool(inputs.get("auto_advance", False))
    description = str(inputs.get("description") or "Governed airlock invoice").strip()
    amount_cents_raw = inputs.get("amount_cents")

    if not customer_id:
        raise RuntimeError("Airlock Refusal: customer_id is required.")

    tok = _creds()

    if amount_cents_raw is not None:
        try:
            amount_cents = int(amount_cents_raw)
        except Exception:
            raise RuntimeError(f"Airlock Refusal: amount_cents must be an integer (received {amount_cents_raw}).")
        if amount_cents <= 0:
            raise RuntimeError(f"Airlock Refusal: Floor Guard Triggered — amount_cents must be positive (received {amount_cents}).")
        
        _stripe_request(
            "/invoiceitems",
            tok,
            method="POST",
            form_data={
                "customer": customer_id,
                "amount": amount_cents,
                "currency": "usd",
                "description": description
            }
        )

    inv = _stripe_request(
        "/invoices",
        tok,
        method="POST",
        form_data={"customer": customer_id, "auto_advance": str(auto_advance).lower(), "description": description}
    )

    return (
        {"status": "created", "invoice_id": inv.get("id"), "customer": customer_id, "total": inv.get("total", 0)},
        {"kind": "stripe.create_invoice", "invoice_id": inv.get("id")}
    )

# -------------------------------------------------------------------------
# 4. CREATE PAYMENT LINK (Floor Guarded)
# -------------------------------------------------------------------------
def stripe_create_payment_link(inputs=None, stamp=None):
    inputs = inputs or {}
    price_id = str(inputs.get("price_id") or "").strip()
    raw_qty = inputs.get("quantity")
    try:
        quantity = int(1 if raw_qty is None else raw_qty)
    except Exception:
        quantity = 1

    if not price_id:
        raise RuntimeError("Airlock Refusal: price_id is required.")
    if quantity <= 0:
        raise RuntimeError(f"Airlock Refusal: Floor Guard Triggered — quantity must be positive (received {quantity}).")

    tok = _creds()
    pl = _stripe_request(
        "/payment_links",
        tok,
        method="POST",
        form_data={"line_items[0][price]": price_id, "line_items[0][quantity]": quantity}
    )

    return (
        {"status": "created", "payment_link_id": pl.get("id"), "url": pl.get("url")},
        {"kind": "stripe.create_payment_link", "payment_link_id": pl.get("id")}
    )

# -------------------------------------------------------------------------
# 5. REFUND CHARGE (Anti-Drift & Idempotency Locked)
# -------------------------------------------------------------------------
def stripe_refund_charge(inputs=None, stamp=None):
    inputs = inputs or {}
    charge_id = str(inputs.get("charge_id") or "").strip()
    amount_raw = inputs.get("amount") if inputs.get("amount") is not None else inputs.get("amount_cents")
    reason = str(inputs.get("reason") or "requested_by_customer").strip()
    expected_fingerprint = str(inputs.get("expected_fingerprint") or "").strip()

    if not charge_id:
        raise RuntimeError("Airlock Refusal: charge_id is required.")

    tok = _creds()
    charge = _stripe_request(f"/charges/{charge_id}", tok, method="GET")
    if charge.get("refunded"):
        raise RuntimeError(f"Airlock Refusal: Charge {charge_id} has already been refunded.")

    raw_state = f"{charge.get('id')}:{charge.get('amount')}:{charge.get('amount_refunded')}:{charge.get('status')}"
    current_fingerprint = hashlib.sha256(raw_state.encode("utf-8")).hexdigest()

    if expected_fingerprint and expected_fingerprint != current_fingerprint:
        raise RuntimeError(f"Airlock Refusal: Anti-Drift Lock Triggered — State fingerprint changed. Expected {expected_fingerprint}, got {current_fingerprint}.")

    form = {"charge": charge_id, "reason": reason}
    amt_key = "full"
    if amount_raw is not None and str(amount_raw).strip() != "":
        try:
            amt = int(amount_raw)
            if amt <= 0:
                raise RuntimeError(f"Airlock Refusal: Refund amount must be positive, got {amt}.")
            form["amount"] = amt
            amt_key = str(amt)
        except ValueError:
            raise RuntimeError(f"Airlock Refusal: Invalid refund amount {amount_raw}.")

    idem_key = f"rc_ref_{hashlib.sha256(f'{charge_id}:{amt_key}'.encode()).hexdigest()[:24]}"
    ref = _stripe_request("/refunds", tok, method="POST", form_data=form, idempotency_key=idem_key)

    return (
        {
            "status": "refunded",
            "refund_id": ref.get("id"),
            "amount": ref.get("amount"),
            "charge": charge_id,
            "state_fingerprint": current_fingerprint
        },
        {"kind": "stripe.refund_charge", "refund_id": ref.get("id"), "charge_id": charge_id}
    )

# -------------------------------------------------------------------------
# 6. ADJUST CREDIT BALANCE (Ceiling Guarded)
# -------------------------------------------------------------------------
def stripe_adjust_credit_balance(inputs=None, stamp=None):
    inputs = inputs or {}
    customer_id = str(inputs.get("customer_id") or "").strip()
    
    raw_amount = inputs.get("amount_cents") if inputs.get("amount_cents") is not None else inputs.get("amount")
    try:
        amount = int(raw_amount)
    except Exception:
        raise RuntimeError("Airlock Refusal: amount_cents is required and must be an integer.")

    currency = str(inputs.get("currency") or "usd").strip().lower()

    raw_override = inputs.get("override_ceiling", False)
    if isinstance(raw_override, str):
        override_ceiling = raw_override.strip().lower() in ("true", "1", "yes")
    else:
        override_ceiling = bool(raw_override)

    # Financial Ceiling Guard: enforce $100 limit (10,000 cents) unless overridden
    if abs(amount) > 10000 and not override_ceiling:
        raise RuntimeError(f"Airlock Refusal: Ceiling Guard Triggered — balance adjustment of {amount} cents exceeds $100 ceiling (max 10,000 cents). Requires override_ceiling=True.")

    tok = _creds()
    tx = _stripe_request(
        f"/customers/{customer_id}/balance_transactions",
        tok,
        method="POST",
        form_data={"amount": amount, "currency": currency, "description": "Station governed credit balance adjustment"}
    )

    return (
        {"status": "adjusted", "transaction_id": tx.get("id"), "new_ending_balance": tx.get("ending_balance")},
        {"kind": "stripe.adjust_credit_balance", "transaction_id": tx.get("id")}
    )

# -------------------------------------------------------------------------
# 7. CANCEL SUBSCRIPTION (Termination Guarded: Safe Period-End Default)
# -------------------------------------------------------------------------
def stripe_cancel_subscription(inputs=None, stamp=None):
    inputs = inputs or {}
    subscription_id = str(inputs.get("subscription_id") or "").strip()
    immediately = bool(inputs.get("immediately", False))

    if not subscription_id:
        raise RuntimeError("Airlock Refusal: subscription_id is required.")

    tok = _creds()
    sub = _stripe_request(f"/subscriptions/{subscription_id}", tok, method="GET")
    status = sub.get("status")
    if status in ("canceled", "incomplete_expired"):
        raise RuntimeError(f"Airlock Refusal: Subscription {subscription_id} is already in terminal state {status}.")

    if immediately:
        res = _stripe_request(f"/subscriptions/{subscription_id}", tok, method="DELETE")
        action = "canceled_immediately"
    else:
        res = _stripe_request(
            f"/subscriptions/{subscription_id}",
            tok,
            method="POST",
            form_data={"cancel_at_period_end": "true"}
        )
        action = "scheduled_for_period_end"

    return (
        {
            "status": "canceled",
            "subscription_id": subscription_id,
            "action": action,
            "cancel_at_period_end": res.get("cancel_at_period_end", False),
            "current_period_end": res.get("current_period_end")
        },
        {"kind": "stripe.cancel_subscription", "subscription_id": subscription_id, "action": action}
    )

# -------------------------------------------------------------------------
# 8. VOID INVOICE
# -------------------------------------------------------------------------
def stripe_void_invoice(inputs=None, stamp=None):
    inputs = inputs or {}
    invoice_id = str(inputs.get("invoice_id") or "").strip()
    if not invoice_id:
        raise RuntimeError("Airlock Refusal: invoice_id is required.")

    tok = _creds()
    curr = _stripe_request(f"/invoices/{invoice_id}", tok, method="GET")
    curr_status = curr.get("status")
    if curr_status in ("void", "paid"):
        raise RuntimeError(f"Airlock Refusal: Cannot void invoice {invoice_id} with terminal status '{curr_status}'.")

    inv = _stripe_request(f"/invoices/{invoice_id}/void", tok, method="POST")

    return (
        {"status": "voided", "invoice_id": invoice_id, "status_code": inv.get("status")},
        {"kind": "stripe.void_invoice", "invoice_id": invoice_id}
    )

# -------------------------------------------------------------------------
# 9. GET CUSTOMER OVERVIEW
# -------------------------------------------------------------------------
def stripe_get_customer_overview(inputs=None, stamp=None):
    inputs = inputs or {}
    customer_id = str(inputs.get("customer_id") or "").strip()
    if not customer_id:
        raise RuntimeError("Airlock Refusal: customer_id is required.")

    tok = _creds()
    cust = _stripe_request(f"/customers/{customer_id}", tok, method="GET")

    overview = {
        "id": cust.get("id"),
        "email": cust.get("email"),
        "balance": cust.get("balance"),
        "currency": cust.get("currency"),
        "delinquent": cust.get("delinquent", False),
        "created": cust.get("created")
    }

    return (
        {"status": "found", "customer": overview},
        {"kind": "stripe.get_customer_overview", "customer_id": customer_id}
    )

# -------------------------------------------------------------------------
# 10. LIST INVOICES
# -------------------------------------------------------------------------
def stripe_list_invoices(inputs=None, stamp=None):
    inputs = inputs or {}
    customer_id = str(inputs.get("customer_id") or "").strip()
    try:
        limit = min(int(inputs.get("limit") or 10), 100)
    except Exception:
        limit = 10

    params = {"limit": limit}
    if customer_id:
        params["customer"] = customer_id

    tok = _creds()
    data = _stripe_request("/invoices", tok, method="GET", form_data=params)
    invoices = [
        {"id": item.get("id"), "amount_due": item.get("amount_due"), "status": item.get("status"), "created": item.get("created")}
        for item in data.get("data", [])
    ]

    return (
        {"status": "success", "count": len(invoices), "invoices": invoices},
        {"kind": "stripe.list_invoices", "total_retrieved": len(invoices)}
    )
