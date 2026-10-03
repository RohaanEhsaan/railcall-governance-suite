# RailCall Enterprise Governance Suite

A 5-module zero-trust autonomous governance airlock suite built for the RailCall platform, signed using Spec v2 tree manifests and Ed25519 cryptographic receipts.

## Included Modules

| Module | Marketplace Slug | Version | Core Guardrail |
| :--- | :--- | :--- | :--- |
| **Cloud Infra Airlock** | `rohan/cloud-infra-airlock` | `1.5.10` | 3-stage airlock (Preview/Approve/Execute), GPU quarantine, $0.50/hr spend ceiling & RDS protection |
| **Shopify Admin** | `rohan/shopify-admin` | `1.2.22` | Stock floor protection & fulfillment-guarded cancellations |
| **Linear Governance** | `rohan/linear-governance-hub` | `1.3.2` | Anti-drift state locks & deterministic payload hashing |
| **Stripe Governance** | `rohan/stripe-governance` | `1.2.19` | $100 financial ceiling enforcement & airlock refusals |
| **Zendesk Governance** | `rohan/zendesk-governance` | `1.2.2` | Zero-trust sandbox (no subprocesses, no filesystem writes) |

## Verification

To verify module manifests and tree signatures locally:

```bash
railcall market module verify ./cloud-infra-airlock
railcall market module verify ./shopify-admin
railcall market module verify ./linear-governance-hub
railcall market module verify ./stripe-governance
railcall market module verify ./zendesk-governance
```
