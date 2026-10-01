# Cloud Infrastructure Cost & Kill-Switch Airlock (`rohan/cloud-infra-airlock`)

Autonomous enterprise governance airlock for AWS cloud infrastructure. Intercepts agent actions locally at loopback to enforce hourly spend ceilings ($0.50/hr), quarantine hardware accelerators (p2-p6, g3-g6, gr6, trn1-2, inf1-2, dl1), batch tag unattached EBS storage, and safeguard unmanaged production compute using `ManagedBy: AgentGovernance` tags.

---

## Quick Install

```bash
railcall market install rohan/cloud-infra-airlock
```

Or clone to local station directory:
```bash
git clone [https://github.com/RohaanEhsaan/railcall-governance-suite.git]
cp -r railcall-governance-suite/cloud-infra-airlock ~/.railcall/station/modules/rohan-cloud-infra-airlock/
```

## Configuration

Set AWS credentials via Station Vault (`vault_get("aws")`) or shell environment:
```bash
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"
```
For LocalStack testing:
```bash
export AWS_ENDPOINT_URL="[http://127.0.0.1:4566](http://127.0.0.1:4566)"
```

## Governed Commands

- `aws.inspect_running_spend`: Paginates active instances; calculates burn estimates from built-in rate tables and heuristics.
- `aws.preview_instance_launch`: Zero-credential offline check for costs and GPU presence.
- `aws.provision_instance`: Blocks hardware accelerators; enforces $0.50/hr ceiling (overrideable with human gate approval); attaches `ManagedBy: AgentGovernance` tags.
- `aws.quarantine_orphan_disks`: Batches available EBS volumes in chunks <= 1000 and applies `GovernanceQuarantine` tags.
- `aws.emergency_killswitch`: Protects untagged/production instances; blocks termination unless `ManagedBy: AgentGovernance` tag is present or `force=true` is passed.
- `aws.verify_immutable_db_lock`: Audits RDS instances to confirm `DeletionProtection` is active.

## Key Security Properties

- **Fail-Closed Spend Ceiling**: Unrecognized instance types default to 60c/hr, requiring explicit override.
- **Non-Overridable Accelerator Quarantine**: GPUs are blocked unconditionally at loopback.
- **Deterministic SHA-256 Receipt Digest**: Produces cryptographic digests of canonical request and response payloads.
- **Least Privilege Sandbox**: Zero filesystem writes (`[]`) and subprocess execution disabled (`false`).

## Testing

```bash
python test_handler.py  # 11 offline unit tests with 100% mock coverage
python live_test.py    # Smoke check against local/live endpoints
```
