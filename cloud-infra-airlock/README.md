# Cloud Infrastructure Cost & Kill-Switch Airlock (`rohan/cloud-infra-airlock`)

`contest:round2`

Autonomous enterprise governance airlock for AWS cloud infrastructure, featuring automatic spend ceiling enforcement, local GPU accelerator refusal, orphaned storage isolation, and deterministic preflight previews.

---

## 10-Minute Setup Guide

### 1. Installation

Install the cryptographically signed module into your local Station:

```bash
railcall market install rohan/cloud-infra-airlock
```

Or clone it directly into your local Station modules directory:

```bash
mkdir -p ~/.railcall/station/modules/rohan-cloud-infra-airlock
git clone [https://github.com/RohaanEhsaan/railcall-governance-suite.git](https://github.com/RohaanEhsaan/railcall-governance-suite.git) temp-suite
cp -r temp-suite/cloud-infra-airlock/* ~/.railcall/station/modules/rohan-cloud-infra-airlock/
rm -rf temp-suite
```

### 2. Configure Scoped AWS Credentials

Obtain IAM credentials with least-privilege EC2 and RDS policies, or use LocalStack for local emulation.

Store your credentials in the Station Vault or export them in your environment:

```bash
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"
```

> **CREDENTIAL HANDLING**: This module accesses `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` strictly via Station Vault (`vault_get("aws")`) or controlled environment discovery via `_get_client()`. Secrets are never persisted to disk, never logged to stdout, and never leaked in receipts or return payloads.

### 3. Verify in Studio

Open RailCall Studio (`http://127.0.0.1:8799`). Confirm the module displays under the **`AW aws`** service badge with 6 registered commands, and execute `aws.inspect_running_spend` to verify connectivity.

---

## Governed Commands (6 Actions)

| Command ID | Mode | Impact Tier | Guardrail Architecture |
| :--- | :--- | :--- | :--- |
| `aws.inspect_running_spend` | Read | READ_ONLY | Scans running EC2 instances and computes active aggregate hourly burn rate. |
| `aws.preview_instance_launch` | Read | READ_ONLY | Performs local preflight cost checks before an agent issues a provisioning call. |
| `aws.provision_instance` | Write | HIGH | Intercepts launches exceeding $0.50/hr or containing GPU hardware; requires explicit `override_ceiling=true`. |
| `aws.quarantine_orphan_disks` | Write | MEDIUM | Detects unattached/available EBS volumes and tags them for quarantine snapshotting. |
| `aws.emergency_killswitch` | Write | HIGH | Immediately terminates unapproved or rogue instances running outside signed consent tokens. |
| `aws.verify_immutable_db_lock` | Read | READ_ONLY | Verifies target RDS instances have termination protection enabled prior to agent migrations. |

---

## Defensive Engineering Highlights

- **Preflight Airlock Spend Ceiling (`aws.provision_instance`)**: Intercepts instance launch requests locally. Prevents dispatch if projected cost exceeds $0.50/hr unless callers explicitly pass `override_ceiling=true`.
- **Zero-Egress GPU Quarantine**: Hard-blocks high-cost accelerator instance types (`p2.*`, `p3.*`, `p4.*`, `p5.*`, `g3.*`, `g4.*`, `g5.*`, `trn1.*`) at loopback before network transmission occurs.
- **Orphan Volume Cost Quarantine (`aws.quarantine_orphan_disks`)**: Discovers detached EBS storage wasting budget and isolates volumes with policy quarantine tags.
- **RDS Termination Lock Verification (`aws.verify_immutable_db_lock`)**: Guards database infrastructure by validating `DeletionProtection` state prior to mutation pipelines.
- **Station v1.5 Airlock Contract**: Every command implements `(inputs, stamp=None)` and returns deterministic `(result, receipt)` tuples with SHA-256 cryptographic provenance.

---

## Declared Sandbox Policy

This module enforces a strict, declared sandbox policy in `module.json`:

* **Network Allowlist**: `127.0.0.1:4566`, `localhost:4566`, `ec2.us-east-1.amazonaws.com`, `rds.us-east-1.amazonaws.com`, `*.amazonaws.com`
* **Subprocess Execution**: Strictly prohibited (`subprocess: false`)
* **Filesystem Writes**: Strictly prohibited (`filesystem_writes: false`)

---

## Verification & Testing

### 1. Offline Deterministic Test Suite (Zero Network Egress)
Verifies policy evaluation, cost calculations, and GPU containment logic completely offline:

```bash
python test_handler.py
```

### 2. Live API Round-Trip Harness (No Mocks / No Stubs)
Dispatches native SDK operations through `boto3` against LocalStack or real AWS endpoints:

```bash
python live_test.py
```
