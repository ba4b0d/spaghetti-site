/**
 * Persistent storefront cart.
 *
 * The cart deliberately stores ONLY product ids and quantities — never prices,
 * names or any other catalogue data. Prices are resolved server-side at
 * request-intake time; the browser cart is not an authoritative price source.
 */

export const CART_STORAGE_KEY = 'spaghetti_cart_v1';
export const MAX_QTY = 99;

const listeners = new Set();

function notify() {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      /* a broken listener must never break the cart */
    }
  }
}

function storage() {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function sanitize(rawItems) {
  if (!Array.isArray(rawItems)) return [];
  const seen = new Set();
  const clean = [];
  for (const entry of rawItems) {
    const id = Number(entry?.id);
    const qty = Number(entry?.qty);
    if (!Number.isInteger(id) || id <= 0) continue;
    if (!Number.isInteger(qty) || qty < 1) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    clean.push({ id, qty: Math.min(qty, MAX_QTY) });
  }
  return clean;
}

/** Read the persisted cart. Always returns a fresh, sanitized array. */
export function readCart() {
  const store = storage();
  if (!store) return [];
  try {
    return sanitize(JSON.parse(store.getItem(CART_STORAGE_KEY) || '[]'));
  } catch {
    return [];
  }
}

function writeCart(items) {
  const clean = sanitize(items);
  const store = storage();
  if (store) {
    try {
      store.setItem(CART_STORAGE_KEY, JSON.stringify(clean));
    } catch {
      /* storage full/blocked — keep the in-memory result */
    }
  }
  notify();
  return clean;
}

/** Add `qty` of a product, merging into an existing line (capped at MAX_QTY). */
export function addItem(id, qty = 1) {
  const productId = Number(id);
  const amount = Number(qty);
  if (!Number.isInteger(productId) || productId <= 0) return readCart();
  if (!Number.isInteger(amount) || amount < 1) return readCart();

  const items = readCart();
  const existing = items.find((item) => item.id === productId);
  if (existing) {
    existing.qty = Math.min(existing.qty + amount, MAX_QTY);
  } else {
    items.push({ id: productId, qty: Math.min(amount, MAX_QTY) });
  }
  return writeCart(items);
}

/** Set an absolute quantity; quantities <= 0 remove the line entirely. */
export function updateQuantity(id, qty) {
  const productId = Number(id);
  const amount = Number(qty);
  const items = readCart();
  const existing = items.find((item) => item.id === productId);
  if (!existing) return items;

  if (!Number.isInteger(amount) || amount <= 0) {
    return writeCart(items.filter((item) => item.id !== productId));
  }
  existing.qty = Math.min(amount, MAX_QTY);
  return writeCart(items);
}

export function removeItem(id) {
  const productId = Number(id);
  return writeCart(readCart().filter((item) => item.id !== productId));
}

export function clearCart() {
  return writeCart([]);
}

/** Total number of units in the cart. */
export function cartCount(items = readCart()) {
  return items.reduce((sum, item) => sum + item.qty, 0);
}

/** Subscribe to cart mutations. Returns an unsubscribe function. */
export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
