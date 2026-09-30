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
        inputs = {"instance_type": "g6.xlarge"}
        result, receipt = handler.aws_preview_instance_launch(inputs)
        self.assertTrue(result["is_gpu_accelerated"])
        self.assertTrue(result["burn_ceiling_exceeded"])
        self.assertTrue(receipt["blocked"])

    def test_provision_instance_gpu_cannot_be_overridden(self):
        """Hardware accelerators must not be bypassed even if override_ceiling=true."""
        inputs = {"instance_type": "p4d.24xlarge", "override_ceiling": "true"}
        result, receipt = handler.aws_provision_instance(inputs)
        self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
        self.assertEqual(receipt["policy_rule"], "gpu_hardware_quarantine")
        self.assertFalse(receipt["executed"])

    def test_provision_instance_ceiling_override_allows_dispatch(self):
        """CPU instance over $0.50/hr is dispatched when override_ceiling=true."""
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_ec2.run_instances.return_value = {
                "Instances": [{"InstanceId": "i-12345", "State": {"Name": "pending"}}]
            }
            mock_client.return_value = mock_ec2

            inputs = {"instance_type": "m5.16xlarge", "override_ceiling": "true"}
            result, receipt = handler.aws_provision_instance(inputs)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["state"], "pending")
            self.assertTrue(receipt["executed"])

    def test_killswitch_refuses_unmanaged_box(self):
        """Killswitch must refuse instances lacking the governance tag."""
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_ec2.describe_instances.return_value = {
                "Reservations": [{"Instances": [{"Tags": [{"Key": "Environment", "Value": "Production"}]}]}]
            }
            mock_client.return_value = mock_ec2

            inputs = {"instance_id": "i-prod-database"}
            result, receipt = handler.aws_emergency_killswitch(inputs)
            self.assertEqual(result["airlock_status"], "REFUSED_BY_POLICY")
            self.assertEqual(receipt["policy_rule"], "killswitch_unmanaged_instance_protection")
            mock_ec2.terminate_instances.assert_not_called()

    def test_killswitch_happy_path_governed_box(self):
        """Governed instances with ManagedBy tag are terminated cleanly."""
        with patch("handler._get_client") as mock_client:
            mock_ec2 = MagicMock()
            mock_ec2.describe_instances.return_value = {
                "Reservations": [{"Instances": [{"Tags": [{"Key": "ManagedBy", "Value": "AgentGovernance"}]}]}]
            }
            mock_ec2.terminate_instances.return_value = {
                "TerminatingInstances": [{"CurrentState": {"Name": "shutting-down"}}]
            }
            mock_client.return_value = mock_ec2

            inputs = {"instance_id": "i-governed-123"}
            result, receipt = handler.aws_emergency_killswitch(inputs)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["current_state"], "shutting-down")
            self.assertTrue(receipt["executed"])

    def test_env_var_fallback(self):
        """Verify _get_client reads os.environ when Station Vault is empty."""
        with patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "AKIA_ENV_KEY",
            "AWS_SECRET_ACCESS_KEY": "SECRET_ENV_KEY",
            "AWS_REGION": "eu-west-1"
        }):
            with patch("boto3.client") as mock_boto:
                handler._get_client("ec2")
                mock_boto.assert_called_with(
                    "ec2",
                    region_name="eu-west-1",
                    aws_access_key_id="AKIA_ENV_KEY",
                    aws_secret_access_key="SECRET_ENV_KEY"
                )

    def test_provenance_hash_is_deterministic(self):
        inputs = {"instance_type": "t3.micro"}
        res, rec1 = handler.aws_preview_instance_launch(inputs, stamp="stamp_001")
        res, rec2 = handler.aws_preview_instance_launch(inputs, stamp="stamp_001")
        self.assertEqual(rec1["provenance_hash"], rec2["provenance_hash"])

if __name__ == "__main__":
    unittest.main()