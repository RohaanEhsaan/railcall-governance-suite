# Linear Governance Hub (`rohan/linear-governance-hub`)

`contest:round2`

Autonomous enterprise governance airlock for the Linear GraphQL API, featuring cryptographic anti-drift locks, P1 escalation safety floors, and deterministic preflight previews.

---

## 10-Minute Setup Guide

### 1. Installation

Install the cryptographically signed module into your local Station:

```bash
railcall market install rohan/linear-governance-hub
```

### 2. Configure Scoped Linear API Key

Obtain a Personal API Key from [Linear Settings > Account > Security & API](https://linear.app/settings/account/security).

Store your key in the Station Vault or export it in your environment:

```bash
export LINEAR_API_KEY="lin_api_..."
```

> **CREDENTIAL HANDLING**: This module accesses `LINEAR_API_KEY` strictly via Station Vault (`vault_get("linear")`) or controlled environment discovery via `_creds()`. Secrets are never persisted to disk, never logged to stdout, and never included in receipts or return payloads.

### 3. Verify in Studio

Confirm the module displays as **Loaded** with 9 registered commands and trigger modernized v1.5 preflight airlocks safely.

---

## Governed Commands (9 Actions)

| Command ID | Mode | Impact Tier | Guardrail Architecture |
| :--- | :--- | :--- | :--- |
| `linear_verify_connection` | Read | READ_ONLY | Probes viewer identity, organization name, and team scopes. |
| `linear_get_issue` | Read | READ_ONLY | Fetches full issue state, assignee, team key, and timestamp for pre-mutation inspection. |
| `linear_list_team_issues` | Read | READ_ONLY | Queries team issue backlog ordered by updatedAt. |
| `linear_transition_status` | Write | MEDIUM | Accepts optional `expected_fingerprint`; aborts if state changed since prior `linear_get_issue`. |
| `linear_update_priority` | Write | HIGH / MEDIUM | Optional anti-drift lock; P1 escalation requires explicit `allow_urgent=true`. |
| `linear_assign_user` | Write | MEDIUM | Preflight preview for issue reassignment and owner transition. |
| `linear_create_issue` | Write | MEDIUM | Provisions new issues with team scope validation and initial priority assignments. |
| `linear_add_comment` | Write | LOW | Attaches structured audit comment notes to issues. |
| `linear_attach_signed_log` | Write | MEDIUM | Formats and commits machine-verifiable operational log receipts to the issue stream. |

---

## Defensive Engineering Highlights

* **Caller-Supplied Anti-Drift Locks (`linear_transition_status`, `linear_update_priority`)**: Accepts an optional `expected_fingerprint` from a prior `linear_get_issue` call. Aborts write if issue state was modified concurrently; omitting it skips the check.
* **P1 Escalation Safety Floor (`linear_update_priority`)**: Escalations to Urgent (Priority 1) trigger a HIGH blast-radius review and require explicit `allow_urgent=true`.
* **Station v1.5 Airlock Contract**: All mutations return strict `(result, receipt)` tuples with full audit metadata and preflight impact declarations.

---

## Verification & Testing

### 1. Offline Deterministic Test Suite (Zero Network Egress)
Verifies GraphQL payload framing, P1 safety floors, state fingerprint drift aborts, and input validation offline:

```bash
python test_handler.py
```

```text
Ran 7 tests in 0.005s - OK
```

### 2. Live API Round-Trip Harness (No Mocks / No Stubs)
Performs live end-to-end API calls against Linear's Live APIs:

```bash
export LINEAR_API_KEY="lin_api_..."
persist_secret=false python live_test.py
```
