# Zendesk Support Governance Airlock (`rohan/zendesk-governance`)

`contest:round2`

Autonomous enterprise governance airlock for the Zendesk Support API, featuring cryptographic anti-drift state locks, non-destructive tag operations, and deterministic preflight previews.

---

## 10-Minute Setup Guide

### 1. Installation

Install the cryptographically signed module into your local Station:

```bash
railcall market install rohan/zendesk-governance
```

### 2. Configure Zendesk API Credentials

Create an API token in your Zendesk Admin Center (Apps and integrations > APIs > Zendesk API):
1. Enable Token Access.
2. Generate an active API Token.

Store your credentials in the Station Vault or export them in your environment:

```bash
export ZENDESK_SUBDOMAIN="yourcompany"
export ZENDESK_EMAIL="agent@yourcompany.com"
export ZENDESK_API_TOKEN="token_..."
```

> **CREDENTIAL HANDLING**: This module accesses `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, and `ZENDESK_API_TOKEN` strictly via Station Vault (`vault_get("zendesk")`) or controlled environment discovery via `_creds()`. Secrets are never persisted to disk, never logged to stdout, and never included in audit receipts or return payloads.

### 3. Verify in Studio

Confirm the module displays as **Loaded** with 7 registered commands, then run `zendesk_verify_connection` to confirm agent permissions and airlock operational status.

---

## Governed Commands (7 Actions)

| Command ID | Mode | Impact Tier | Guardrail Architecture |
| :--- | :--- | :--- | :--- |
| `zendesk_verify_connection` | Read | READ_ONLY | Validates agent identity, permissions role, and airlock operational health. |
| `zendesk_get_ticket` | Read | READ_ONLY | Extracts comprehensive ticket state, SLA status, priority, and state fingerprint. |
| `zendesk_list_open_tickets` | Read | READ_ONLY | Queries active SLA queue filtering for status < solved for pre-mutation discovery. |
| `zendesk_update_ticket_status` | Write | HIGH | Accepts optional `expected_fingerprint` from `zendesk_get_ticket`; aborts if ticket was modified mid-review. |
| `zendesk_escalate_ticket_priority` | Write | HIGH | Optional anti-drift concurrency protection across priority and update timestamps. |
| `zendesk_post_ticket_reply` | Write | MEDIUM / HIGH | Tiered safety check; marks internal notes as MEDIUM, public responses as HIGH. |
| `zendesk_add_ticket_tags` | Write | MEDIUM | Non-destructive tag appends via POST; prevents clobbering existing tags. |

---

## Defensive Engineering Highlights

* **Caller-Supplied Anti-Drift Verification (`zendesk_update_ticket_status`, `zendesk_escalate_ticket_priority`)**: Accepts an optional `expected_fingerprint` from a prior `zendesk_get_ticket` call. Aborts if ticket was modified concurrently; omitting it skips the check.
* **Non-Destructive Tag Appends (`zendesk_add_ticket_tags`)**: Dispatches using HTTP POST to append tags directly to the ticket, avoiding the destructive tag overwrite inherent to PUT replacements.
* **SLA Queue Search Filtering (`zendesk_list_open_tickets`)**: Searches using `type:ticket status<solved` to query only unresolved SLA work.
* **Station v1.5 Airlock Contract**: All mutations return strict `(result, receipt)` tuples with deterministic verification metadata.

---

## Verification & Testing

### 1. Offline Deterministic Test Suite (Zero Network Egress)
Verifies payload framing, non-destructive tag routing, state fingerprint drift aborts, and input validation completely offline:

```bash
python test_handler.py
```

```text
Ran 11 tests in 0.007s - OK
```

### 2. Live Zendesk Integration Harness (Stub-Free)
Performs live end-to-end API calls against your Zendesk Support instance:

```bash
export ZENDESK_SUBDOMAIN="yourcompany"
export ZENDESK_EMAIL="agent@yourcompany.com"
export ZENDESK_API_TOKEN="token_..."
python live_test.py
```
