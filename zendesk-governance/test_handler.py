import unittest
from unittest.mock import patch
from handlers import handler
import os

class TestZendeskGovernanceSuite(unittest.TestCase):
    def setUp(self):
        os.environ["ZENDESK_SUBDOMAIN"] = "support-test"
        os.environ["ZENDESK_EMAIL"] = "agent@example.com"
        os.environ["ZENDESK_API_TOKEN"] = "mock_token_abc"

    @patch("handlers.handler._make_api_request")
    def test_verify_zendesk_connection(self, mock_req):
        mock_req.return_value = ({"user": {"id": 101, "name": "Agent", "role": "admin"}}, 200)
        res, rcp = handler.zendesk_verify_zendesk_connection()
        self.assertTrue(res["verified"])
        self.assertEqual(rcp["user_id"], 101)
        self.assertEqual(rcp["kind"], "zendesk.verify_connection")

    def test_get_ticket_missing_id(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.zendesk_get_ticket({})
        self.assertIn("ticket_id is required", str(ctx.exception))

    @patch("handlers.handler._make_api_request")
    def test_list_open_tickets_query_filter(self, mock_req):
        mock_req.return_value = ({
            "results": [
                {"id": 1, "subject": "Outage", "status": "open", "priority": "urgent", "updated_at": "2026-03-01T10:00:00Z"},
                {"id": 2, "subject": "Billing", "status": "pending", "priority": "normal", "updated_at": "2026-03-01T11:00:00Z"}
            ]
        }, 200)
        res, rcp = handler.zendesk_list_open_tickets({"limit": 5})
        self.assertEqual(rcp["count"], 2)
        call_url = mock_req.call_args[0][0]
        self.assertIn("status%3Csolved", call_url)

    @patch("handlers.handler._make_api_request")
    def test_update_ticket_status_drift_refusal(self, mock_req):
        mock_req.return_value = (
            {"ticket": {"id": 300, "status": "open", "priority": "normal", "updated_at": "2026-03-01T10:02:00Z"}}, 
            200
        )
        with self.assertRaises(RuntimeError) as ctx:
            handler.zendesk_update_ticket_status({
                "ticket_id": "300", 
                "status": "solved", 
                "expected_fingerprint": "stale_hash_xyz"
            })
        self.assertIn("Anti-Drift Lock Triggered", str(ctx.exception))

    @patch("handlers.handler._make_api_request")
    def test_update_ticket_status_success(self, mock_req):
        initial_ticket = {"id": 300, "status": "open", "priority": "normal", "updated_at": "2026-03-01T10:00:00Z"}
        updated_ticket = {"id": 300, "status": "solved", "priority": "normal", "updated_at": "2026-03-01T10:05:00Z"}
        mock_req.side_effect = [(initial_ticket, 200), ({"ticket": updated_ticket}, 200)]

        res, rcp = handler.zendesk_update_ticket_status({"ticket_id": "300", "status": "solved"})
        self.assertEqual(res["status"], "solved")
        self.assertEqual(rcp["new_status"], "solved")

    @patch("handlers.handler._make_api_request")
    def test_escalate_ticket_priority_drift_refusal(self, mock_req):
        mock_req.return_value = (
            {"ticket": {"id": 400, "status": "open", "priority": "normal", "updated_at": "2026-03-01T10:05:00Z"}}, 
            200
        )
        with self.assertRaises(RuntimeError) as ctx:
            handler.zendesk_escalate_ticket_priority({
                "ticket_id": "400", 
                "priority": "urgent", 
                "expected_fingerprint": "stale_hash_xyz"
            })
        self.assertIn("Anti-Drift Lock Triggered", str(ctx.exception))

    @patch("handlers.handler._make_api_request")
    def test_escalate_ticket_priority_success(self, mock_req):
        initial_ticket = {"id": 400, "status": "open", "priority": "normal", "updated_at": "2026-03-01T10:00:00Z"}
        updated_ticket = {"id": 400, "status": "open", "priority": "urgent", "updated_at": "2026-03-01T10:05:00Z"}
        mock_req.side_effect = [(initial_ticket, 200), ({"ticket": updated_ticket}, 200)]

        res, rcp = handler.zendesk_escalate_ticket_priority({"ticket_id": "400", "priority": "urgent"})
        self.assertEqual(res["priority"], "urgent")
        self.assertEqual(rcp["priority"], "urgent")

    @patch("handlers.handler._make_api_request")
    def test_add_ticket_tags_uses_post_verb(self, mock_req):
        mock_req.return_value = ({"tags": ["tier1", "escalated"]}, 200)
        res, rcp = handler.zendesk_add_ticket_tags({"ticket_id": "500", "tags": "escalated"})
        self.assertIn("escalated", res["tags_added"])
        self.assertEqual(mock_req.call_args[1]["method"], "POST")

    @patch("handlers.handler._make_api_request")
    def test_post_ticket_reply_public_vs_internal(self, mock_req):
        mock_req.return_value = ({"ticket": {"id": 600}}, 200)
        res_internal, rcp_internal = handler.zendesk_post_ticket_reply({"ticket_id": "600", "body": "Audit note", "public": False})
        self.assertFalse(res_internal["public"])
        self.assertFalse(rcp_internal["public"])

        res_public, rcp_public = handler.zendesk_post_ticket_reply({"ticket_id": "600", "body": "Customer message", "public": True})
        self.assertTrue(res_public["public"])
        self.assertTrue(rcp_public["public"])

    def test_boundary_missing_parameters(self):
        with self.assertRaises(RuntimeError):
            handler.zendesk_add_ticket_tags({"ticket_id": "500", "tags": ""})
        with self.assertRaises(RuntimeError):
            handler.zendesk_post_ticket_reply({"ticket_id": "600", "body": ""})

    def test_invalid_status_boundary(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.zendesk_update_ticket_status({"ticket_id": "300", "status": "invalid_lifecycle_step"})
        self.assertIn("Invalid status", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
