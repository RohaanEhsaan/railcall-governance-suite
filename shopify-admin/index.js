const axios = require('axios');

function getClient(secrets) {
  const store = (secrets.SHOPIFY_STORE_DOMAIN || '')
    .replace(/^https?:\/\//, '')
    .replace(/\/$/, '');

  return axios.create({
    baseURL: `https://${store}/admin/api/2024-07`,
    headers: {
      'X-Shopify-Access-Token': secrets.SHOPIFY_ACCESS_TOKEN,
      'Content-Type': 'application/json'
    }
  });
}

// 1. PREVIEW PHASE
async function preview(action, inputs, secrets) {
  const client = getClient(secrets);

  switch (action) {
    case 'create_refund': {
      const { data } = await client.get(`/orders/${inputs.order_id}.json?fields=id,name,total_price,currency`);
      return {
        impact: "FINANCIAL_DEBIT",
        message: `Issue refund of ${inputs.currency || 'USD'} ${inputs.amount} for Order ${data.order.name}`,
        details: {
          order_id: inputs.order_id,
          order_name: data.order.name,
          refund_amount: `${inputs.currency || 'USD'} ${inputs.amount}`,
          restock: inputs.restock ?? true,
          note: inputs.note || 'No note provided'
        }
      };
    }

    case 'cancel_order': {
      return {
        impact: "ORDER_STATE_CHANGE",
        message: `Permanently cancel Shopify Order #${inputs.order_id}`,
        details: { order_id: inputs.order_id, reason: inputs.reason || 'other' }
      };
    }

    case 'create_fulfillment': {
      return {
        impact: "FULFILLMENT_UPDATE",
        message: `Create fulfillment for Order #${inputs.order_id}`,
        details: {
          order_id: inputs.order_id,
          tracking_number: inputs.tracking_number || 'N/A',
          carrier: inputs.tracking_company || 'Standard'
        }
      };
    }

    case 'update_inventory': {
      return {
        impact: "INVENTORY_MUTATION",
        message: `Set available inventory to ${inputs.available} for Item #${inputs.inventory_item_id}`,
        details: {
          inventory_item_id: inputs.inventory_item_id,
          location_id: inputs.location_id,
          new_available: inputs.available
        }
      };
    }

    case 'add_order_tags': {
      return {
        impact: "METADATA_UPDATE",
        message: `Append tags "${inputs.tags}" to Order #${inputs.order_id}`
      };
    }

    case 'get_order': {
      return {
        impact: "READ_ONLY",
        message: `Fetch order details for Order #${inputs.order_id}`
      };
    }

    default:
      return { message: `Execute ${action} with provided parameters.` };
  }
}

// 2. EXECUTE PHASE
async function execute(action, inputs, secrets) {
  const client = getClient(secrets);

  switch (action) {
    case 'create_refund': {
      const calcRes = await client.post(`/orders/${inputs.order_id}/refunds/calculate.json`, {
        refund: {
          currency: inputs.currency || 'USD',
          transactions: [{ kind: 'refund', amount: inputs.amount }]
        }
      });

      const refundPayload = {
        refund: {
          note: inputs.note || 'Refund processed via RailCall',
          transactions: [{
            parent_id: calcRes.data.refund.transactions[0]?.parent_id,
            amount: inputs.amount,
            kind: 'refund',
            gateway: calcRes.data.refund.transactions[0]?.gateway
          }]
        }
      };

      const { data } = await client.post(`/orders/${inputs.order_id}/refunds.json`, refundPayload);
      return {
        status: "SUCCESS",
        receipt: {
          refund_id: data.refund.id,
          order_id: inputs.order_id,
          created_at: data.refund.created_at
        }
      };
    }

    case 'cancel_order': {
      const { data } = await client.post(`/orders/${inputs.order_id}/cancel.json`, {
        reason: inputs.reason || 'other'
      });
      return {
        status: "SUCCESS",
        receipt: { order_id: data.order.id, cancelled_at: data.order.cancelled_at }
      };
    }

    case 'create_fulfillment': {
      // Fetch fulfillment order ID required by Shopify API 2024+
      const foRes = await client.get(`/orders/${inputs.order_id}/fulfillment_orders.json`);
      const fulfillmentOrderId = foRes.data.fulfillment_orders[0]?.id;

      if (!fulfillmentOrderId) {
        throw new Error(`No unfulfilled line items found for Order #${inputs.order_id}`);
      }

      const { data } = await client.post('/fulfillments.json', {
        fulfillment: {
          line_items_by_fulfillment_order: [{ fulfillment_order_id: fulfillmentOrderId }],
          tracking_info: {
            number: inputs.tracking_number || '',
            company: inputs.tracking_company || 'Standard'
          }
        }
      });

      return {
        status: "SUCCESS",
        receipt: {
          fulfillment_id: data.fulfillment.id,
          order_id: inputs.order_id,
          status: data.fulfillment.status
        }
      };
    }

    case 'update_inventory': {
      const { data } = await client.post('/inventory_levels/set.json', {
        location_id: inputs.location_id,
        inventory_item_id: inputs.inventory_item_id,
        available: inputs.available
      });
      return {
        status: "SUCCESS",
        receipt: {
          inventory_item_id: data.inventory_level.inventory_item_id,
          location_id: data.inventory_level.location_id,
          available: data.inventory_level.available
        }
      };
    }

    case 'add_order_tags': {
      const existing = await client.get(`/orders/${inputs.order_id}.json?fields=tags`);
      const currentTags = existing.data.order.tags ? `${existing.data.order.tags}, ` : '';
      const updatedTags = `${currentTags}${inputs.tags}`;

      const { data } = await client.put(`/orders/${inputs.order_id}.json`, {
        order: { id: inputs.order_id, tags: updatedTags }
      });
      return {
        status: "SUCCESS",
        receipt: { order_id: data.order.id, tags: data.order.tags }
      };
    }

    case 'get_order': {
      const { data } = await client.get(`/orders/${inputs.order_id}.json`);
      return { status: "SUCCESS", data: data.order };
    }

    default:
      throw new Error(`Unsupported action: ${action}`);
  }
}

module.exports = { preview, execute };