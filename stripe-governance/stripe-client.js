const https = require('https');
const querystring = require('querystring');

async function callStripe(endpoint, method = 'GET', data = null, secretKey) {
  if (!secretKey || !secretKey.startsWith('sk_')) {
    throw new Error('STATION_AUTH_ERROR: Missing or malformed Stripe Secret Key.');
  }

  const postData = data ? querystring.stringify(data) : '';
  const options = {
    hostname: 'api.stripe.com',
    port: 443,
    path: `/v1/${endpoint}`,
    method,
    headers: {
      'Authorization': `Bearer ${secretKey}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'Stripe-Version': '2023-10-16'
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

module.exports = { callStripe };