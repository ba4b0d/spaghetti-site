// @vitest-environment jsdom
//
// Unit tests for the per-tab payment receipt transport.
//
// The BitPay callback 303-redirects the payer to the public, token-free page
// `/pay/result?payment=success|failed|pending`. The backend deliberately keeps
// that redirect free of the private bearer token (the token is never persisted
// server-side, and it must not be echoed into a Location header, a query, a
// Referer or a log). So the result page cannot — and must not — prove a payment
// from the query alone; it still needs the private invoice read behind the
// token to show a TRUTHFUL confirmation.
//
// The pay page (`/pay/<token>`) already knows the token and already parks the
// validated gateway URL in per-tab sessionStorage for the token-free hand-off.
// It parks the token HERE, under a dedicated key, the same way. These tests pin
// the transport's contract: it round-trips exactly the token, it is fail-closed
// on anything malformed or stale, it never throws when storage is unusable, and
// it stays separate from the gateway hand-off entry (which MUST remain
// token-free — see paymentHandoff.js).
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  PAYMENT_RECEIPT_KEY,
  PAYMENT_RECEIPT_MAX_AGE_MS,
  writePaymentReceipt,
  readPaymentReceipt,
  clearPaymentReceipt,
} from '../../lib/paymentReceipt';
import { GATEWAY_HANDOFF_KEY } from '../../lib/paymentHandoff';

const TOKEN = 'raw-BEARER-token-777';

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  window.sessionStorage.clear();
});

describe('payment receipt transport', () => {
  it('round-trips the invoice bearer token', () => {
    expect(writePaymentReceipt(TOKEN)).toBe(true);
    expect(readPaymentReceipt()).toEqual({ token: TOKEN });
  });

  it('uses a dedicated key, separate from the token-free gateway hand-off', () => {
    expect(PAYMENT_RECEIPT_KEY).not.toBe(GATEWAY_HANDOFF_KEY);
    writePaymentReceipt(TOKEN);
    // Parking the receipt must NOT populate the hand-off entry, which is
    // asserted elsewhere never to carry the token.
    expect(window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY)).toBeNull();
  });

  it('refuses a non-string or empty token instead of parking it', () => {
    expect(writePaymentReceipt('')).toBe(false);
    expect(writePaymentReceipt(null)).toBe(false);
    expect(writePaymentReceipt(undefined)).toBe(false);
    expect(writePaymentReceipt(42)).toBe(false);
    expect(readPaymentReceipt()).toBeNull();
  });

  it('returns null (fail closed) when nothing was parked', () => {
    expect(readPaymentReceipt()).toBeNull();
  });

  it('returns null (fail closed) on malformed or incomplete entries', () => {
    window.sessionStorage.setItem(PAYMENT_RECEIPT_KEY, 'not json');
    expect(readPaymentReceipt()).toBeNull();

    window.sessionStorage.setItem(PAYMENT_RECEIPT_KEY, JSON.stringify({ token: TOKEN }));
    expect(readPaymentReceipt()).toBeNull(); // missing ts

    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: 42, ts: Date.now() })
    );
    expect(readPaymentReceipt()).toBeNull(); // non-string token

    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: '', ts: Date.now() })
    );
    expect(readPaymentReceipt()).toBeNull(); // empty token

    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: TOKEN, ts: 'soon' })
    );
    expect(readPaymentReceipt()).toBeNull(); // non-numeric ts
  });

  it('ignores a receipt older than the max age (bounded lifetime)', () => {
    const now = Date.now();
    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: TOKEN, ts: now - PAYMENT_RECEIPT_MAX_AGE_MS - 1 })
    );
    expect(readPaymentReceipt(now)).toBeNull();

    // A fresh entry read with the same clock is still valid.
    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: TOKEN, ts: now })
    );
    expect(readPaymentReceipt(now)).toEqual({ token: TOKEN });
  });

  it('clears the receipt on demand (so it is not kept indefinitely)', () => {
    writePaymentReceipt(TOKEN);
    clearPaymentReceipt();
    expect(window.sessionStorage.getItem(PAYMENT_RECEIPT_KEY)).toBeNull();
    expect(readPaymentReceipt()).toBeNull();
  });

  it('never throws (and reports failure) when sessionStorage is unusable', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get: () => ({
        setItem() {
          throw new Error('storage disabled');
        },
        getItem() {
          throw new Error('storage disabled');
        },
        removeItem() {
          throw new Error('storage disabled');
        },
      }),
    });
    try {
      expect(writePaymentReceipt(TOKEN)).toBe(false);
      expect(readPaymentReceipt()).toBeNull();
      expect(() => clearPaymentReceipt()).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });
});
