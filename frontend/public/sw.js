const CACHE_NAME = 'spaghetti-v5';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
];

// The private invoice page lives at `/pay/<token>` — the path segment IS a
// bearer credential — and the server serves it `Cache-Control: no-store`. The
// worker must honour that independently of response headers: a cached copy of a
// private payment page would survive on disk and be re-served after the token
// was revoked or expired, leaking it to a later navigation.
//
// Every `/pay/…` request (case-insensitive, so /PAY/… and /Pay/… — which React
// Router matches just like nginx does — are covered too, as are the token-free
// /pay/redirect and /pay/result siblings) is therefore excluded from the cache
// entirely and always goes to the network, even while offline.
const PRIVATE_PAYMENT_PATH = /^\/pay(\/|$)/i;

const isPrivatePaymentPath = (pathname) =>
  typeof pathname === 'string' && PRIVATE_PAYMENT_PATH.test(pathname);

// The one-visit «سفارش‌های من» page at `/my-orders` is a session-ENTRY
// document: the customer proves a mobile number with an SMS code and the
// short-lived bearer lives only in that tab's sessionStorage, while the actual
// history arrives through no-store API calls. The document itself carries no
// token, but — like the /pay/… family — it must never be cached or served from
// cache: a stale/offline copy of a session-entry page must not be replayed, and
// no future change can then accidentally let a cached shell hold personal data.
// Matched case-insensitively because React Router resolves /MY-ORDERS,
// /My-Orders … just as nginx now does; `(/|$)` avoids catching lookalikes such
// as /my-orders-archive.
const PRIVATE_HISTORY_PATH = /^\/my-orders(\/|$)/i;

const isPrivateHistoryPath = (pathname) =>
  typeof pathname === 'string' && PRIVATE_HISTORY_PATH.test(pathname);

// Delete every cached entry whose URL is on the private payment path. Run on
// BOTH install and activate so a client whose older worker already poisoned its
// cache is repaired as soon as this version takes over, not just for future
// requests.
async function purgePrivatePaymentEntries() {
  const cacheNames = await caches.keys();
  await Promise.all(
    cacheNames.map(async (name) => {
      const cache = await caches.open(name);
      const requests = await cache.keys();
      await Promise.all(
        requests
          .filter((request) => {
            try {
              return isPrivatePaymentPath(new URL(request.url).pathname);
            } catch {
              return false;
            }
          })
          .map((request) => cache.delete(request))
      );
    })
  );
}

// Install: cache the shell, then repair any cached payment pages.
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(purgePrivatePaymentEntries)
  );
  self.skipWaiting();
});

// Activate: clean old caches, then repair any cached payment pages.
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
      .then(purgePrivatePaymentEntries)
  );
  self.clients.claim();
});

const networkFirst = async (request) => {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request)) || (await cache.match('/index.html'));
  }
};

const cacheFirst = async (request) => {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
  }
  return response;
};

// Fetch: fresh HTML/navigation, immutable hashed assets from cache.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip non-GET and API calls — always go network
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) {
    return;
  }

  // Private bearer-token payment routes: never cached, never served from cache.
  // Returning without respondWith hands the request to the browser's default
  // network fetch, so the /pay/<token> document is always fetched live (or the
  // request simply fails offline) and no copy of it can ever be replayed.
  if (isPrivatePaymentPath(url.pathname)) {
    return;
  }

  // One-visit history page: same rule — the session-entry document is never
  // cached and never served from cache, so the request goes to the network.
  if (isPrivateHistoryPath(url.pathname)) {
    return;
  }

  if (e.request.mode === 'navigate' || e.request.destination === 'document') {
    e.respondWith(networkFirst(e.request));
    return;
  }

  const immutableAsset = url.origin === self.location.origin
    && url.pathname.startsWith('/assets/')
    && /\.[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?|png|jpe?g|webp|svg)$/.test(url.pathname);

  if (immutableAsset) e.respondWith(cacheFirst(e.request));
});
