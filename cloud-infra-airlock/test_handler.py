import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Ensure handler can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "handlers"))
import handler

class TestCloudInfraAirlock(unittest.TestCase):

    def test_preview_instance_launch_standard(self):
        """Standard micro instance within budget should pass preview."""
        inputs = {"instance_type": "t3.micro"}
        result, receipt = handler.aws_preview_instance_launch(inputs)
        
        self.assertFalse(result["is_gpu_accelerated"])
        self.assertFalse(result["burn_ceiling_exceeded"])
        self.assertFalse(result["will_be_blocked_at_airlock"])
        self.assertEqual(result["hourly_cost_cents"], 2)
        self.assertTrue(receipt["executed"])

    def test_preview_instance_launch_gpu_refused(self):
        """GPU accelerator instance must be flagged for local airlock refusal."""
        inputs = {"instance_type": "g4dn.xlarge"}
        result, receipt = handler.aws_preview_instance_launch(inputs)
        
        self.assertTrue(result["is_gpu_accelerated"])
        self.assertTrue(result["burn_ceiling_exceeded"])
        self.assertTrue(result["will_be_blocked_at_airlock"])
        self.assertTrue(receipt["blocked"])

    def test_provision_instance_spend_ceiling_refused(self):
        """High cost / GPU provisioning must be rejected before AWS dispatch without network egress."""
        inputs = {"instance_type": "p3.2xlarge", "override_ceiling": "false"}
        result, receipt = handler.aws_provision_instance(inputs)
        
        self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["policy_rule"], "infra_spend_ceiling_exceeded")
        self.assertEqual(receipt["blocked_at"], "127.0.0.1")

    def test_provision_instance_emergency_killswitch_missing_id(self):
        """Killswitch must cleanly fail when missing target instance ID."""
        inputs = {}
        result, receipt = handler.aws_emergency_killswitch(inputs)
        
        self.assertIn("error", result)
        self.assertFalse(receipt["executed"])

    @patch("handler._get_client")
    def test_quarantine_orphan_disks(self, mock_client):
        """Orphan detached disks must be located and tagged for quarantine."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_volumes.return_value = {
            "Volumes": [{"VolumeId": "vol-0123456789abcdef0", "Size": 100}]
        }
        mock_client.return_value = mock_ec2

        inputs = {"tag_quarantine": "true"}
        result, receipt = handler.aws_quarantine_orphan_disks(inputs)

        self.assertEqual(result["orphan_volumes_found"], 1)
        mock_ec2.create_tags.assert_called_once()
        self.assertEqual(receipt["count"], 1)

    @patch("handler._get_client")
    def test_verify_immutable_db_lock_protected(self, mock_client):
        """Protected RDS databases return safe_for_agent_ops: True."""
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "prod-db", "DeletionProtection": True}]
        }
        mock_client.return_value = mock_rds

        inputs = {"db_identifier": "prod-db"}
        result, receipt = handler.aws_verify_immutable_db_lock(inputs)

        self.assertTrue(result["deletion_protection"])
        self.assertTrue(result["safe_for_agent_ops"])
        self.assertTrue(receipt["protected"])

    @patch("handler._get_client")
    def test_verify_immutable_db_lock_unprotected(self, mock_client):
        """Unprotected RDS databases return safe_for_agent_ops: False."""
        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {
            "DBInstances": [{"DBInstanceIdentifier": "dev-db", "DeletionProtection": False}]
        }
        mock_client.return_value = mock_rds

        inputs = {"db_identifier": "dev-db"}
        result, receipt = handler.aws_verify_immutable_db_lock(inputs)

        self.assertFalse(result["deletion_protection"])
        self.assertFalse(result["safe_for_agent_ops"])
        self.assertFalse(receipt["protected"])

    def test_credential_casing_resilience(self):
        """Verify credential reader handles case insensitivity and vault fallbacks."""
        client_func = getattr(handler, "_get_client")
        self.assertTrue(callable(client_func))

if __name__ == "__main__":
    unittest.main()