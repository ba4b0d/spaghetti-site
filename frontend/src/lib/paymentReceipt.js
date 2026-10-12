/**
 * Per-tab payment receipt — the private invoice bearer token parked for the
 * token-free result page.
 *
 * WHY THIS EXISTS
 * The BitPay callback 303-redirects the payer's browser to the public,
 * token-free page ``/pay/result?payment=success|failed|pending``. The backend
 * deliberately keeps that redirect free of the private bearer token: the token
 * is never persisted server-side (only its hash is), so it cannot be rebuilt,
 * and it must not be echoed into a ``Location`` header, a query string, a
 * Referer or an access log. The result page therefore starts with only an
 * untrusted presentation hint — it cannot, and must not, prove a payment from
 * it.
 *
 * To show the customer a TRUTHFUL confirmation (invoice number + amount) the
 * result page still needs the private invoice read, which lives behind the
 * bearer token. The pay page (``/pay/<token>``) already knows that token and
 * already parks the *validated gateway URL* in per-tab ``sessionStorage`` for
 * the token-free hand-off; it parks the token here the same way, keyed to that
 * hand-off. ``sessionStorage`` is per-tab and origin-scoped and is NEVER sent
 * over the network, so the token stays out of every URL, query string, Referer
 * and access log — the same guarantee the invoice page gets from its own
 * ``no-referrer`` / ``no-store`` headers.
 *
 * SAFETY
 *  - The parked token is only ever read back by the result page to make the
 *    SAME private invoice GET the pay page makes; the server remains the sole
 *    authority for whether the invoice is paid. The result page shows the
 *    confirmation ONLY when the server reports the invoice ``state === 'paid'``.
 *  - It is separate from the gateway hand-off entry, which MUST stay token-free
 *    (see ``paymentHandoff.js``): the two live under different keys, so neither
 *    guarantee weakens the other.
 *  - A missing/expired/malformed entry is never an error: the result page falls
 *    back to its generic, fail-closed copy. Mobile tab loss — the portal
 *    opening in a new tab, or the browser discarding the tab — simply loses the
 *    receipt, safely.
 *  - Writing to a storage that can throw (locked-down private mode) is
 *    best-effort and returns ``false`` rather than raising.
 *
 * LIFETIME
 * The entry is bounded by ``PAYMENT_RECEIPT_MAX_AGE_MS`` and the result page
 * clears it once it has read a server-confirmed ``paid`` invoice, so the raw
 * bearer token is never kept in storage indefinitely.
 */

export const PAYMENT_RECEIPT_KEY = 'spaghetti:payment:invoice-receipt';

/** A parked receipt older than this is ignored (fail closed). */
export const PAYMENT_RECEIPT_MAX_AGE_MS = 60 * 60 * 1000;

/** sessionStorage, or null when unavailable (private mode / disabled storage). */
function safeSession() {
  try {
    if (typeof window === 'undefined') return null;
    return window.sessionStorage || null;
  } catch {
    // Accessing sessionStorage itself can throw in hardened browsers.
    return null;
  }
}

/**
 * Park the private invoice bearer token for the result page. Best-effort:
 * returns ``false`` (never throws) when storage is unavailable or the token is
 * not a usable string.
 */
export function writePaymentReceipt(token) {
  if (typeof token !== 'string' || !token) return false;
  const store = safeSession();
  if (!store) return false;
  try {
    store.setItem(PAYMENT_RECEIPT_KEY, JSON.stringify({ token, ts: Date.now() }));
    return true;
  } catch {
    return false;
  }
}

/**
 * Read and structurally validate the parked receipt.
 *
 * Returns ``{ token }`` or ``null``. Fail-closed: any missing, malformed,
 * incomplete or stale (older than ``PAYMENT_RECEIPT_MAX_AGE_MS``) entry yields
 * ``null`` — the caller then simply renders its generic, non-committal copy.
 */
export function readPaymentReceipt(now = Date.now()) {
  const store = safeSession();
  if (!store) return null;
  let raw;
  try {
    raw = store.getItem(PAYMENT_RECEIPT_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;

  const { token, ts } = parsed;
  if (typeof token !== 'string' || !token) return null;
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return null;
  if (now - ts > PAYMENT_RECEIPT_MAX_AGE_MS) return null;
  return { token };
}

/** Drop the parked receipt once it has been consumed (payment confirmed). */
export function clearPaymentReceipt() {
  const store = safeSession();
  if (!store) return;
  try {
    store.removeItem(PAYMENT_RECEIPT_KEY);
  } catch {
    /* nothing to do */
  }
}
