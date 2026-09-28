import urllib.request
import urllib.error
import json
import base64
import hashlib
import os
from pathlib import Path

# -------------------------------------------------------------------------
# CREDENTIALS & AIRLOCK RESOLUTION
# -------------------------------------------------------------------------
def _creds():
    # 1. Primary: Station Vault
    helpers = globals().get("__rc_helpers__")
    if helpers and "vault_get" in helpers:
        try:
            entry = helpers["vault_get"]("zendesk")
            if isinstance(entry, dict):
                subdomain = entry.get("ZENDESK_SUBDOMAIN") or entry.get("subdomain")
                email = entry.get("ZENDESK_EMAIL") or entry.get("email")
                tok = entry.get("ZENDESK_API_TOKEN") or entry.get("api_token")
                if subdomain and email and tok:
                    return str(subdomain).strip(), str(email).strip(), str(tok).strip()
        except Exception:
            pass

    # 2. Environment fallback
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN")
    email = os.environ.get("ZENDESK_EMAIL")
    tok = os.environ.get("ZENDESK_API_TOKEN")
    if subdomain and email and tok:
        return subdomain.strip(), email.strip(), tok.strip()

    # 3. Local JSON credential files
    for p in [
        Path.home() / ".railcall" / "station" / "credentials.local.json",
        Path.home() / ".railcall" / "station" / ".railcall_workspace" / "keys.local.json"
    ]:
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                zd = d.get("zendesk", {}) if isinstance(d.get("zendesk"), dict) else d
                s = zd.get("ZENDESK_SUBDOMAIN")
                e = zd.get("ZENDESK_EMAIL")
                t = zd.get("ZENDESK_API_TOKEN")
                if s and e and t:
                    return str(s).strip(), str(e).strip(), str(t).strip()
            except Exception:
                pass

    raise RuntimeError("Airlock Refusal: Missing ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, or ZENDESK_API_TOKEN in Station Vault.")

def _get_base_url(subdomain):
    sub = subdomain.strip()
    if sub.startswith("https://"):
        sub = sub[len("https://"):]
    sub = sub.rstrip("/")
    if "." not in sub:
        return f"https://{sub}.zendesk.com/api/v2"
    return f"https://{sub}/api/v2"

def _make_api_request(url, email, token, method="GET", payload=None):
    auth_str = f"{email}/token:{token}".encode("utf-8")
    b64_auth = base64.b64encode(auth_str).decode("ascii")

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}, resp.status
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise RuntimeError(f"Zendesk API Error ({e.code}): {err_body}")
    except Exception as e:
        raise RuntimeError(f"Zendesk Transport Error: {str(e)}")

def _compute_ticket_fingerprint(ticket):
    sig = f"{ticket.get('id')}_{ticket.get('status')}_{ticket.get('priority')}_{ticket.get('updated_at')}"
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16]

# -------------------------------------------------------------------------
# COMMAND HANDLERS (RESULT, RECEIPT TUPLES)
# -------------------------------------------------------------------------

def zendesk_verify_zendesk_connection(inputs=None, stamp=None):
    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    res, _ = _make_api_request(f"{base_url}/users/me.json", email, token)
    user = res.get("user", {})

    result = {
        "status": "connected",
        "verified": True,
        "user_id": user.get("id"),
        "name": user.get("name"),
        "role": user.get("role"),
        "subdomain": subdomain
    }
    receipt = {"kind": "zendesk.verify_connection", "user_id": user.get("id"), "role": user.get("role")}
    return result, receipt

