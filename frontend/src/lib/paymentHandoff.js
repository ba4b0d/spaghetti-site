/**
 * Token-free gateway hand-off transport.
 *
 * WHY THIS EXISTS
 * The private invoice page lives at ``/pay/<token>`` — the path segment IS a
 * bearer credential — so nginx serves that document (and the hook mounted on
 * it) with ``Referrer-Policy: no-referrer``. When the browser navigated to the
 * BitPay portal straight from that document it therefore sent NO ``Referer``,
 * and the portal rejected the hand-off with «آدرس ارجاعی نامعتبر» (invalid
 * referer address).
 *
 * THE HAND-OFF
 * Instead of navigating to the portal from the no-referrer document, the pay
 * page parks the *validated* portal URL here (per-tab ``sessionStorage``) and
 * hard-navigates the browser to the token-free same-origin page
 * ``/pay/redirect``. That page is served with an origin-only referrer policy,
 * re-validates the parked URL and navigates on — so the browser emits
 * ``Referer: https://spaghettiprints.ir/`` (origin only), which is exactly
 * what BitPay requires.
 *
 * The bearer token never enters this module: only the already-validated gateway
 * URL and its provider name are stored, and never as a URL/query parameter, so
 * nothing sensitive lands in history, a Referer or an access log.
 */

export const GATEWAY_HANDOFF_KEY = 'spaghetti:payment:gateway-handoff';

/** The token-free same-origin intermediate page (see nginx.conf). */
export const GATEWAY_HANDOFF_PATH = '/pay/redirect';

/** A parked hand-off older than this is discarded (fail closed). */
export const GATEWAY_HANDOFF_MAX_AGE_MS = 5 * 60 * 1000;

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
 * Park a validated gateway URL for the intermediate page.
 * Returns false when storage is unavailable — the caller must then take the
 * direct (degraded) path rather than stranding the customer.
 */
export function writeGatewayHandoff(url, provider) {
  const store = safeSession();
  if (!store) return false;
  try {
    store.setItem(GATEWAY_HANDOFF_KEY, JSON.stringify({ url, provider, ts: Date.now() }));
    return true;
  } catch {
    return false;
  }
}

/**
 * Read and structurally validate the parked hand-off.
 * Returns ``{ url, provider }`` or ``null``. It does NOT validate the URL
 * against a provider allowlist — the caller must pass ``url``/``provider``
 * through ``validateGatewayUrl`` before navigating.
 */
export function readGatewayHandoff(now = Date.now()) {
  const store = safeSession();
  if (!store) return null;
  let raw;
  try {
    raw = store.getItem(GATEWAY_HANDOFF_KEY);
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
  const { url, provider, ts } = parsed;
  if (typeof url !== 'string' || typeof provider !== 'string') return null;
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return null;
  if (now - ts > GATEWAY_HANDOFF_MAX_AGE_MS) return null;
  return { url, provider };
}

/** Drop the parked hand-off so a refresh cannot replay the navigation. */
export function clearGatewayHandoff() {
  const store = safeSession();
  if (!store) return;
  try {
    store.removeItem(GATEWAY_HANDOFF_KEY);
  } catch {
    /* nothing to do */
  }
}

/**
 * Build the anchor used to leave for the portal, carrying an explicit
 * ``referrerpolicy="origin"``. The attribute overrides the document's policy
 * for THIS navigation (defence in depth: it holds even if the page were ever
 * served without the origin-only header), and ``origin`` emits scheme+host+port
 * only — never the path, query, fragment or any token.
 *
 * A ``rel="noreferrer"`` (or a no-referrer policy) must NOT be used here: it
 * would strip the very Referer BitPay requires.
 */
export function buildGatewayAnchor(url) {
  const anchor = document.createElement('a');
  anchor.setAttribute('href', url);
  anchor.setAttribute('referrerpolicy', 'origin');
  anchor.style.display = 'none';
  return anchor;
}

/** Navigate the current tab to ``url`` with an origin-only Referer. */
export function navigateWithOriginReferrer(url) {
  if (typeof document === 'undefined' || !document.body) return;
  const anchor = buildGatewayAnchor(url);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
