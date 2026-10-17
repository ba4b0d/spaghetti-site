/**
 * Tab-scoped order-history session storage.
 *
 * The raw history bearer lives ONLY in ``sessionStorage`` under a single key. It
 * is never written to ``localStorage``, a cookie, an IndexedDB store, a URL or a
 * service-worker cache. ``sessionStorage`` is tab-scoped, so closing the tab
 * drops it (best effort — some browsers restore a closed tab's sessionStorage,
 * which is exactly why the server independently enforces a short absolute TTL).
 *
 * Every access is defensive: a browser that blocks storage (Safari private
 * mode, disabled cookies, a sandboxed iframe) can throw on the very property
 * access, so reads degrade to ``null`` and writes to ``false`` rather than
 * crashing the page. A malformed or expired entry is removed on read, so a
 * stale bearer is never silently reused.
 */

export const HISTORY_SESSION_KEY = 'spaghetti:history:session';

/** Normalise an expiry to epoch milliseconds; ``NaN`` when it cannot be parsed. */
function toMillis(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return NaN;
}

/** ``window.sessionStorage``, or ``null`` when it is unavailable or blocked. */
function getStore() {
  try {
    if (typeof window === 'undefined') return null;
    // Property access itself can throw when storage is disabled.
    return window.sessionStorage || null;
  } catch {
    return null;
  }
}

/**
 * Read this tab's history session, or ``null`` when there is none, it is
 * malformed, or it has already expired. A malformed/expired entry is cleared so
 * it can never be reused.
 */
export function readHistorySession() {
  const store = getStore();
  if (!store) return null;

  let raw;
  try {
    raw = store.getItem(HISTORY_SESSION_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearHistorySession();
    return null;
  }

  const token = typeof parsed?.token === 'string' ? parsed.token.trim() : '';
  const expiresAt = toMillis(parsed?.expiresAt);
  if (!token || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    clearHistorySession();
    return null;
  }
  return { token, expiresAt };
}

/**
 * Persist the session for this tab. Returns ``false`` (never throws) when the
 * token/expiry is invalid or storage is unusable, so the caller can decide.
 */
export function writeHistorySession(token, expiresAt) {
  const cleanToken = typeof token === 'string' ? token.trim() : '';
  const millis = toMillis(expiresAt);
  if (!cleanToken || !Number.isFinite(millis)) return false;

  const store = getStore();
  if (!store) return false;

  try {
    store.setItem(HISTORY_SESSION_KEY, JSON.stringify({ token: cleanToken, expiresAt: millis }));
    return true;
  } catch {
    return false;
  }
}

/** Remove this tab's session. Never throws. */
export function clearHistorySession() {
  const store = getStore();
  if (!store) return;
  try {
    store.removeItem(HISTORY_SESSION_KEY);
  } catch {
    /* nothing to clean up */
  }
}
