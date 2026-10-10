// @vitest-environment node
//
// Config-level test for frontend/nginx.conf's token-bearing payment route.
//
// The /pay/<token> URL embeds a private bearer token, so the served document
// must (a) never let the token escape via a Referer header, (b) never be
// cached, and (c) never be routed to the upstream meta-preview handler that
// echoed the raw URI back in og:url/canonical. These are properties of the
// nginx config, not of the React code, so they are asserted here against the
// real config file rather than mocked.
//
// Why a hand-rolled parser instead of a trivial `toContain`: the same
// directives appear at several levels, and nginx's `add_header` inheritance
// is positional — once a location declares any `add_header`, the server-level
// security headers are dropped for that location. The test therefore scopes
// assertions to the /pay/ location block and separately proves the server
// level still declares the baseline policy.
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
    locations.push({ selector, body: text.slice(re.lastIndex, i - 1) });
    re.lastIndex = i;
  }
  return locations;
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
const payLocation = locations.find((l) => /(^|\s)\^~\s*\/pay\//.test(` ${l.selector}`));
const rootLocation = locations.find((l) => l.selector === '/');
const htmlLocation = locations.find((l) => l.selector.includes('html'));

// Server-level security headers, i.e. the directives declared outside every
// location (top of the server block). Asserted to be replicated in /pay/.
const SERVER_SECURITY_HEADERS = [
  ['X-Content-Type-Options', 'nosniff'],
  ['X-Frame-Options', 'SAMEORIGIN'],
  ['Permissions-Policy', 'camera=(), microphone=(), geolocation=()'],
];

describe('frontend/nginx.conf — token-bearing /pay/ route', () => {
  it('is a ^~ prefix location for /pay/ (wins over `location /` and skips regex locations)', () => {
    expect(payLocation, 'no `location ^~ /pay/` block found').toBeTruthy();
    expect(payLocation.selector).toMatch(/^\^~\s*\/pay\//);

    // `^~` prefix beats the plain `location /` prefix by length and disables
    // regex matching, so a social crawler hitting /pay/<token> can never fall
    // through to the `location /` bot UA branch.
    expect(rootLocation).toBeTruthy();
    expect(rootLocation.body).toMatch(/TelegramBot/);
    expect(payLocation.body).not.toMatch(/TelegramBot/);
  });

  it('forces Referrer-Policy: no-referrer on the document response', () => {
    expect(headerValue(addHeaders(payLocation.body), 'Referrer-Policy')).toBe('no-referrer');
  });

  it('forces Cache-Control: no-store so the payment page is never cached', () => {
    const cc = headerValue(addHeaders(payLocation.body), 'Cache-Control');
    expect(cc).toBeTruthy();
    expect(cc.toLowerCase()).toContain('no-store');
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

  it('never proxies /pay/ upstream (keeps the token out of meta-preview/backend logs)', () => {
    expect(payLocation.body).not.toMatch(/proxy_pass/);
    expect(payLocation.body).not.toMatch(/meta-preview/);
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

  it('has balanced braces (cheap syntax guard before nginx -t runs in the image)', () => {
    const opens = (CONF.match(/\{/g) || []).length;
    const closes = (CONF.match(/\}/g) || []).length;
    expect(opens).toBe(closes);
  });
});
