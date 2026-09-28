import unittest
from unittest.mock import patch
import os
from handlers import handler

class TestStripeGovernanceAirlock(unittest.TestCase):
    def setUp(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_mock_secret_key_12345"

    @patch("handlers.handler._stripe_request")
    def test_verify_connection_success(self, mock_req):
        mock_req.return_value = {
            "id": "acct_test_123",
            "charges_enabled": True
        }
        res, rcp = handler.stripe_verify_connection()
        self.assertTrue(res.get("verified"))
        self.assertEqual(res.get("account_id"), "acct_test_123")
        self.assertEqual(rcp.get("kind"), "stripe.verify_connection")

    @patch("handlers.handler._stripe_request")
    def test_create_customer_dedup_reuse(self, mock_req):
        mock_req.return_value = {"data": [{"id": "cus_existing_1"}]}
        res, rcp = handler.stripe_create_customer({"email": "test@example.com"})
        self.assertEqual(res.get("status"), "already_exists")
        self.assertEqual(res.get("customer_id"), "cus_existing_1")
        self.assertTrue(res.get("reused"))
        self.assertEqual(rcp.get("action"), "reused")

    @patch("handlers.handler._stripe_request")
    def test_create_customer_success(self, mock_req):
        mock_req.side_effect = [
            {"data": []},
            {"id": "cus_new_1", "email": "test@example.com", "name": "Jane"}
        ]
        res, rcp = handler.stripe_create_customer({"email": "test@example.com", "name": "Jane"})
        self.assertEqual(res.get("status"), "created")
        self.assertEqual(res.get("customer_id"), "cus_new_1")
        self.assertEqual(rcp.get("action"), "created")

    def test_create_payment_link_floor_refusal(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.stripe_create_payment_link({"price_id": "price_123", "quantity": 0})
        self.assertIn("must be positive", str(ctx.exception).lower())

    @patch("handlers.handler._stripe_request")
    def test_create_payment_link_success(self, mock_req):
        mock_req.return_value = {"id": "pl_456", "url": "https://buy.stripe.com/test"}
        res, rcp = handler.stripe_create_payment_link({"price_id": "price_123", "quantity": 1})
        self.assertEqual(res.get("payment_link_id"), "pl_456")
        self.assertEqual(rcp.get("kind"), "stripe.create_payment_link")

    @patch("handlers.handler._stripe_request")
    def test_refund_anti_drift_guard(self, mock_req):
        mock_req.return_value = {
            "id": "ch_mock_123",
            "amount": 10000,
            "amount_refunded": 5000,
            "status": "succeeded"
        }
        with self.assertRaises(RuntimeError) as ctx:
            handler.stripe_refund_charge({
                "charge_id": "ch_mock_123",
                "amount": 5000,
                "expected_fingerprint": "stale_fingerprint_abc"
            })
        self.assertIn("anti-drift lock triggered", str(ctx.exception).lower())

    def test_adjust_credit_balance_ceiling_refusal(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.stripe_adjust_credit_balance({"customer_id": "cus_1", "amount": 150000})
        self.assertIn("ceiling guard triggered", str(ctx.exception).lower())

    @patch("handlers.handler._stripe_request")
    def test_adjust_credit_balance_success(self, mock_req):
        mock_req.return_value = {"id": "cbt_123", "ending_balance": 1500}
        res, rcp = handler.stripe_adjust_credit_balance({"customer_id": "cus_mock_1", "amount": 500})
        self.assertEqual(res.get("new_ending_balance"), 1500)
        self.assertEqual(rcp.get("kind"), "stripe.adjust_credit_balance")

    @patch("handlers.handler._stripe_request")
    def test_cancel_subscription_terminal_guard(self, mock_req):
        mock_req.return_value = {"id": "sub_123", "status": "canceled"}
        with self.assertRaises(RuntimeError) as ctx:
            handler.stripe_cancel_subscription({"subscription_id": "sub_123"})
        self.assertIn("already in terminal state", str(ctx.exception).lower())

    @patch("handlers.handler._stripe_request")
    def test_cancel_subscription_graceful_success(self, mock_req):
        mock_req.side_effect = [
            {"id": "sub_123", "status": "active"},
            {"id": "sub_123", "cancel_at_period_end": True, "current_period_end": 1800000000}
        ]
        res, rcp = handler.stripe_cancel_subscription({"subscription_id": "sub_123", "immediately": False})
        self.assertEqual(res.get("action"), "scheduled_for_period_end")
        self.assertTrue(res.get("cancel_at_period_end"))
        self.assertEqual(rcp.get("kind"), "stripe.cancel_subscription")

    @patch("handlers.handler._stripe_request")
    def test_void_invoice_success(self, mock_req):
        mock_req.side_effect = [
            {"id": "in_123", "status": "open"},
            {"id": "in_123", "status": "void"}
        ]
        res, rcp = handler.stripe_void_invoice({"invoice_id": "in_123"})
        self.assertEqual(res.get("status"), "voided")
        self.assertEqual(rcp.get("kind"), "stripe.void_invoice")

    @patch("handlers.handler._stripe_request")
    def test_get_customer_overview_success(self, mock_req):
        mock_req.return_value = {
            "id": "cus_123",
            "email": "jane@corp.io",
            "balance": 2500,
            "currency": "usd",
            "delinquent": False,
            "created": 1700000000
        }
        res, rcp = handler.stripe_get_customer_overview({"customer_id": "cus_123"})
        self.assertEqual(res.get("customer", {}).get("email"), "jane@corp.io")
        self.assertEqual(rcp.get("kind"), "stripe.get_customer_overview")

if __name__ == "__main__":
    unittest.main()
