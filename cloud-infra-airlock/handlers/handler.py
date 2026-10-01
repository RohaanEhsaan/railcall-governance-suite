import os
import json
import hashlib
import boto3
from botocore.config import Config

# Extended hardware accelerator prefixes (Strict Non-Overridable Block)
STRICT_GPU_PREFIXES = (
    "p2", "p3", "p4", "p5", "p6",
    "g3", "g4", "g5", "g6", "gr6",
    "trn1", "trn2", "inf1", "inf2", "dl1"
)

# Known standard rates (USD cents/hr)
ESTIMATED_RATES_CENTS = {
    "t3.nano": 1,
    "t3.micro": 2,
    "t3.small": 3,
    "t3.medium": 5,
    "t3.large": 10,
    "t3.xlarge": 20,
    "m5.large": 10,
    "m5.xlarge": 20,
    "c5.large": 9,
    "c5.xlarge": 17,
}
DEFAULT_HOURLY_RATE_CENTS = 60  # Fail-closed fallback — above CEILING_CENTS, so unknown types require explicit override
CEILING_CENTS = 50              # $0.50/hr airlock threshold

MANAGED_TAG_KEY = "ManagedBy"
MANAGED_TAG_VAL = "AgentGovernance"

def _estimate_rate_cents(itype: str) -> int:
    itype = str(itype or "").strip().lower()
    if itype in ESTIMATED_RATES_CENTS:
        return ESTIMATED_RATES_CENTS[itype]
    
    # Check GPU / accelerator families
    if any(itype.startswith(p) for p in STRICT_GPU_PREFIXES):
        return 300  # Conservative estimate for accelerator instances ($3.00+/hr)

    # Size-based heuristic for high compute / bare metal / large memory
    size = itype.rsplit(".", 1)[-1]
    if size == "metal" or (size.endswith("xlarge") and size != "xlarge") or itype.startswith(("mac", "u-")):
        return 120  # 2xlarge+, bare-metal, mac, high-mem instances exceed $0.50 ceiling ($1.20/hr)

    return DEFAULT_HOURLY_RATE_CENTS

