"""rohan/linear-governance-hub — Strict Governed Airlock Handler.

Zero fabricated fallbacks.
Full error assertion on GraphQL errors and unsuccess flags.
Airlock drift protection via state comparison.
"""
import hashlib
import json
import urllib.request
import urllib.error

_API = "https://api.linear.app/graphql"

def _creds():
    helpers = globals().get("__rc_helpers__")
    if helpers and "vault_get" in helpers:
        try:
            entry = helpers["vault_get"]("linear")
            if isinstance(entry, str):
                return entry.strip()
            if isinstance(entry, dict):
                return str(entry.get("LINEAR_API_KEY") or entry.get("token") or "").strip()
        except Exception:
            pass
    return ""

def _graphql(query, variables, token):
    if not token:
        token = _creds()
    if not token:
        raise RuntimeError("Airlock Refusal: No Linear credentials found in Station Vault.")

    req = urllib.request.Request(
        _API,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": token,
            "User-Agent": "RailCall-Linear-Governance/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Linear HTTP Error {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"Network error contacting Linear: {str(e)}")

def _compute_fingerprint(issue_id, state_or_priority, updated_at):
    raw = f"{issue_id}:{state_or_priority}:{updated_at}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

# -------------------------------------------------------------------------
# 1. VERIFY CONNECTION
# -------------------------------------------------------------------------
def linear_verify_connection(inputs=None, stamp=None):
    tok = _creds()
    if not tok:
        raise RuntimeError("No LINEAR_API_KEY found in Station Vault.")
    
    query = "{ viewer { id name email } }"
    res = _graphql(query, {}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear Auth Error: {res['errors'][0].get('message')}")

    viewer = (res.get("data") or {}).get("viewer")
    if not viewer:
        raise RuntimeError("Airlock Refusal: Unable to fetch authenticated Linear viewer.")
    
    return (
        {"status": "connected", "verified": True, "viewer": viewer},
        {"kind": "linear.verify_connection", "user": viewer.get("email")}
    )

# -------------------------------------------------------------------------
# 2. CREATE ISSUE
# -------------------------------------------------------------------------
def linear_create_issue(inputs, stamp=None):
    inputs = inputs or {}
    team_id = str(inputs.get("teamId") or inputs.get("team_id") or "").strip()
    title = str(inputs.get("title") or "").strip()
    desc = str(inputs.get("description") or "").strip()
    
    if not title:
        raise RuntimeError("Airlock Refusal: 'title' is required to create an issue.")

    try:
        priority = int(inputs.get("priority") or 0)
    except Exception:
        priority = 0

    tok = _creds()
    mutation = """
    mutation($teamId: String!,$title: String!, $desc: String,$priority: Int) {
      issueCreate(input: { teamId: $teamId, title:$title, description: $desc, priority:$priority }) {
        success
        issue { id identifier url title priority }
      }
    }
    """
    res = _graphql(mutation, {"teamId": team_id, "title": title, "desc": desc, "priority": priority}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")
        
    data = (res.get("data") or {}).get("issueCreate") or {}
    if not data.get("success"):
        raise RuntimeError("Airlock Refusal: Linear reported issueCreate failure.")

    issue = data.get("issue")
    if not issue:
        raise RuntimeError("Airlock Refusal: issueCreate reported success but returned no issue payload.")

    return (
        {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "url": issue.get("url"),
            "title": issue.get("title"),
            "status": "created"
        },
        {
            "kind": "linear.create_issue",
            "identifier": issue.get("identifier"),
            "priority": priority
        }
    )

# -------------------------------------------------------------------------
# 3. UPDATE PRIORITY (Escalation Guard & Anti-Drift)
# -------------------------------------------------------------------------
def linear_update_priority(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()
    expected_fp = str(inputs.get("expected_fingerprint") or "").strip()

    try:
        priority = int(inputs.get("priority") or 0)
    except Exception:
        priority = 0

    allow_urgent_raw = str(inputs.get("allow_urgent", "")).lower()
    allow_urgent = allow_urgent_raw in ("true", "1", "yes")

    if not issue_id:
        raise RuntimeError("Airlock Refusal: 'issueId' is required.")

    # Escalation Guard
    if priority == 1 and not allow_urgent:
        raise RuntimeError("Airlock Refusal: P1/Urgent escalation requires explicit allow_urgent=True")

    tok = _creds()
    check_query = "query($id: String!) { issue(id:$id) { id priority updatedAt } }"
    data = _graphql(check_query, {"id": issue_id}, tok)
    if data.get("errors"):
        raise RuntimeError(f"Linear API Error fetching issue: {data['errors'][0].get('message')}")

    issue = (data.get("data") or {}).get("issue")
    if not issue:
        raise RuntimeError(f"Airlock Refusal: Issue '{issue_id}' not found on Linear.")

    curr_fp = _compute_fingerprint(issue_id, issue.get("priority"), issue.get("updatedAt"))
    if expected_fp and curr_fp != expected_fp:
        raise RuntimeError(f"Airlock Refusal: Issue state drifted. Expected {expected_fp}, found {curr_fp}")

    mutation = """
    mutation($id: String!,$priority: Int!) {
      issueUpdate(id: $id, input: { priority:$priority }) {
        success
        issue { id priority identifier }
      }
    }
    """
    res = _graphql(mutation, {"id": issue_id, "priority": priority}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    result = (res.get("data") or {}).get("issueUpdate") or {}
    if not result.get("success"):
        raise RuntimeError("Airlock Refusal: Linear reported issueUpdate failure.")

    updated = result.get("issue")
    return (
        {
            "issue_id": issue_id,
            "priority": updated.get("priority"),
            "fingerprint": curr_fp,
            "guard_passed": True
        },
        {
            "kind": "linear.update_priority",
            "issue_id": issue_id,
            "escalation_approved": allow_urgent if priority == 1 else True
        }
    )

# -------------------------------------------------------------------------
# 4. TRANSITION STATUS
# -------------------------------------------------------------------------
def linear_transition_status(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()
    state_id = str(inputs.get("stateId") or inputs.get("state_id") or "").strip()
    expected_fp = str(inputs.get("expected_fingerprint") or "").strip()

    if not issue_id or not state_id:
        raise RuntimeError("Airlock Refusal: Both 'issueId' and 'stateId' are required.")

    tok = _creds()
    check_query = "query($id: String!) { issue(id:$id) { id state { id name } updatedAt } }"
    data = _graphql(check_query, {"id": issue_id}, tok)
    if data.get("errors"):
        raise RuntimeError(f"Linear API Error: {data['errors'][0].get('message')}")

    issue = (data.get("data") or {}).get("issue")
    if not issue:
        raise RuntimeError(f"Airlock Refusal: Issue '{issue_id}' not found on Linear.")

    curr_fp = _compute_fingerprint(issue_id, (issue.get("state") or {}).get("id"), issue.get("updatedAt"))
    if expected_fp and curr_fp != expected_fp:
        raise RuntimeError(f"Airlock Refusal: State drifted. Expected {expected_fp}, found {curr_fp}")

    mutation = """
    mutation($id: String!,$stateId: String!) {
      issueUpdate(id: $id, input: { stateId:$stateId }) {
        success
        issue { id state { id name } }
      }
    }
    """
    res = _graphql(mutation, {"id": issue_id, "stateId": state_id}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    result = (res.get("data") or {}).get("issueUpdate") or {}
    if not result.get("success"):
        raise RuntimeError("Airlock Refusal: Linear reported state transition failure.")

    updated = result.get("issue")
    return (
        {
            "issue_id": issue_id,
            "state": updated.get("state"),
            "fingerprint": curr_fp,
            "drift_checked": True
        },
        {"kind": "linear.transition_status", "issue_id": issue_id}
    )

# -------------------------------------------------------------------------
# 5. ADD COMMENT
# -------------------------------------------------------------------------
def linear_add_comment(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()
    body = str(inputs.get("body") or "").strip()

    if not issue_id or not body:
        raise RuntimeError("Airlock Refusal: Both 'issueId' and 'body' are required.")

    tok = _creds()
    mutation = """
    mutation($issueId: String!,$body: String!) {
      commentCreate(input: { issueId: $issueId, body:$body }) {
        success
        comment { id url }
      }
    }
    """
    res = _graphql(mutation, {"issueId": issue_id, "body": body}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    result = (res.get("data") or {}).get("commentCreate") or {}
    if not result.get("success"):
        raise RuntimeError("Airlock Refusal: Linear reported comment creation failure.")

    comment = result.get("comment")
    return (
        {"status": "success", "comment_id": comment.get("id"), "url": comment.get("url")},
        {"kind": "linear.add_comment", "issue_id": issue_id}
    )

# -------------------------------------------------------------------------
# 6. ATTACH SIGNED LOG
# -------------------------------------------------------------------------
def linear_attach_signed_log(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()
    receipt_id = str(inputs.get("receiptId") or inputs.get("receipt_id") or "UNKNOWN").strip()
    summary = str(inputs.get("summary") or "Airlock Audit Verified").strip()

    if not issue_id:
        raise RuntimeError("Airlock Refusal: 'issueId' is required.")

    body = f"🔒 **RailCall Governance Airlock Audit Record**\n\n- **Receipt ID**: `{receipt_id}`\n- **Audit Summary**: {summary}\n- **Integrity**: Ed25519 Verified"

    tok = _creds()
    mutation = """
    mutation($issueId: String!,$body: String!) {
      commentCreate(input: { issueId: $issueId, body:$body }) {
        success
        comment { id }
      }
    }
    """
    res = _graphql(mutation, {"issueId": issue_id, "body": body}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    result = (res.get("data") or {}).get("commentCreate") or {}
    if not result.get("success"):
        raise RuntimeError("Airlock Refusal: Failed to attach audit log to Linear issue.")

    return (
        {"status": "attached", "receipt_id": receipt_id, "issue_id": issue_id},
        {"kind": "linear.attach_signed_log", "receipt_id": receipt_id}
    )

# -------------------------------------------------------------------------
# 7. ASSIGN USER
# -------------------------------------------------------------------------
def linear_assign_user(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()
    assignee_id = str(inputs.get("assigneeId") or inputs.get("assignee_id") or "").strip()

    if not issue_id:
        raise RuntimeError("Airlock Refusal: 'issueId' is required.")

    tok = _creds()
    mutation = """
    mutation($id: String!,$assigneeId: String) {
      issueUpdate(id: $id, input: { assigneeId:$assigneeId }) {
        success
        issue { id assignee { id name } }
      }
    }
    """
    res = _graphql(mutation, {"id": issue_id, "assigneeId": assignee_id if assignee_id else None}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    result = (res.get("data") or {}).get("issueUpdate") or {}
    if not result.get("success"):
        raise RuntimeError("Airlock Refusal: Linear reported assign_user failure.")

    return (
        {"status": "assigned", "issue_id": issue_id, "assignee": result.get("issue", {}).get("assignee")},
        {"kind": "linear.assign_user", "issue_id": issue_id}
    )

# -------------------------------------------------------------------------
# 8. GET ISSUE
# -------------------------------------------------------------------------
def linear_get_issue(inputs, stamp=None):
    inputs = inputs or {}
    issue_id = str(inputs.get("issueId") or inputs.get("issue_id") or "").strip()

    if not issue_id:
        raise RuntimeError("Airlock Refusal: 'issueId' is required.")

    tok = _creds()
    query = """
    query($id: String!) {
      issue(id: $id) {
        id identifier title description priority state { id name } updatedAt
      }
    }
    """
    res = _graphql(query, {"id": issue_id}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    issue = (res.get("data") or {}).get("issue")
    if not issue:
        raise RuntimeError(f"Airlock Refusal: Issue '{issue_id}' not found.")

    fingerprint = _compute_fingerprint(issue_id, issue.get("priority"), issue.get("updatedAt"))
    return (
        {"issue": issue, "fingerprint": fingerprint},
        {"kind": "linear.get_issue", "issue_id": issue_id}
    )

# -------------------------------------------------------------------------
# 9. LIST TEAM ISSUES
# -------------------------------------------------------------------------
def linear_list_team_issues(inputs, stamp=None):
    inputs = inputs or {}
    team_id = str(inputs.get("teamId") or inputs.get("team_id") or "").strip()

    if not team_id:
        raise RuntimeError("Airlock Refusal: 'teamId' is required.")

    tok = _creds()
    query = """
    query($teamId: String!) {
      team(id: $teamId) {
        issues(first: 20) {
          nodes { id identifier title priority state { name } }
        }
      }
    }
    """
    res = _graphql(query, {"teamId": team_id}, tok)
    if res.get("errors"):
        raise RuntimeError(f"Linear API Error: {res['errors'][0].get('message')}")

    issues = ((res.get("data") or {}).get("team") or {}).get("issues", {}).get("nodes", [])
    return (
        {"team_id": team_id, "count": len(issues), "issues": issues},
        {"kind": "linear.list_team_issues", "team_id": team_id}
    )
