// @vitest-environment node
//
// Behavioural tests for frontend/public/sw.js.
//
// WHAT THIS PINS
// The private invoice page lives at /pay/<token> — the path segment IS a bearer
// credential — and nginx serves it `Cache-Control: no-store`. The service
// worker must honour that *independently of response headers*: a cached copy of
// a private payment page would survive on disk and be re-served after the token
// was revoked or expired. So EVERY /pay/… request (case-insensitive, in every
// variant React Router accepts) must be excluded from the cache and always go
// to the network — never cached, never served from cache, not even offline.
//
// It also pins the REPAIR path: a client that already cached a /pay page under
// an older worker must have those entries purged as soon as this worker installs
// /activates, and superseded caches must be dropped.
//
// HOW
// sw.js is a classic script that talks to `self`, `caches` and `fetch`. Rather
// than mock the module in place, we execute the REAL file inside a fresh V8
// context (node:vm) with a fake CacheStorage, capture the registered listeners
// and drive them, so the tests exercise the shipped worker verbatim.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SW_SRC = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8');
const MAIN_SRC = readFileSync(new URL('../../src/main.jsx', import.meta.url), 'utf8');

// Read CACHE_NAME straight from the worker so the tests never hard-code it.
const CACHE_NAME = (() => {
  const m = /const\s+CACHE_NAME\s*=\s*'([^']+)'/.exec(SW_SRC);
  if (!m) throw new Error('could not read CACHE_NAME from sw.js');
  return m[1];
})();

const ORIGIN = 'https://spaghettiprints.ir';

const keyOf = (req) => (typeof req === 'string' ? req : req.url);

function makeResponse(body = 'ok') {
  return {
    ok: true,
    status: 200,
    body,
    clone() {
      return makeResponse(body);
    },
    async text() {
      return body;
    },
  };
}

/** A minimal in-memory CacheStorage whose keys behave like real Requests. */
function createCaches() {
  const byName = new Map();
  const cacheFor = (map) => ({
    async put(req, res) {
      map.set(keyOf(req), res);
    },
    async match(req) {
      return map.get(keyOf(req));
    },
    async addAll(urls) {
      for (const url of urls) map.set(keyOf(url), makeResponse(url));
    },
    async keys() {
      return [...map.keys()].map((url) => ({ url }));
    },
    async delete(req) {
      return map.delete(keyOf(req));
    },
  });

  const caches = {
    async open(name) {
      if (!byName.has(name)) byName.set(name, new Map());
      return cacheFor(byName.get(name));
    },
    async keys() {
      return [...byName.keys()];
    },
    async delete(name) {
      return byName.delete(name);
    },
    async match(req) {
      const key = keyOf(req);
      for (const map of byName.values()) if (map.has(key)) return map.get(key);
      return undefined;
    },
  };

  return {
    caches,
    preload(name, url, res = makeResponse(url)) {
      if (!byName.has(name)) byName.set(name, new Map());
      byName.get(name).set(url, res);
      return res;
    },
    get(name, url) {
      return byName.get(name)?.get(url);
    },
    names() {
      return [...byName.keys()];
    },
    entries() {
      const out = [];
      for (const [name, map] of byName) for (const url of map.keys()) out.push({ name, url });
      return out;
    },
  };
}

/** Execute the real sw.js in a fresh context and return its listeners. */
function loadSW({ fetchImpl } = {}) {
  const harness = createCaches();
  const listeners = {};
  const fetchCalls = [];
  const self = {
    addEventListener: (type, cb) => {
      (listeners[type] ||= []).push(cb);
    },
    skipWaiting: () => {},
    clients: { claim: () => {} },
    location: { origin: ORIGIN },
  };
  const fetchMock = async (req) => {
    fetchCalls.push(keyOf(req));
    return fetchImpl ? fetchImpl(req) : makeResponse('net:' + keyOf(req));
  };

  const context = { self, caches: harness.caches, fetch: fetchMock, URL, console };
  vm.createContext(context);
  vm.runInContext(SW_SRC, context);

  return { listeners, harness, fetchCalls };
}

/** Fire an install/activate event and await everything it deferred. */
function runWaitUntil(listeners, type) {
  const waits = [];
  const event = { waitUntil: (p) => waits.push(p) };
  for (const cb of listeners[type] || []) cb(event);
  return Promise.all(waits);
}

/** Fire a fetch event; `responded` is set only if the worker called respondWith. */
function dispatchFetch(listeners, request) {
  let responded;
  const event = { request, respondWith: (value) => (responded = value) };
  for (const cb of listeners.fetch || []) cb(event);
  return { responded };
}

const nav = (path, extra = {}) => ({
  url: ORIGIN + path,
  method: 'GET',
  mode: 'navigate',
  destination: 'document',
  ...extra,
});

