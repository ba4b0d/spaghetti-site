/**
 * Per-provider gateway URL allowlist and validator.
 *
 * Extracted from the pay page so BOTH the page that starts a payment and the
 * token-free hand-off page that finishes it validate against the exact same
 * rules. Mirrors the backend as defence in depth: the browser is never handed
 * an arbitrary or plaintext URL even if a provider response is tampered with.
 *
 * DigiPay host names are whitelisted as-is; BitPay lives entirely on
 * ``bitpay.ir``, where live vs. sandbox is a **path** prefix (``/payment`` vs
 * ``/payment-test``), so both documented portal prefixes are accepted while any
 * other host, path, query or shape is refused.
 */

export const GATEWAY_ALLOWLIST = Object.freeze({
  digipay: Object.freeze({
    hosts: Object.freeze(['web.mydigipay.com', 'uatweb.mydigipay.info']),
    pathPattern: null,
    rejectQuery: false,
  }),
  bitpay: Object.freeze({
    hosts: Object.freeze(['bitpay.ir']),
    // documented live + sandbox portal: /payment[-test]/gateway-<id_get>-get
    pathPattern: /^\/payment(?:-test)?\/gateway-\d+-get$/,
    rejectQuery: true,
  }),
});

/** DigiPay web-pay hosts (alias kept for callers of the previous name). */
export const ALLOWED_GATEWAY_HOSTS = GATEWAY_ALLOWLIST.digipay.hosts;

/**
 * Return the validated absolute HTTPS gateway URL for ``provider``, or ``null``
 * when the server's URL is not allowed for that provider. An unknown/missing
 * provider fails closed.
 */
export function validateGatewayUrl(url, provider) {
  const hasRules =
    typeof provider === 'string' &&
    Object.prototype.hasOwnProperty.call(GATEWAY_ALLOWLIST, provider);
  const rules = hasRules ? GATEWAY_ALLOWLIST[provider] : null;
  if (!rules) return null;
  if (typeof url !== 'string' || !url.trim()) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:') return null;
  if (parsed.username || parsed.password) return null;
  if (rules.rejectQuery && (parsed.search || parsed.hash)) return null;
  if (!rules.hosts.includes(parsed.hostname.toLowerCase())) return null;
  if (rules.pathPattern && !rules.pathPattern.test(parsed.pathname)) return null;
  return parsed.href;
}
