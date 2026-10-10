// @vitest-environment node
//
// Config-level test for frontend/nginx.conf's token-bearing payment route.
//
// The /pay/<token> URL embeds a private bearer token, so the served document
// must (a) never let the token escape via a Referer header, (b) never be
// cached, and (c) never be routed to the upstream meta-preview handler that
// echoes the raw URI back in og:url/canonical. These are properties of the
// nginx config, not of the React code, so they are asserted here against the
// real config file rather than mocked.
//
// Why a hand-rolled parser + location matcher instead of a trivial
// `toContain`: the same directives appear at several levels, nginx's
// `add_header` inheritance is positional, and — the whole point of this file —
// nginx location SELECTION has non-obvious precedence (exact > longest `^~`
// prefix > first regex > longest plain prefix) and prefix matching is
// CASE-SENSITIVE. React Router v7 matches the same routes case-insensitively,
// so a naive `^~ /pay/` prefix left /PAY/<token> and /Pay/<token> falling
// through to `location /` (losing no-referrer/no-store AND hitting the
// meta-preview echo). This test models nginx's algorithm and proves every case
// variant is captured.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const CONF_PATH = new URL('../../nginx.conf', import.meta.url);
// Normalise CRLF so the parser behaves the same on a Windows checkout
// (core.autocrlf=true) as on the LF Linux CI runner.
const RAW = readFileSync(CONF_PATH, 'utf8').replace(/\r\n?/g, '\n');

