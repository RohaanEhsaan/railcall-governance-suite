import os
import boto3
from botocore.exceptions import ClientError

HOURLY_RATES_CENTS = {
    "t3.nano": 1,
    "t3.micro": 2,
    "t3.small": 3,
    "t3.medium": 5,
    "t3.large": 10,
    "c5.large": 12,
    "m5.large": 15,
    "g4dn.xlarge": 75,
    "p3.2xlarge": 306,
    "p4d.24xlarge": 3277
}

PROHIBITED_PREFIXES = ("p2", "p3", "p4", "p5", "g3", "g4", "g5", "trn1")

def _get_client(service_name):
    vault_get = globals().get("__rc_helpers__", {}).get("vault_get")
    creds = vault_get("aws") if vault_get else None
    
    # Matches uppercase manifest secrets, with case-insensitive fallback
    if isinstance(creds, dict):
        access_key = creds.get("AWS_ACCESS_KEY_ID") or creds.get("aws_access_key_id") or "test"
        secret_key = creds.get("AWS_SECRET_ACCESS_KEY") or creds.get("aws_secret_access_key") or "test"
        region = creds.get("AWS_REGION") or creds.get("region") or "us-east-1"
        endpoint = creds.get("AWS_ENDPOINT_URL") or creds.get("endpoint_url")
    elif isinstance(creds, str):
        access_key = creds
        secret_key = creds
        region = "us-east-1"
        endpoint = None
    else:
        access_key = "test"
        secret_key = "test"
        region = "us-east-1"
        endpoint = "http://127.0.0.1:4566"

    kwargs = {
        "region_name": region,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint

    return boto3.client(service_name, **kwargs)

def aws_inspect_running_spend(inputs, stamp=None):
    try:
        ec2 = _get_client("ec2")
        response = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
        
        running_instances = []
        total_cents = 0
        for reservation in response.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                itype = inst.get("InstanceType", "t3.micro")
                rate = HOURLY_RATES_CENTS.get(itype, 20)
                total_cents += rate
                running_instances.append({
                    "instance_id": inst.get("InstanceId"),
                    "type": itype,
                    "hourly_rate_cents": rate
                })

        result = {
            "status": "success",
            "active_count": len(running_instances),
            "instances": running_instances,
            "total_burn_cents_hr": total_cents,
            "hourly_burn_usd": f"${total_cents / 100:.2f}/hr"
        }
        receipt = {"action": "aws.inspect_running_spend", "executed": True, "count": len(running_instances)}
        return (result, receipt)
    except Exception as e:
        return ({"error": str(e)}, {"action": "aws.inspect_running_spend", "executed": False, "error": str(e)})

def aws_preview_instance_launch(inputs, stamp=None):
    itype = inputs.get("instance_type", "t3.micro")
    rate = HOURLY_RATES_CENTS.get(itype, 150)
    is_gpu = any(itype.startswith(p) for p in PROHIBITED_PREFIXES)
    exceeded = rate > 50 or is_gpu

    result = {
        "instance_type": itype,
        "hourly_cost_cents": rate,
        "hourly_cost_usd": f"${rate / 100:.2f}/hr",
        "is_gpu_accelerated": is_gpu,
        "burn_ceiling_exceeded": exceeded,
        "will_be_blocked_at_airlock": exceeded
    }
    receipt = {"action": "aws.preview_instance_launch", "executed": True, "type": itype, "blocked": exceeded}
    return (result, receipt)

def aws_provision_instance(inputs, stamp=None):
    instance_type = inputs.get("instance_type", "t3.micro")
    image_id = inputs.get("image_id", "ami-12345678")
    override = str(inputs.get("override_ceiling", "false")).lower() == "true"
    
    rate = HOURLY_RATES_CENTS.get(instance_type, 150)
    is_gpu = any(instance_type.startswith(p) for p in PROHIBITED_PREFIXES)

    if (rate > 50 or is_gpu) and not override:
        reason = f"Refused: Instance type '{instance_type}' exceeds $0.50/hr ceiling or contains GPU hardware."
        receipt = {
            "airlock_status": "REFUSED_BY_POLICY",
            "policy_rule": "infra_spend_ceiling_exceeded",
            "blocked_at": "127.0.0.1",
            "attempted_type": instance_type,
            "rate_cents": rate
        }
        return ({"airlock_status": "REFUSED_BY_POLICY", "refusal_reason": reason}, receipt)

    try:
        ec2 = _get_client("ec2")
        resp = ec2.run_instances(
            ImageId=image_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1
        )
        instance_id = resp["Instances"][0]["InstanceId"]
        result = {
            "airlock_status": "APPROVED_AND_EXECUTED",
            "instance_id": instance_id,
            "instance_type": instance_type,
            "state": "running",
            "hourly_cost_usd": f"${rate / 100:.2f}/hr"
        }
        receipt = {"action": "aws.provision_instance", "executed": True, "instance_id": instance_id}
        return (result, receipt)
    except Exception as e:
        return ({"error": str(e)}, {"action": "aws.provision_instance", "executed": False, "error": str(e)})

def aws_quarantine_orphan_disks(inputs, stamp=None):
    tag_quarantine = str(inputs.get("tag_quarantine", "true")).lower() == "true"
    try:
        ec2 = _get_client("ec2")
        resp = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
        volumes = resp.get("Volumes", [])
        
        quarantined = []
        for vol in volumes:
            vid = vol["VolumeId"]
            size = vol.get("Size", 0)
            if tag_quarantine:
                ec2.create_tags(
                    Resources=[vid],
                    Tags=[{"Key": "AirlockStatus", "Value": "QuarantinedOrphan"}]
                )
            quarantined.append({"volume_id": vid, "size_gb": size})

        result = {
            "status": "success",
            "orphan_volumes_found": len(quarantined),
            "volumes": quarantined
        }
        receipt = {"action": "aws.quarantine_orphan_disks", "executed": True, "count": len(quarantined)}
        return (result, receipt)
    except Exception as e:
        return ({"error": str(e)}, {"action": "aws.quarantine_orphan_disks", "executed": False, "error": str(e)})

def aws_emergency_killswitch(inputs, stamp=None):
    instance_id = inputs.get("instance_id")
    if not instance_id:
        return ({"error": "Missing instance_id"}, {"executed": False})

    try:
        ec2 = _get_client("ec2")
        resp = ec2.terminate_instances(InstanceIds=[instance_id])
        current_state = resp["TerminatingInstances"][0]["CurrentState"]["Name"]

        result = {
            "airlock_status": "KILLSWITCH_EXECUTED",
            "instance_id": instance_id,
            "state": current_state,
            "reason": inputs.get("reason", "Autonomous agent deviation")
        }
        receipt = {"action": "cloud.emergency_killswitch", "executed": True, "instance_id": instance_id, "state": current_state}
        return (result, receipt)
    except Exception as e:
        return ({"error": str(e)}, {"action": "aws.emergency_killswitch", "executed": False, "error": str(e)})

def aws_verify_immutable_db_lock(inputs, stamp=None):
    db_id = inputs.get("db_identifier", "prod-db")
    try:
        rds = _get_client("rds")
        resp = rds.describe_db_instances(DBInstanceIdentifier=db_id)
        db = resp["DBInstances"][0]
        deletion_protected = db.get("DeletionProtection", False)

        result = {
            "db_identifier": db_id,
            "deletion_protection": deletion_protected,
            "safe_for_agent_ops": deletion_protected
        }
        receipt = {"action": "aws.verify_immutable_db_lock", "executed": True, "protected": deletion_protected}
        return (result, receipt)
    except Exception as e:
        return ({"error": str(e)}, {"action": "aws.verify_immutable_db_lock", "executed": False, "error": str(e)})