import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "handlers"))
import handler

class TestCloudInfraAirlock(unittest.TestCase):

    def test_preview_instance_launch_standard(self):
        inputs = {"instance_type": "t3.micro"}
        result, receipt = handler.aws_preview_instance_launch(inputs)
        self.assertFalse(result["is_gpu_accelerated"])
        self.assertFalse(result["burn_ceiling_exceeded"])
        self.assertIn("provenance_hash", receipt)
        self.assertEqual(receipt["action"], "aws.preview_instance_launch")

    def test_preview_instance_launch_gpu_refused(self):
        # Checks case insensitivity and prefix coverage
        inputs = {"instance_type": " G6.2xlarge "}
        result, receipt = handler.aws_preview_instance_launch(inputs)
        self.assertTrue(result["is_gpu_accelerated"])
        self.assertTrue(result["burn_ceiling_exceeded"])
        self.assertTrue(receipt["blocked"])

    def test_provision_instance_gpu_cannot_be_overridden(self):
        inputs = {"instance_type": "p4d.24xlarge", "image_id": "ami-12345", "override_ceiling": "true"}
        result, receipt = handler.aws_provision_instance(inputs)
        self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["policy_rule"], "gpu_hardware_quarantine")
        self.assertFalse(receipt["executed"])

    def test_provision_instance_ceiling_enforced_and_override_allowed(self):
        # 1. High compute CPU instance (m5.16xlarge) without override MUST be refused
        inputs = {"instance_type": "m5.16xlarge", "image_id": "ami-12345", "override_ceiling": "false"}
        result, receipt = handler.aws_provision_instance(inputs)
        self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["policy_rule"], "infra_spend_ceiling_exceeded")

        # 2. With override_ceiling=true, dispatch succeeds and applies governance tags
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_ec2.run_instances.return_value = {
                "Instances": [{"InstanceId": "i-12345", "State": {"Name": "pending"}}]
            }
            mock_client.return_value = mock_ec2

            inputs["override_ceiling"] = "true"
            result, receipt = handler.aws_provision_instance(inputs)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["state"], "pending")
            self.assertTrue(receipt["executed"])

            # Verify governance tags were passed
            call_kwargs = mock_ec2.run_instances.call_args[1]
            tag_specs = call_kwargs.get("TagSpecifications", [{}])[0].get("Tags", [])
            tag_dict = {t["Key"]: t["Value"] for t in tag_specs}
            self.assertEqual(tag_dict.get("ManagedBy"), "AgentGovernance")

    def test_provision_instance_missing_image_id_errors(self):
        inputs = {"instance_type": "t3.micro"}
        result, receipt = handler.aws_provision_instance(inputs)
        self.assertIn("error", result)
        self.assertFalse(receipt["executed"])

    def test_killswitch_refuses_unmanaged_box_unless_forced(self):
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_ec2.describe_instances.return_value = {
                "Reservations": [{"Instances": [{"Tags": [{"Key": "Environment", "Value": "Production"}]}]}]
            }
            mock_client.return_value = mock_ec2

            # 1. Unmanaged box without force is refused
            inputs = {"instance_id": "i-prod-db", "force": "false"}
            result, receipt = handler.aws_emergency_killswitch(inputs)
            self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
            self.assertEqual(receipt["policy_rule"], "killswitch_unmanaged_instance_protection")
            mock_ec2.terminate_instances.assert_not_called()

            # 2. With force=true, termination is permitted
            mock_ec2.terminate_instances.return_value = {
                "TerminatingInstances": [{"CurrentState": {"Name": "shutting-down"}}]
            }
            inputs["force"] = "true"
            result, receipt = handler.aws_emergency_killswitch(inputs)
            self.assertEqual(result["status"], "success")
            mock_ec2.terminate_instances.assert_called_with(InstanceIds=["i-prod-db"])

    def test_inspect_running_spend_paginator(self):
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [
                {"Reservations": [{"Instances": [{"InstanceId": "i-1", "InstanceType": "t3.micro"}]}]},
                {"Reservations": [{"Instances": [{"InstanceId": "i-2", "InstanceType": "m5.16xlarge"}]}]}
            ]
            mock_ec2.get_paginator.return_value = mock_paginator
            mock_client.return_value = mock_ec2

            result, receipt = handler.aws_inspect_running_spend({"region": "us-west-2"})
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["active_count"], 2)
            # t3.micro (2c) + m5.16xlarge (120c) = 122c
            self.assertEqual(result["estimated_hourly_burn_cents"], 122)
            self.assertTrue(receipt["executed"])

    def test_quarantine_orphan_disks_chunking(self):
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_paginator = MagicMock()
            # Generate 1050 dummy volumes to verify batch chunking at 1000
            mock_vols = [{"VolumeId": f"vol-{i}"} for i in range(1050)]
            mock_paginator.paginate.return_value = [{"Volumes": mock_vols}]
            mock_ec2.get_paginator.return_value = mock_paginator
            mock_client.return_value = mock_ec2

            result, receipt = handler.aws_quarantine_orphan_disks({"tag_quarantine": "true"})
            self.assertEqual(result["orphan_volumes_found"], 1050)
            self.assertEqual(mock_ec2.create_tags.call_count, 2)
            self.assertTrue(receipt["executed"])

    def test_verify_immutable_db_lock(self):
        with patch("handler._get_client") as mock_client:
            mock_rds = MagicMock()
            mock_rds.describe_db_instances.return_value = {
                "DBInstances": [{"DBInstanceIdentifier": "prod-postgres", "DeletionProtection": True}]
            }
            mock_client.return_value = mock_rds

            result, receipt = handler.aws_verify_immutable_db_lock({"db_identifier": "prod-postgres"})
            self.assertTrue(result["deletion_protection"])
            self.assertTrue(receipt["protected"])

    def test_env_var_fallback(self):
        # Use clear=True so existing shell AWS_ENDPOINT_URL does not interfere
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "AKIA_CLEAN_KEY",
            "AWS_SECRET_ACCESS_KEY": "SECRET_CLEAN_KEY",
            "AWS_REGION": "ca-central-1"
        }, clear=True):
            with patch("boto3.client") as mock_boto:
                handler._get_client("ec2")
                self.assertEqual(mock_boto.call_args[0][0], "ec2")
                self.assertEqual(mock_boto.call_args[1]["region_name"], "ca-central-1")
                self.assertEqual(mock_boto.call_args[1]["aws_access_key_id"], "AKIA_CLEAN_KEY")
                self.assertEqual(mock_boto.call_args[1]["aws_secret_access_key"], "SECRET_CLEAN_KEY")


    def test_unrecognized_instance_fails_closed(self):
        """Unrecognized instance types must default above ceiling (60c) and be refused."""
        inputs = {"instance_type": "c6i.large", "image_id": "ami-12345", "override_ceiling": "false"}
        result, receipt = handler.aws_provision_instance(inputs)
        self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["policy_rule"], "infra_spend_ceiling_exceeded")

if __name__ == "__main__":
    unittest.main()
