import unittest
from unittest.mock import patch
from handlers import handler
import os

class TestShopifyAdminSuite(unittest.TestCase):
    def setUp(self):
        os.environ["SHOPIFY_SHOP_DOMAIN"] = "demo-store.myshopify.com"
        os.environ["SHOPIFY_ACCESS_TOKEN"] = "shpat_mock_access_token_123"

    @patch("handlers.handler._request")
    def test_verify_connection_success(self, mock_req):
        mock_req.return_value = {
            "shop": {
                "name": "Demo Store",
                "currency": "USD",
                "myshopify_domain": "demo-store.myshopify.com",
                "email": "owner@demo.com"
            }
        }
        res, rcp = handler.shopify_verify_shopify_connection()
        self.assertTrue(res.get("verified"))
        self.assertEqual(res.get("shop_name"), "Demo Store")
        self.assertEqual(res.get("currency"), "USD")
        self.assertEqual(rcp.get("kind"), "shopify.verify_shopify_connection")
        self.assertEqual(rcp.get("shop"), "demo-store.myshopify.com")

    @patch("handlers.handler._request")
    def test_get_order_rich_schema(self, mock_req):
        mock_req.return_value = {
            "order": {
                "id": 888,
                "name": "#1001",
                "email": "buyer@example.com",
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled",
                "total_price": "150.00",
                "total_refunded": "0.00",
                "tags": "vip, repeat",
                "updated_at": "2026-03-01T12:00:00Z",
                "line_items": [{"id": 1, "title": "Widget"}]
            }
        }
        res, rcp = handler.shopify_get_order({"order_id": "888"})
        self.assertEqual(res.get("order", {}).get("name"), "#1001")
        self.assertEqual(res.get("order", {}).get("financial_status"), "paid")
        self.assertIn("fingerprint", res)
        self.assertEqual(rcp.get("kind"), "shopify.get_order")
        self.assertEqual(rcp.get("order_id"), "888")

    @patch("handlers.handler._request")
    def test_list_orders_success(self, mock_req):
        mock_req.return_value = {
            "orders": [
                {"id": 1, "name": "#1001", "financial_status": "paid", "total_price": "45.00"},
                {"id": 2, "name": "#1002", "financial_status": "pending", "total_price": "89.00"}
            ]
        }
        res, rcp = handler.shopify_list_orders({"limit": 5})
        self.assertEqual(len(res.get("orders", [])), 2)
        self.assertEqual(rcp.get("kind"), "shopify.list_orders")

    def test_create_refund_ceiling_guard_refusal(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_create_refund({"order_id": "101", "amount": "150.00", "allow_high_refund": False})
        self.assertIn("exceeds $100 ceiling", str(ctx.exception))

    @patch("handlers.handler._request")
    def test_create_refund_success(self, mock_req):
        mock_req.side_effect = [
            {"order": {"id": 101, "currency": "USD", "transactions": [{"id": 55555}], "gateway": "shopify_payments"}},
            {"refund": {"id": 999}}
        ]
        res, rcp = handler.shopify_create_refund({"order_id": "101", "amount": "25.00"})
        self.assertEqual(res.get("refund_id"), 999)
        self.assertEqual(res.get("status"), "refunded")
        self.assertEqual(rcp.get("kind"), "shopify.create_refund")

    @patch("handlers.handler._request")
    def test_cancel_order_failure_refusal(self, mock_req):
        mock_req.return_value = {"order": {}}
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_cancel_order({"order_id": "303"})
        self.assertIn("reported cancellation failure", str(ctx.exception).lower())

    @patch("handlers.handler._request")
    def test_cancel_order_success(self, mock_req):
        mock_req.return_value = {"order": {"id": 303, "cancelled_at": "2026-03-01T14:00:00Z"}}
        res, rcp = handler.shopify_cancel_order({"order_id": "303"})
        self.assertEqual(res.get("order_id"), "303")
        self.assertEqual(res.get("cancelled_at"), "2026-03-01T14:00:00Z")
        self.assertEqual(rcp.get("kind"), "shopify.cancel_order")

    @patch("handlers.handler._request")
    def test_add_order_tags_drift_refusal(self, mock_req):
        mock_req.return_value = {
            "order": {
                "id": 202,
                "financial_status": "paid",
                "tags": "new, urgent",
                "updated_at": "2026-03-01T10:05:00Z"
            }
        }
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_add_order_tags({
                "order_id": "202",
                "tags": "verified",
                "expected_fingerprint": "stale_hash_xyz"
            })
        msg = str(ctx.exception).lower()
        self.assertTrue("drift" in msg or "state" in msg or "fingerprint" in msg)

    @patch("handlers.handler._request")
    def test_add_order_tags_success(self, mock_req):
        mock_req.side_effect = [
            {"order": {"id": 202, "financial_status": "paid", "tags": "vip", "updated_at": "2026-03-01T10:00:00Z"}},
            {"order": {"id": 202, "tags": "vip, expedited"}}
        ]
        res, rcp = handler.shopify_add_order_tags({"order_id": "202", "tags": "expedited"})
        self.assertEqual(res.get("tags"), "vip, expedited")
        self.assertEqual(rcp.get("kind"), "shopify.add_order_tags")

    def test_update_inventory_negative_floor_refusal(self):
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_update_inventory({"inventory_item_id": "item_1", "location_id": "loc_1", "available": -5})
        self.assertIn("cannot be negative", str(ctx.exception).lower())

    @patch("handlers.handler._request")
    def test_update_inventory_success(self, mock_req):
        mock_req.return_value = {"inventory_level": {"inventory_item_id": 111, "available": 15}}
        res, rcp = handler.shopify_update_inventory({"inventory_item_id": "111", "location_id": "222", "available": 15})
        self.assertEqual(res.get("available"), 15)
        self.assertEqual(rcp.get("kind"), "shopify.update_inventory")

    @patch("handlers.handler._request")
    def test_close_order_guard_unfulfilled_refusal(self, mock_req):
        mock_req.return_value = {
            "order": {
                "id": 404,
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled"
            }
        }
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_close_order({"order_id": "404"})
        self.assertIn("is not fulfilled", str(ctx.exception).lower())

    @patch("handlers.handler._request")
    def test_close_order_success(self, mock_req):
        mock_req.side_effect = [
            {"order": {"id": 404, "financial_status": "paid", "fulfillment_status": "fulfilled"}},
            {"order": {"id": 404, "closed_at": "2026-03-01T15:00:00Z"}}
        ]
        res, rcp = handler.shopify_close_order({"order_id": "404"})
        self.assertEqual(res.get("order_id"), "404")
        self.assertEqual(res.get("closed_at"), "2026-03-01T15:00:00Z")
        self.assertEqual(rcp.get("kind"), "shopify.close_order")

    @patch("handlers.handler._request")
    def test_create_fulfillment_cancelled_guard_refusal(self, mock_req):
        mock_req.return_value = {
            "order": {
                "id": 505,
                "cancelled_at": "2026-03-01T09:00:00Z"
            }
        }
        with self.assertRaises(RuntimeError) as ctx:
            handler.shopify_create_fulfillment({"order_id": "505", "tracking_number": "TRK123"})
        self.assertIn("cancellation guard", str(ctx.exception).lower())

    @patch("handlers.handler._request")
    def test_create_fulfillment_success(self, mock_req):
        mock_req.side_effect = [
            {"order": {"id": 505, "cancelled_at": None}},
            {"fulfillment": {"id": 777, "status": "success"}}
        ]
        res, rcp = handler.shopify_create_fulfillment({"order_id": "505", "tracking_number": "TRK123"})
        self.assertEqual(res.get("fulfillment_id"), 777)
        self.assertEqual(rcp.get("kind"), "shopify.create_fulfillment")

if __name__ == "__main__":
    unittest.main()
