import unittest
from unittest.mock import patch
from handlers import handler

class TestLinearGovernanceSuite(unittest.TestCase):

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_verify_connection_success(self, mock_gql, mock_creds):
        mock_gql.return_value = {
            "data": {
                "viewer": {"id": "usr_123", "name": "Dev", "email": "dev@test.io"}
            }
        }
        res, rcp = handler.linear_verify_connection()
        self.assertTrue(res.get("verified"))
        self.assertEqual(rcp.get("user"), "dev@test.io")
        self.assertEqual(rcp.get("kind"), "linear.verify_connection")

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_create_issue_lifecycle(self, mock_gql, mock_creds):
        mock_gql.return_value = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "iss_1", "identifier": "ENG-1", "title": "Test Issue", "url": "https://linear.app/issue/ENG-1"}
                }
            }
        }
        res, rcp = handler.linear_create_issue({"teamId": "t1", "title": "Test Issue", "priority": 2})
        self.assertEqual(res.get("identifier"), "ENG-1")
        self.assertEqual(rcp.get("identifier"), "ENG-1")

    def test_update_priority_urgent_guard_refusal(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.linear_update_priority({"issueId": "i1", "priority": 1, "allow_urgent": False})
        self.assertIn("P1/Urgent escalation requires explicit allow_urgent=True", str(ctx.exception))

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_update_priority_with_override_success(self, mock_gql, mock_creds):
        mock_gql.side_effect = [
            {"data": {"issue": {"id": "i1", "priority": 2, "updatedAt": "2026-03-01T10:00:00Z"}}},
            {"data": {"issueUpdate": {"success": True, "issue": {"id": "i1", "priority": 1, "identifier": "ENG-1"}}}}
        ]
        res, rcp = handler.linear_update_priority({"issueId": "i1", "priority": 1, "allow_urgent": True})
        self.assertEqual(res.get("priority"), 1)
        self.assertTrue(res.get("guard_passed"))
        self.assertTrue(rcp.get("escalation_approved"))

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_transition_status_drift_refusal(self, mock_gql, mock_creds):
        mock_gql.return_value = {
            "data": {
                "issue": {
                    "id": "i1",
                    "identifier": "ENG-101",
                    "title": "Bug in billing",
                    "updatedAt": "2026-03-01T10:00:00Z",
                    "state": {"id": "state_1", "name": "Backlog"}
                }
            }
        }
        with self.assertRaises(RuntimeError) as ctx:
            handler.linear_transition_status({
                "issueId": "i1",
                "stateId": "s2",
                "expected_fingerprint": "stale_hash_xyz"
            })
        self.assertIn("State drifted", str(ctx.exception))

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_get_issue_success(self, mock_gql, mock_creds):
        mock_gql.return_value = {
            "data": {
                "issue": {"id": "iss_1", "identifier": "ENG-101", "title": "Crash on login", "priority": 1, "updatedAt": "2026-03-01T10:00:00Z"}
            }
        }
        res, rcp = handler.linear_get_issue({"issueId": "iss_1"})
        self.assertEqual(res["issue"]["identifier"], "ENG-101")
        self.assertIn("fingerprint", res)
        self.assertEqual(rcp["kind"], "linear.get_issue")

    @patch("handlers.handler._creds", return_value="lin_api_test_key_123")
    @patch("handlers.handler._graphql")
    def test_list_team_issues_success(self, mock_gql, mock_creds):
        mock_gql.return_value = {
            "data": {
                "team": {
                    "issues": {
                        "nodes": [{"id": "iss_1", "identifier": "ENG-1"}, {"id": "iss_2", "identifier": "ENG-2"}]
                    }
                }
            }
        }
        res, rcp = handler.linear_list_team_issues({"teamId": "team_core", "limit": 10})
        self.assertEqual(len(res.get("issues", [])), 2)
        self.assertEqual(rcp.get("kind"), "linear.list_team_issues")

if __name__ == "__main__":
    unittest.main()