def _compute_provenance(action: str, inputs: dict, result: dict, stamp: str = None) -> str:
    canonical = json.dumps({
        "action": action,
        "inputs": inputs,
        "result": result,
        "stamp": stamp or "none"
    }, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _get_client(service_name: str, region: str = None):
    # 1. Check Station Vault (supporting helper global or station package)
    vault_creds = {}
    try:
        if "__rc_helpers__" in globals() and "vault_get" in globals()["__rc_helpers__"]:
            vault_creds = globals()["__rc_helpers__"]["vault_get"]("aws") or {}
        else:
            from station import vault_get
            vault_creds = vault_get("aws") or {}
    except Exception:
        vault_creds = {}

    access_key = None
    secret_key = None
    vault_region = None
    vault_endpoint = None

    if isinstance(vault_creds, dict):
        access_key = vault_creds.get("AWS_ACCESS_KEY_ID") or vault_creds.get("aws_access_key_id") or vault_creds.get("access_key")
        secret_key = vault_creds.get("AWS_SECRET_ACCESS_KEY") or vault_creds.get("aws_secret_access_key") or vault_creds.get("secret_key")
        vault_region = vault_creds.get("AWS_REGION") or vault_creds.get("aws_region") or vault_creds.get("region")
        vault_endpoint = vault_creds.get("AWS_ENDPOINT_URL") or vault_creds.get("aws_endpoint_url") or vault_creds.get("endpoint_url")

    # 2. Environment variable fallbacks
    access_key = access_key or os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
    
    target_region = region or vault_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    endpoint_url = vault_endpoint or os.environ.get("AWS_ENDPOINT_URL")

    # 3. Default to LocalStack if no credentials exist
    if not access_key or not secret_key:
        access_key = "test"
        secret_key = "test"
        if not endpoint_url:
            endpoint_url = "http://127.0.0.1:4566"

    client_config = Config(
        connect_timeout=2,
        read_timeout=3,
        retries={"max_attempts": 1}
    )

    kwargs = {
        "region_name": target_region,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "config": client_config
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    return boto3.client(service_name, **kwargs)

def aws_inspect_running_spend(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.inspect_running_spend"
    region = inputs.get("region")
    try:
        ec2 = _get_client("ec2", region=region)
        paginator = ec2.get_paginator("describe_instances")
        page_iterator = paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
        
        running_instances = []
        total_hourly_burn = 0
        for page in page_iterator:
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    itype = inst.get("InstanceType", "unknown")
                    rate = _estimate_rate_cents(itype)
                    total_hourly_burn += rate
                    running_instances.append({
                        "instance_id": inst.get("InstanceId"),
                        "instance_type": itype,
                        "rate_cents_hr": rate
                    })

        result = {
            "status": "success",
            "region": region or ec2.meta.region_name,
            "active_count": len(running_instances),
            "estimated_hourly_burn_cents": total_hourly_burn,
            "instances": running_instances
        }
        receipt = {
            "action": action,
            "executed": True,
            "provenance_hash": _compute_provenance(action, inputs, result, stamp),
            "count": len(running_instances)
        }
        return result, receipt
    except Exception as e:
        result = {"error": str(e), "region": region}
        receipt = {
            "action": action,
            "executed": False,
            "provenance_hash": _compute_provenance(action, inputs, result, stamp),
            "error": str(e)
        }
        return result, receipt

def aws_preview_instance_launch(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.preview_instance_launch"
    raw_itype = inputs.get("instance_type", "t3.micro")
    itype = str(raw_itype).strip().lower()
    is_gpu = any(itype.startswith(p) for p in STRICT_GPU_PREFIXES)
    rate = _estimate_rate_cents(itype)
    exceeds_ceiling = rate > CEILING_CENTS or is_gpu

    result = {
        "instance_type": raw_itype,
        "is_gpu_accelerated": is_gpu,
        "hourly_cost_cents": rate,
        "burn_ceiling_exceeded": exceeds_ceiling,
        "will_be_blocked_at_airlock": exceeds_ceiling
    }
    receipt = {
        "action": action,
        "executed": True,
        "blocked": exceeds_ceiling,
        "provenance_hash": _compute_provenance(action, inputs, result, stamp)
    }
    return result, receipt

def aws_provision_instance(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.provision_instance"
    raw_itype = inputs.get("instance_type", "t3.micro")
    itype = str(raw_itype).strip().lower()
    image_id = inputs.get("image_id")
    override = str(inputs.get("override_ceiling", "false")).lower() == "true"
    region = inputs.get("region")

    if not image_id:
        result = {"error": "Missing required image_id parameter"}
        receipt = {
            "action": action,
            "executed": False,
            "error": "Missing required image_id parameter",
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

    is_gpu = any(itype.startswith(p) for p in STRICT_GPU_PREFIXES)

    # 1. Non-overridable hardware accelerator block
    if is_gpu:
        result = {
            "airlock_status": "REFUSED_BY_POLICY",
            "refusal_reason": f"Refused: Instance type '{raw_itype}' contains prohibited GPU/accelerator hardware. Hardware accelerator blocks cannot be overridden."
        }
        receipt = {
            "action": action,
            "executed": False,
            "airlock_status": "REFUSED_BY_POLICY",
            "policy_rule": "gpu_hardware_quarantine",
            "blocked_at": "127.0.0.1",
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

    # 2. Spend ceiling block (overridable with human approval)
    rate = _estimate_rate_cents(itype)
    if rate > CEILING_CENTS and not override:
        result = {
            "airlock_status": "REFUSED_BY_POLICY",
            "refusal_reason": f"Refused: Projected cost ({rate}c/hr) exceeds {CEILING_CENTS}c/hr ceiling. Set override_ceiling=true to request human gate approval."
        }
        receipt = {
            "action": action,
            "executed": False,
            "airlock_status": "REFUSED_BY_POLICY",
            "policy_rule": "infra_spend_ceiling_exceeded",
            "blocked_at": "127.0.0.1",
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

    # 3. Governed AWS Dispatch with governance tags
    try:
        ec2 = _get_client("ec2", region=region)
        resp = ec2.run_instances(
            ImageId=image_id,
            InstanceType=raw_itype,
            MinCount=1,
            MaxCount=1,
            TagSpecifications=[{
                "ResourceType": "instance",
                "Tags": [
                    {"Key": MANAGED_TAG_KEY, "Value": MANAGED_TAG_VAL},
                    {"Key": "AirlockApproved", "Value": "true"}
                ]
            }]
        )
        inst = resp["Instances"][0]
        actual_state = inst.get("State", {}).get("Name", "pending")

        result = {
            "status": "success",
            "instance_id": inst["InstanceId"],
            "state": actual_state,
            "instance_type": raw_itype,
            "managed_tag_applied": True
        }
        receipt = {
            "action": action,
            "executed": True,
            "instance_id": inst["InstanceId"],
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt
    except Exception as e:
        result = {"error": str(e)}
        receipt = {
            "action": action,
            "executed": False,
            "error": str(e),
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

def aws_quarantine_orphan_disks(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.quarantine_orphan_disks"
    tag_quarantine = str(inputs.get("tag_quarantine", "true")).lower() == "true"
    region = inputs.get("region")

    try:
        ec2 = _get_client("ec2", region=region)
        paginator = ec2.get_paginator("describe_volumes")
        page_iterator = paginator.paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )

        orphans = []
        for page in page_iterator:
            for vol in page.get("Volumes", []):
                orphans.append(vol.get("VolumeId"))

        tagged = False
        if orphans and tag_quarantine:
            # Chunk into batches of 1000 per AWS create_tags limit
            for i in range(0, len(orphans), 1000):
                chunk = orphans[i:i + 1000]
                ec2.create_tags(
                    Resources=chunk,
                    Tags=[{"Key": "GovernanceQuarantine", "Value": "IsolatedUnattachedStorage"}]
                )
            tagged = True

        result = {
            "status": "success",
            "orphan_volumes_found": len(orphans),
            "volume_ids": orphans,
            "tagged_for_quarantine": tagged,
            "dry_run": not tag_quarantine
        }
        receipt = {
            "action": action,
            "executed": True,
            "count": len(orphans),
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt
    except Exception as e:
        result = {"error": str(e)}
        receipt = {
            "action": action,
            "executed": False,
            "error": str(e),
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

def aws_emergency_killswitch(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.emergency_killswitch"
    instance_id = inputs.get("instance_id")
    force = str(inputs.get("force", "false")).lower() == "true"
    region = inputs.get("region")

    if not instance_id:
        result = {"error": "Missing required instance_id parameter"}
        receipt = {
            "action": action,
            "executed": False,
            "error": "Missing required instance_id parameter",
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

    try:
        ec2 = _get_client("ec2", region=region)
        
        # Guard: Check tags before termination
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        tags = {t["Key"]: t["Value"] for t in desc["Reservations"][0]["Instances"][0].get("Tags", [])}
        
        if tags.get(MANAGED_TAG_KEY) != MANAGED_TAG_VAL and not force:
            result = {
                "airlock_status": "REFUSED_BY_POLICY",
                "refusal_reason": f"Instance '{instance_id}' lacks '{MANAGED_TAG_KEY}: {MANAGED_TAG_VAL}' tag. Aborting to protect unmanaged/production boxes. Set force=true to override."
            }
            receipt = {
                "action": action,
                "executed": False,
                "airlock_status": "REFUSED_BY_POLICY",
                "policy_rule": "killswitch_unmanaged_instance_protection",
                "provenance_hash": _compute_provenance(action, inputs, result, stamp)
            }
            return result, receipt

        resp = ec2.terminate_instances(InstanceIds=[instance_id])
        current_state = resp["TerminatingInstances"][0]["CurrentState"]["Name"]

        result = {
            "status": "success",
            "terminated_instance_id": instance_id,
            "current_state": current_state
        }
        receipt = {
            "action": action,
            "executed": True,
            "terminated_instance_id": instance_id,
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt
    except Exception as e:
        result = {"error": str(e)}
        receipt = {
            "action": action,
            "executed": False,
            "error": str(e),
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

def aws_verify_immutable_db_lock(inputs=None, context=None, stamp=None, **kwargs):
    action = "aws.verify_immutable_db_lock"
    db_id = inputs.get("db_identifier")
    region = inputs.get("region")

    if not db_id:
        result = {"error": "Missing required db_identifier parameter"}
        receipt = {
            "action": action,
            "executed": False,
            "error": "Missing required db_identifier parameter",
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt

    try:
        rds = _get_client("rds", region=region)
        resp = rds.describe_db_instances(DBInstanceIdentifier=db_id)
        db = resp["DBInstances"][0]
        deletion_protected = db.get("DeletionProtection", False)

        result = {
            "status": "success",
            "db_identifier": db_id,
            "deletion_protection": deletion_protected,
            "safe_for_agent_ops": deletion_protected
        }
        receipt = {
            "action": action,
            "executed": True,
            "protected": deletion_protected,
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt
    except Exception as e:
        result = {"error": str(e)}
        receipt = {
            "action": action,
            "executed": False,
            "error": str(e),
            "provenance_hash": _compute_provenance(action, inputs, result, stamp)
        }
        return result, receipt