def zendesk_get_ticket(inputs=None, stamp=None):
    inputs = inputs or {}
    ticket_id = str(inputs.get("ticket_id") or "").strip()
    if not ticket_id:
        raise RuntimeError("Airlock Refusal: ticket_id is required.")

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token)
    ticket = res.get("ticket", {})
    fp = _compute_ticket_fingerprint(ticket)

    result = {
        "ticket_id": ticket.get("id"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "subject": ticket.get("subject"),
        "tags": ticket.get("tags", []),
        "state_fingerprint": fp
    }
    receipt = {"kind": "zendesk.get_ticket", "ticket_id": ticket_id, "state_fingerprint": fp}
    return result, receipt

def zendesk_list_open_tickets(inputs=None, stamp=None):
    inputs = inputs or {}
    limit = int(inputs.get("limit") or 10)

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    query = "type:ticket status<solved"
    url = f"{base_url}/search.json?query={urllib.parse.quote(query)}&per_page={min(limit, 100)}"
    res, _ = _make_api_request(url, email, token)

    tickets = res.get("results", [])
    result = {
        "count": len(tickets),
        "tickets": [
            {
                "id": t.get("id"),
                "status": t.get("status"),
                "priority": t.get("priority"),
                "subject": t.get("subject"),
                "fingerprint": _compute_ticket_fingerprint(t)
            }
            for t in tickets
        ]
    }
    receipt = {"kind": "zendesk.list_open_tickets", "count": len(tickets)}
    return result, receipt

def zendesk_update_ticket_status(inputs=None, stamp=None):
    inputs = inputs or {}
    ticket_id = str(inputs.get("ticket_id") or "").strip()
    new_status = str(inputs.get("status") or "").strip().lower()
    expected_fingerprint = str(inputs.get("expected_fingerprint") or "").strip()

    if not ticket_id or not new_status:
        raise RuntimeError("Airlock Refusal: ticket_id and status are required.")

    valid_statuses = ("new", "open", "pending", "hold", "solved", "closed")
    if new_status not in valid_statuses:
        raise RuntimeError(f"Airlock Refusal: Invalid status '{new_status}'. Allowed: {valid_statuses}")

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    # Anti-drift guard
    res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token)
    current_ticket = res.get("ticket", {})
    cur_fp = _compute_ticket_fingerprint(current_ticket)

    if expected_fingerprint and expected_fingerprint != cur_fp:
        raise RuntimeError(f"Airlock Refusal: Anti-Drift Lock Triggered — Ticket state changed. Expected {expected_fingerprint}, got {cur_fp}.")

    payload = {"ticket": {"status": new_status}}
    up_res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token, method="PUT", payload=payload)
    updated = up_res.get("ticket", {})

    result = {
        "ticket_id": updated.get("id"),
        "status": updated.get("status"),
        "previous_fingerprint": cur_fp,
        "new_fingerprint": _compute_ticket_fingerprint(updated)
    }
    receipt = {"kind": "zendesk.update_ticket_status", "ticket_id": ticket_id, "new_status": new_status}
    return result, receipt

def zendesk_escalate_ticket_priority(inputs=None, stamp=None):
    inputs = inputs or {}
    ticket_id = str(inputs.get("ticket_id") or "").strip()
    priority = str(inputs.get("priority") or "urgent").strip().lower()
    expected_fingerprint = str(inputs.get("expected_fingerprint") or "").strip()

    if not ticket_id:
        raise RuntimeError("Airlock Refusal: ticket_id is required.")

    valid_priorities = ("low", "normal", "high", "urgent")
    if priority not in valid_priorities:
        raise RuntimeError(f"Airlock Refusal: Invalid priority '{priority}'. Allowed: {valid_priorities}")

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token)
    current_ticket = res.get("ticket", {})
    cur_fp = _compute_ticket_fingerprint(current_ticket)

    if expected_fingerprint and expected_fingerprint != cur_fp:
        raise RuntimeError(f"Airlock Refusal: Anti-Drift Lock Triggered — Ticket state changed. Expected {expected_fingerprint}, got {cur_fp}.")

    payload = {"ticket": {"priority": priority}}
    up_res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token, method="PUT", payload=payload)
    updated = up_res.get("ticket", {})

    result = {
        "ticket_id": updated.get("id"),
        "priority": updated.get("priority"),
        "previous_fingerprint": cur_fp,
        "new_fingerprint": _compute_ticket_fingerprint(updated)
    }
    receipt = {"kind": "zendesk.escalate_ticket_priority", "ticket_id": ticket_id, "priority": priority}
    return result, receipt

def zendesk_post_ticket_reply(inputs=None, stamp=None):
    inputs = inputs or {}
    ticket_id = str(inputs.get("ticket_id") or "").strip()
    body = str(inputs.get("body") or "").strip()
    public = bool(inputs.get("public", False))

    if not ticket_id or not body:
        raise RuntimeError("Airlock Refusal: ticket_id and body are required.")

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    payload = {"ticket": {"comment": {"body": body, "public": public}}}
    res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}.json", email, token, method="PUT", payload=payload)

    result = {
        "ticket_id": ticket_id,
        "action": "reply_posted",
        "public": public
    }
    receipt = {"kind": "zendesk.post_ticket_reply", "ticket_id": ticket_id, "public": public}
    return result, receipt

def zendesk_add_ticket_tags(inputs=None, stamp=None):
    inputs = inputs or {}
    ticket_id = str(inputs.get("ticket_id") or "").strip()
    raw_tags = inputs.get("tags") or ""

    if not ticket_id or not raw_tags:
        raise RuntimeError("Airlock Refusal: ticket_id and tags are required.")

    if isinstance(raw_tags, list):
        tag_list = [str(t).strip() for t in raw_tags if str(t).strip()]
    else:
        tag_list = [t.strip() for t in str(raw_tags).split(",") if t.strip()]

    subdomain, email, token = _creds()
    base_url = _get_base_url(subdomain)

    # Nondestructive tag append: POST to /tickets/{id}/tags.json
    payload = {"tags": tag_list}
    res, _ = _make_api_request(f"{base_url}/tickets/{ticket_id}/tags.json", email, token, method="POST", payload=payload)

    result = {
        "ticket_id": ticket_id,
        "tags_added": tag_list,
        "all_tags": res.get("tags", [])
    }
    receipt = {"kind": "zendesk.add_ticket_tags", "ticket_id": ticket_id, "tags_added": tag_list}
    return result, receipt