const stripComments = (text) =>
  text
    .split('\n')
    .map((line) => line.replace(/#.*$/, ''))
    .join('\n');

const CONF = stripComments(RAW);

/** Split an nginx location selector into { type, target }. */
function classify(selector) {
  if (/^=\s*/.test(selector)) return { type: '=', target: selector.replace(/^=\s*/, '').trim() };
  if (/^\^~\s*/.test(selector)) return { type: '^~', target: selector.replace(/^\^~\s*/, '').trim() };
  if (/^~\*\s*/.test(selector)) return { type: '~*', target: selector.replace(/^~\*\s*/, '').trim() };
  if (/^~\s*/.test(selector)) return { type: '~', target: selector.replace(/^~\s*/, '').trim() };
  return { type: 'prefix', target: selector.trim() };
}

/** Extract every `location <selector> { ... }` block (locations never nest). */
function parseLocations(text) {
  const locations = [];
  const re = /location\s+([^{;]+?)\s*\{/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const selector = m[1].trim();
    let depth = 1;
    let i = re.lastIndex;
    for (; i < text.length && depth > 0; i += 1) {
      if (text[i] === '{') depth += 1;
      else if (text[i] === '}') depth -= 1;
    }
    locations.push({
      selector,
      body: text.slice(re.lastIndex, i - 1),
      ...classify(selector),
    });
    re.lastIndex = i;
  }
  return locations;
}

/**
 * Model nginx server-level location selection:
 *   1. exact (`=`) wins outright;
 *   2. otherwise remember the LONGEST matching prefix (`^~` or plain);
 *      if that longest prefix is `^~`, it wins and regexes are skipped;
 *   3. otherwise the FIRST matching regex (`~` case-sensitive, `~*` insens.)
 *      wins;
 *   4. if no regex matches, the longest prefix wins (here: `location /`).
 * Prefix matching is case-sensitive on the Linux runtime.
 */
function matchLocation(locations, uri) {
  const exact = locations.find((l) => l.type === '=' && l.target === uri);
  if (exact) return exact;

  let bestPrefix = null;
  for (const l of locations) {
    if ((l.type === '^~' || l.type === 'prefix') && uri.startsWith(l.target)) {
      if (!bestPrefix || l.target.length > bestPrefix.target.length) bestPrefix = l;
    }
  }
  if (bestPrefix && bestPrefix.type === '^~') return bestPrefix;

  for (const l of locations) {
    if (l.type === '~' || l.type === '~*') {
      const re = new RegExp(l.target, l.type === '~*' ? 'i' : '');
      if (re.test(uri)) return l;
    }
  }
  return bestPrefix;
}

/** add_header directives declared directly in one block body. */
function addHeaders(body) {
  const out = [];
  const re = /add_header\s+(?:"([^"]+)"|'([^']+)'|([^\s;]+))\s+(?:"([^"]*)"|'([^']*)'|([^;]+?))(\s+always)?\s*;/g;
  let m;
  while ((m = re.exec(body)) !== null) {
    out.push({
      name: m[1] ?? m[2] ?? m[3],
      value: (m[4] ?? m[5] ?? m[6] ?? '').trim(),
      always: Boolean(m[7]),
    });
  }
  return out;
}

const headerValue = (headers, name) => {
  const hit = headers.find((h) => h.name.toLowerCase() === name.toLowerCase());
  return hit ? hit.value : undefined;
};

const locations = parseLocations(CONF);
const payLocations = locations.filter(
  (l) => (l.type === '^~' || l.type === 'prefix' || l.type === '~' || l.type === '~*') &&
         /^\^?\/pay\//i.test(l.target)
);
const payLocation = payLocations[0];
const rootLocation = locations.find((l) => l.type === 'prefix' && l.target === '/');
const staticLocation = locations.find((l) => l.type === '~*' && /\\\.\(/.test(l.target));
const htmlLocation = locations.find((l) => l.type === '~*' && /\\\.html\$/.test(l.target));

// Every case variant of the payment prefix that must resolve to the hardened
// pay location (both the token page and the token-free result page).
const PAY_URIS = [
  '/pay/abc123token',
  '/PAY/abc123token',
  '/Pay/abc123token',
  '/pAy/abc123token',
  '/pay/result',
  '/PAY/result',
  '/Pay/Result',
];
const BOT_UA = 'TelegramBot/1.0';

// Server-level security headers, i.e. the directives declared outside every
// location (top of the server block). Asserted to be replicated in /pay/.
const SERVER_SECURITY_HEADERS = [
  ['X-Content-Type-Options', 'nosniff'],
  ['X-Frame-Options', 'SAMEORIGIN'],
  ['Permissions-Policy', 'camera=(), microphone=(), geolocation=()'],
];

describe('nginx location matcher faithfully models nginx precedence', () => {
  // Sanity: if these fail the rest of the file is meaningless.
  const prefixOnly = [
    { type: '^~', target: '/pay/', selector: '^~ /pay/', body: '' },
    { type: 'prefix', target: '/', selector: '/', body: '' },
  ];
  const withRegex = [
    { type: '~*', target: '^/pay/', selector: '~* ^/pay/', body: '' },
    { type: 'prefix', target: '/', selector: '/', body: '' },
  ];
  it('treats prefix matching as case-SENSITIVE (the original bug)', () => {
    expect(matchLocation(prefixOnly, '/pay/x').selector).toBe('^~ /pay/');
    // /PAY/ does not match the case-sensitive prefix, so it falls to `/`.
    expect(matchLocation(prefixOnly, '/PAY/x').selector).toBe('/');
  });
  it('treats `~*` regexes as case-INSENSITIVE and checks them before `/`', () => {
    expect(matchLocation(withRegex, '/PAY/x').selector).toBe('~* ^/pay/');
    expect(matchLocation(withRegex, '/pay/x').selector).toBe('~* ^/pay/');
  });
});

describe('frontend/nginx.conf — token-bearing /pay/ route', () => {
  it('matches the pay route with a case-insensitive regex (not a case-sensitive prefix)', () => {
    expect(payLocations.length, 'no pay location found').toBeGreaterThan(0);
    expect(payLocation.type, 'pay location must be a case-insensitive regex').toBe('~*');
    expect(payLocation.target).toMatch(/^\^\/pay\//);
    // No `^~ /pay/` (case-sensitive-only) prefix may remain: it would open the
    // /PAY/ and /Pay/ bypass again.
    expect(
      locations.some((l) => l.type === '^~' && l.target === '/pay/'),
      'stale case-sensitive `^~ /pay/` prefix still present'
    ).toBe(false);
  });

  it('places the pay regex before the static-asset regex (so /pay/*.js cannot slip through)', () => {
    const payIdx = locations.indexOf(payLocation);
    const staticIdx = locations.indexOf(staticLocation);
    expect(payIdx).toBeGreaterThanOrEqual(0);
    expect(staticIdx).toBeGreaterThan(payIdx);
  });

  it.each(PAY_URIS)('routes %s to the hardened pay location (browser)', (uri) => {
    const hit = matchLocation(locations, uri);
    expect(hit, `no location matched ${uri}`).toBeTruthy();
    expect(hit.type, `${uri} matched a case-sensitive/insecure location`).toBe('~*');
    expect(hit.target).toMatch(/^\^\/pay\//);
    // Hardening must travel with the location that actually serves the URI.
    expect(headerValue(addHeaders(hit.body), 'Referrer-Policy')).toBe('no-referrer');
    const cc = headerValue(addHeaders(hit.body), 'Cache-Control');
    expect(cc).toBeTruthy();
    expect(cc.toLowerCase()).toContain('no-store');
  });

  it.each(PAY_URIS)('never sends %s to the bot meta-preview branch', (uri) => {
    // UA only matters inside `location /`; the pay location must win first so
    // the requested $uri (the token) is never echoed by meta-preview.
    const hit = matchLocation(locations, uri);
    expect(hit).not.toBe(rootLocation);
    expect(hit.body).not.toMatch(/meta-preview/);
    expect(hit.body).not.toMatch(/proxy_pass/);
    expect(hit.body).not.toMatch(/TelegramBot/);
    // The crawler UA is asserted here so the intent (bot traffic) is explicit.
    expect(BOT_UA).toMatch(/TelegramBot/);
  });

  it('restates every server-level security header (add_header does not inherit)', () => {
    const headers = addHeaders(payLocation.body);
    for (const [name, value] of SERVER_SECURITY_HEADERS) {
      expect(headerValue(headers, name), `${name} missing in /pay/ location`).toBe(value);
    }
    // CSP is long; compare against the server-level value verbatim.
    const serverCsp = headerValue(addHeaders(CONF), 'Content-Security-Policy');
    expect(serverCsp, 'server-level CSP not found').toBeTruthy();
    expect(headerValue(headers, 'Content-Security-Policy')).toBe(serverCsp);
  });

  it('keeps the SPA fallback to /index.html so deep links and refresh work', () => {
    // try_files' own fallback re-matches `location ~* \.html$` and would drop
    // the headers set above, so an equivalent `rewrite ... break` is accepted.
    const spaFallback =
      /try_files[^;]*\/index\.html/.test(payLocation.body) ||
      /rewrite\s+\S+\s+\/index\.html\s+break/.test(payLocation.body);
    expect(spaFallback).toBe(true);
  });

  it('does not weaken the global policy for other routes', () => {
    // Other SPAs keep the looser cross-origin policy; only /pay/ is tightened.
    expect(headerValue(addHeaders(CONF), 'Referrer-Policy')).toBe(
      'strict-origin-when-cross-origin'
    );
    // The HTML rule still disables caching for the SPA entry point.
    expect(headerValue(addHeaders(htmlLocation.body), 'Cache-Control')).toContain('no-store');
  });

  it('preserves the other server routes', () => {
    expect(locations.some((l) => l.type === '^~' && l.target === '/api/')).toBe(true);
    expect(locations.some((l) => l.type === '^~' && l.target === '/uploads/')).toBe(true);
    expect(locations.some((l) => l.type === '=' && l.target === '/sw.js')).toBe(true);

    // A normal SPA route still falls through to `location /` (unchanged), and
    // the bot branch still lives there for non-payment routes.
    expect(matchLocation(locations, '/catalog/xyz')).toBe(rootLocation);
    expect(rootLocation.body).toMatch(/TelegramBot/);
    expect(rootLocation.body).toMatch(/meta-preview/);

    // Static assets still hit the immutable-cache branch.
    const asset = matchLocation(locations, '/assets/index-abc123.js');
    expect(asset).toBe(staticLocation);
    expect(headerValue(addHeaders(staticLocation.body), 'Cache-Control')).toBe('public, immutable');
  });

  it('has balanced braces (cheap syntax guard before nginx -t runs in the image)', () => {
    const opens = (CONF.match(/\{/g) || []).length;
    const closes = (CONF.match(/\}/g) || []).length;
    expect(opens).toBe(closes);
  });
});

// ── Two-tier trusted edge: realip recovery of the true client IP ──────────
// Production path: client → Pi5 edge reverse proxy (192.168.100.50) → this
// nginx → backend. The edge replaces X-Forwarded-For with the real client, but
// the peer THIS nginx sees is the edge, so plain $remote_addr is the edge's own
// address for every visitor and the backend's rate-limit key collapses to one
// shared bucket. realip rewrites $remote_addr from X-Forwarded-For, but ONLY
// when the immediate peer is trusted. We trust exactly the one edge address
// (never a range, never `*`), and keep forwarding the recovered $remote_addr —
// never a client-supplied chain.
describe('frontend/nginx.conf — two-tier trusted edge (realip)', () => {
  const serverLevel = CONF.slice(0, CONF.indexOf('location '));
  const realIpFrom = (CONF.match(/set_real_ip_from\s+\S+;/g) || []).map((s) =>
    s.replace(/set_real_ip_from\s+/, '').replace(/;$/, '')
  );

  it('trusts exactly the Pi edge address, and only it', () => {
    expect(realIpFrom).toEqual(['192.168.100.50']);
    // No wildcard / range trust that would let a direct caller spoof its IP.
    expect(CONF).not.toMatch(/set_real_ip_from\s+(all|\*|0\.0\.0\.0\/0|::\/0)/);
  });

  it('recovers the client from X-Forwarded-For, recursively', () => {
    expect(serverLevel).toMatch(/real_ip_header\s+X-Forwarded-For;/);
    expect(serverLevel).toMatch(/real_ip_recursive\s+on;/);
  });

  it('forwards the recovered $remote_addr and never a client-supplied chain', () => {
    expect(CONF).toMatch(/proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;/);
    expect(CONF).not.toMatch(/proxy_set_header\s+X-Forwarded-For\s+\$proxy_add_x_forwarded_for;/);
    expect(CONF).not.toMatch(/proxy_set_header\s+X-Forwarded-For\s+\$http_x_forwarded_for;/);
    expect(CONF).toMatch(/proxy_set_header\s+X-Real-IP\s+\$remote_addr;/);
  });

  it('configures realip server-wide, before $remote_addr is forwarded', () => {
    expect(serverLevel).toMatch(/set_real_ip_from/);
    const headerIdx = CONF.indexOf('real_ip_header X-Forwarded-For;');
    expect(headerIdx).toBeGreaterThanOrEqual(0);
    expect(headerIdx).toBeLessThan(
      CONF.indexOf('proxy_set_header X-Forwarded-For $remote_addr;')
    );
  });
});