describe('sw.js — cache name stays in step with the registration', () => {
  it('registers the worker under a cache-busting version matching CACHE_NAME', () => {
    const m = /serviceWorker\.register\(\s*'\/sw\.js\?v=(\d+)'/.exec(MAIN_SRC);
    expect(m, 'no serviceWorker.register("/sw.js?v=N") found in main.jsx').toBeTruthy();
    expect(`spaghetti-v${m[1]}`).toBe(CACHE_NAME);
  });
});

describe('sw.js — private bearer payment pages are never cached', () => {
  // Every case variant React Router accepts, plus the token-free siblings that
  // live under the same private family.
  const PAY_PATHS = [
    '/pay/rawtoken',
    '/PAY/rawtoken',
    '/Pay/RawToken',
    '/pAy/x',
    '/PAY/x',
    '/pay/result',
    '/pay/redirect',
    '/pay',
  ];

  it.each([...PAY_PATHS, '/pay/token?x=1', '/PAY/Token#frag'])(
    'hands %s straight to the network without intercepting or caching it',
    (path) => {
      const { listeners, harness } = loadSW();
      const { responded } = dispatchFetch(listeners, nav(path));

      // No respondWith ⇒ the browser performs its own (never cached) fetch.
      expect(responded).toBeUndefined();
      // And the worker wrote nothing at all.
      expect(harness.entries()).toEqual([]);
    }
  );

  it('never serves a cached copy of a payment page even when one is already stored', () => {
    const { listeners, harness } = loadSW();
    const url = ORIGIN + '/pay/leaked-token';
    harness.preload(CACHE_NAME, url, makeResponse('cached secret'));

    const { responded } = dispatchFetch(listeners, nav('/pay/leaked-token'));
    expect(responded).toBeUndefined();
  });

  it('does not over-reach: ordinary navigations are still handled by the worker', () => {
    for (const path of ['/payments', '/payroll', '/catalog/pay-now', '/']) {
      const { listeners } = loadSW();
      const { responded } = dispatchFetch(listeners, nav(path));
      expect(responded, `${path} should still be intercepted`).toBeDefined();
    }
  });
});

describe('sw.js — poisoned caches are repaired on install and activate', () => {
  it('purges cached payment pages on activate and drops superseded caches', async () => {
    const { listeners, harness } = loadSW();
    const secret = ORIGIN + '/pay/secret-token';
    const secretUpper = ORIGIN + '/PAY/SecretToken';
    const asset = ORIGIN + '/assets/app-abcdef12.js';

    harness.preload(CACHE_NAME, secret, makeResponse('secret'));
    harness.preload(CACHE_NAME, secretUpper, makeResponse('secret'));
    harness.preload(CACHE_NAME, asset, makeResponse('asset'));
    harness.preload('spaghetti-v4', ORIGIN + '/pay/old-token', makeResponse('old'));

    await runWaitUntil(listeners, 'activate');

    // Only the current cache survives ...
    expect(harness.names()).toEqual([CACHE_NAME]);
    // ... and it holds no payment pages, in any case variant ...
    expect(harness.get(CACHE_NAME, secret)).toBeUndefined();
    expect(harness.get(CACHE_NAME, secretUpper)).toBeUndefined();
    // ... while ordinary assets are untouched.
    expect(harness.get(CACHE_NAME, asset)).toBeTruthy();
    expect(harness.entries().some((e) => /^\/pay(\/|$)/i.test(new URL(e.url).pathname))).toBe(false);
  });

  it('also purges cached payment pages on install (repair before activate)', async () => {
    const { listeners, harness } = loadSW();
    const secret = ORIGIN + '/pay/secret-token';
    harness.preload(CACHE_NAME, secret, makeResponse('secret'));

    await runWaitUntil(listeners, 'install');

    expect(harness.get(CACHE_NAME, secret)).toBeUndefined();
    // The shell is still cached by install.
    expect(harness.get(CACHE_NAME, '/index.html')).toBeTruthy();
  });
});

describe('sw.js — existing behaviour preserved', () => {
  it('still caches an ordinary navigation (network-first)', async () => {
    const { listeners, harness } = loadSW();
    const { responded } = dispatchFetch(listeners, nav('/catalog'));
    expect(responded).toBeDefined();
    await responded;
    expect(harness.get(CACHE_NAME, ORIGIN + '/catalog')).toBeTruthy();
  });

  it('still skips non-GET and API requests entirely', () => {
    for (const request of [
      { url: ORIGIN + '/api/v1/x', method: 'GET', mode: 'cors', destination: '' },
      { url: ORIGIN + '/uploads/a.png', method: 'GET', mode: 'no-cors', destination: 'image' },
      { url: ORIGIN + '/catalog', method: 'POST', mode: 'cors', destination: '' },
    ]) {
      const { listeners } = loadSW();
      const { responded } = dispatchFetch(listeners, request);
      expect(responded).toBeUndefined();
    }
  });
});
