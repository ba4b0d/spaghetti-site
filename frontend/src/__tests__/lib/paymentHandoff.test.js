// @vitest-environment jsdom
//
// Unit tests for the token-free gateway hand-off transport.
//
// The private /pay/<token> page must NOT navigate the browser straight to the
// gateway: that document is served with `Referrer-Policy: no-referrer` (the
// token is a credential in the path), so the browser sends no Referer and the
// BitPay portal rejects the hand-off with «آدرس ارجاعی نامعتبر» (invalid
// referer). Instead the validated gateway URL is parked in per-tab
// sessionStorage and the browser is sent to a token-free same-origin page that
// re-validates and navigates on with an origin-only referrer.
//
// These tests pin the transport's contract: it carries only {url, provider},
// it never persists the bearer token, it expires stale entries, and the
// navigation is performed with an explicit `referrerpolicy="origin"` so the
// Referer is the site origin and never a path or query.
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  GATEWAY_HANDOFF_KEY,
  GATEWAY_HANDOFF_PATH,
  GATEWAY_HANDOFF_MAX_AGE_MS,
  isHandoffStorageAvailable,
  writeGatewayHandoff,
  readGatewayHandoff,
  clearGatewayHandoff,
  buildGatewayAnchor,
} from '../../lib/paymentHandoff';

const TOKEN = 'raw-BEARER-token-321';
const BITPAY_OK_URL = 'https://bitpay.ir/payment/gateway-987654-get';

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  window.sessionStorage.clear();
});

describe('payment hand-off transport', () => {
  it('uses a token-free same-origin path as the intermediate page', () => {
    expect(GATEWAY_HANDOFF_PATH).toBe('/pay/redirect');
    expect(GATEWAY_HANDOFF_PATH).not.toContain(TOKEN);
  });

  it('round-trips the validated gateway URL and provider', () => {
    expect(writeGatewayHandoff(BITPAY_OK_URL, 'bitpay')).toBe(true);
    const read = readGatewayHandoff();
    expect(read).toEqual({ url: BITPAY_OK_URL, provider: 'bitpay' });
  });

  it('never persists a bearer token in the hand-off entry', () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'bitpay');
    const raw = window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY);
    expect(raw).toBeTruthy();
    expect(raw).not.toContain(TOKEN);
    expect(raw).not.toContain('raw-BEARER');
  });

  it('returns null when nothing was handed off', () => {
    expect(readGatewayHandoff()).toBeNull();
  });

  it('returns null (fail closed) on malformed or incomplete entries', () => {
    window.sessionStorage.setItem(GATEWAY_HANDOFF_KEY, 'not json');
    expect(readGatewayHandoff()).toBeNull();
    window.sessionStorage.setItem(GATEWAY_HANDOFF_KEY, JSON.stringify({ url: BITPAY_OK_URL }));
    expect(readGatewayHandoff()).toBeNull();
    window.sessionStorage.setItem(
      GATEWAY_HANDOFF_KEY,
      JSON.stringify({ url: 42, provider: 'bitpay', ts: Date.now() })
    );
    expect(readGatewayHandoff()).toBeNull();
    window.sessionStorage.setItem(
      GATEWAY_HANDOFF_KEY,
      JSON.stringify({ url: BITPAY_OK_URL, provider: null, ts: Date.now() })
    );
    expect(readGatewayHandoff()).toBeNull();
  });

  it('refuses a stale hand-off once it is older than the max age', () => {
    const now = Date.now();
    window.sessionStorage.setItem(
      GATEWAY_HANDOFF_KEY,
      JSON.stringify({
        url: BITPAY_OK_URL,
        provider: 'bitpay',
        ts: now - GATEWAY_HANDOFF_MAX_AGE_MS - 1,
      })
    );
    expect(readGatewayHandoff(now)).toBeNull();
    // A fresh entry read with the same clock is still valid.
    window.sessionStorage.setItem(
      GATEWAY_HANDOFF_KEY,
      JSON.stringify({ url: BITPAY_OK_URL, provider: 'bitpay', ts: now })
    );
    expect(readGatewayHandoff(now)).toEqual({ url: BITPAY_OK_URL, provider: 'bitpay' });
  });

  it('clears the entry so a refresh cannot re-trigger the navigation', () => {
    writeGatewayHandoff(BITPAY_OK_URL, 'bitpay');
    clearGatewayHandoff();
    expect(window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY)).toBeNull();
    expect(readGatewayHandoff()).toBeNull();
  });

  it('builds the navigation anchor with an origin-only referrer policy', () => {
    const anchor = buildGatewayAnchor(BITPAY_OK_URL);
    expect(anchor.tagName).toBe('A');
    expect(anchor.getAttribute('href')).toBe(BITPAY_OK_URL);
    // `origin` ⇒ the browser sends `Referer: https://spaghettiprints.ir/`
    // (scheme + host + port) and never the path, query, fragment or token.
    expect(anchor.getAttribute('referrerpolicy')).toBe('origin');
    // A `noreferrer`/`no-referrer` rel would strip the Referer BitPay requires.
    expect(anchor.getAttribute('rel') || '').not.toMatch(/noreferrer/i);
  });
});

describe('hand-off storage availability', () => {
  const originalDescriptor = () =>
    Object.getOwnPropertyDescriptor(window, 'sessionStorage');

  it('reports true when sessionStorage can be written, leaving no residue', () => {
    expect(isHandoffStorageAvailable()).toBe(true);
    // The probe key must be removed again.
    expect(window.sessionStorage.length).toBe(0);
  });

  it('reports false when setItem throws (locked-down private mode)', () => {
    const original = originalDescriptor();
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get: () => ({
        setItem() {
          throw new Error('storage disabled');
        },
        getItem: () => null,
        removeItem() {},
      }),
    });
    try {
      expect(isHandoffStorageAvailable()).toBe(false);
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });

  it('reports false when sessionStorage is absent', () => {
    const original = originalDescriptor();
    Object.defineProperty(window, 'sessionStorage', { configurable: true, get: () => undefined });
    try {
      expect(isHandoffStorageAvailable()).toBe(false);
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });
});
