const { callStripe } = require('../lib/stripe-client');

async function previewRefund({ charge_id, amount_cents, reason }, secretKey) {
  // Safe verification: Read the live charge first to present an exact preview
  const charge = await callStripe(`charges/${charge_id}`, 'GET', null, secretKey);
  const refundAmount = amount_cents || charge.amount - charge.amount_refunded;

  return {
    will_execute: 'stripe.refunds.create',
    charge_id,
    customer: charge.customer,
    currency: charge.currency.toUpperCase(),
    total_original_cents: charge.amount,
    already_refunded_cents: charge.amount_refunded,
    proposed_refund_cents: refundAmount,
    proposed_refund_formatted: `$${(refundAmount / 100).toFixed(2)}`,
    reason: reason || 'requested_by_customer',
    warning: refundAmount > charge.amount - charge.amount_refunded 
      ? 'HALT: Requested amount exceeds refundable balance.' 
      : 'Requires explicit airlock approval before funds are moved.'
  };
}

async function executeRefund({ charge_id, amount_cents, reason }, secretKey) {
  const payload = { charge: charge_id };
  if (amount_cents) payload.amount = amount_cents;
  if (reason) payload.reason = reason;

  const result = await callStripe('refunds', 'POST', payload, secretKey);

  return {
    status: result.status,
    refund_id: result.id,
    charge_id: result.charge,
    amount_refunded: result.amount,
    currency: result.currency,
    receipt_number: result.receipt_number,
    created_at: new Date(result.created * 1000).toISOString()
  };
}

module.exports = { previewRefund, executeRefund };