const https = require('https');
const querystring = require('querystring');

function callStripe(endpoint, method = 'GET', data = null, secretKey) {
  if (!secretKey || !secretKey.startsWith('sk_')) {
    return Promise.reject(new Error('STATION_AUTH_ERROR: Missing or malformed Stripe Secret Key.'));
  }

  const postData = data ? querystring.stringify(data) : '';
  const options = {
    hostname: 'api.stripe.com',
    port: 443,
    path: `/v1/${endpoint}`,
    method,
    headers: {
      'Authorization': `Bearer ${secretKey}`,
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  };

  if (method === 'POST') {
    options.headers['Content-Length'] = Buffer.byteLength(postData);
  }

  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        try {
          const parsed = JSON.parse(body);
          if (res.statusCode >= 400) {
            reject(new Error(`STRIPE_API_ERROR [${res.statusCode}]: ${parsed.error ? parsed.error.message : 'Unknown'}`));
          } else {
            resolve(parsed);
          }
        } catch (err) {
          reject(new Error(`RESPONSE_PARSE_ERROR: ${err.message}`));
        }
      });
    });

    req.on('error', (e) => reject(new Error(`NETWORK_ERROR: ${e.message}`)));
    if (data && method === 'POST') req.write(postData);
    req.end();
  });
}

async function previewRefund({ charge_id, amount_cents, reason }, secretKey) {
  // Support both pi_ (PaymentIntent) and ch_ (Charge)
  const isIntent = charge_id.startsWith('pi_');
  const endpoint = isIntent ? `payment_intents/${charge_id}` : `charges/${charge_id}`;
  const record = await callStripe(endpoint, 'GET', null, secretKey);

  const totalAmount = isIntent ? record.amount : record.amount;
  const alreadyRefunded = isIntent ? (record.amount_received - record.amount) : record.amount_refunded;
  const refundAmount = amount_cents || (totalAmount - alreadyRefunded);

  return {
    will_execute: 'stripe.refunds.create',
    target_id: charge_id,
    currency: record.currency.toUpperCase(),
    total_original_cents: totalAmount,
    proposed_refund_cents: refundAmount,
    proposed_refund_formatted: `$${(refundAmount / 100).toFixed(2)}`,
    reason: reason || 'requested_by_customer',
    warning: 'Airlock Halt: Requires explicit operator approval before funds move.'
  };
}

async function executeRefund({ charge_id, amount_cents, reason }, secretKey) {
  const payload = {};
  if (charge_id.startsWith('pi_')) {
    payload.payment_intent = charge_id;
  } else {
    payload.charge = charge_id;
  }
  if (amount_cents) payload.amount = amount_cents;
  if (reason) payload.reason = reason;

  const result = await callStripe('refunds', 'POST', payload, secretKey);

  return {
    status: result.status,
    refund_id: result.id,
    amount_refunded_cents: result.amount,
    currency: result.currency,
    receipt_number: result.receipt_number || null,
    created_at: new Date(result.created * 1000).toISOString()
  };
}

module.exports = async function handler(context) {
  const { action, dryRun, payload, secrets } = context;
  const stripeKey = secrets.STRIPE_SECRET_KEY;

  if (!stripeKey) {
    throw new Error('CONFIG_ERROR: STRIPE_SECRET_KEY not injected into airlock runtime.');
  }

  switch (action) {
    case 'refund_charge':
      return dryRun
        ? await previewRefund(payload, stripeKey)
        : await executeRefund(payload, stripeKey);

    default:
      throw new Error(`UNKNOWN_ACTION: Capability '${action}' is not handled.`);
  }
};