import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Mock the public HTTP layers: the checkout page talks to commerceApi for the
// request and to the catalog API only to resolve display names (never prices
// as authoritative values).
const commerceApiMock = vi.hoisted(() => ({
  submitCommerceRequest: vi.fn(),
  requestOtp: vi.fn(),
}));
const catalogApiMock = vi.hoisted(() => ({ getCatalog: vi.fn() }));

vi.mock('../lib/commerceApi', () => commerceApiMock);
vi.mock('../lib/api', () => ({
  getCatalog: catalogApiMock.getCatalog,
  getCatalogProduct: vi.fn(),
}));

import * as cart from '../lib/cart';
import { formatPrice } from '../lib/utils';
import CheckoutRequest from '../pages/CheckoutRequest';

const CART_KEY = 'spaghetti_cart_v1';

function renderCheckout() {
  return render(
    <MemoryRouter>
      <CheckoutRequest />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  catalogApiMock.getCatalog.mockResolvedValue({
    data: [{ id: 12, name: 'جاکلیدی تستی', final_price: 30000, slug: 'test-keychain' }],
  });
  commerceApiMock.requestOtp.mockResolvedValue({
    data: {
      challenge_id: 7,
      expires_in: 120,
      resend_after: 2,
      delivery: 'sms',
      masked_mobile: '0912***6789',
    },
  });
});

// ── Item 3: the cart is gated behind an SMS one-time code ────────────
// Every test that submits the cart must first open the OTP step and confirm a
// code; the request is only minted on confirm.
async function submitCartThroughOtp() {
  fireEvent.click(screen.getByRole('button', { name: 'ثبت درخواست' }));
  await screen.findByTestId('checkout-otp-step');
  fireEvent.change(screen.getByLabelText('کد تأیید'), { target: { value: '12345' } });
  fireEvent.click(screen.getByRole('button', { name: 'تأیید و ثبت درخواست' }));
}

// ── cart.js ──────────────────────────────────────────────────────────

describe('cart persistence', () => {
  it('adds an item and reads it back', () => {
    cart.addItem(7, 1);
    expect(cart.readCart()).toEqual([{ id: 7, qty: 1 }]);
  });

  it('merges quantity for an existing product', () => {
    cart.addItem(7, 1);
    cart.addItem(7, 2);
    expect(cart.readCart()).toEqual([{ id: 7, qty: 3 }]);
  });

  it('caps quantity at 99', () => {
    cart.addItem(7, 90);
    cart.addItem(7, 90);
    expect(cart.readCart()).toEqual([{ id: 7, qty: 99 }]);
  });

  it('updates quantity and removes an item', () => {
    cart.addItem(1, 1);
    cart.addItem(2, 1);

    cart.updateQuantity(1, 5);
    expect(cart.readCart()).toEqual([{ id: 1, qty: 5 }, { id: 2, qty: 1 }]);

    cart.removeItem(1);
    expect(cart.readCart()).toEqual([{ id: 2, qty: 1 }]);
  });

  it('drops the item when quantity drops to zero or below', () => {
    cart.addItem(3, 2);
    cart.updateQuantity(3, 0);
    expect(cart.readCart()).toEqual([]);
  });

  it('persists only product ids and quantities', () => {
    cart.addItem(4, 2);
    const raw = window.localStorage.getItem(CART_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw);
    expect(parsed).toEqual([{ id: 4, qty: 2 }]);
    expect(Object.keys(parsed[0]).sort()).toEqual(['id', 'qty']);
  });

  it('reloads from localStorage in a fresh module instance', async () => {
    cart.addItem(11, 3);
    vi.resetModules();
    const reloaded = await import('../lib/cart');
    expect(reloaded.readCart()).toEqual([{ id: 11, qty: 3 }]);
  });

  it('ignores corrupt localStorage payloads', () => {
    window.localStorage.setItem(CART_KEY, '{not json');
    expect(cart.readCart()).toEqual([]);

    window.localStorage.setItem(CART_KEY, JSON.stringify([{ id: 'x', qty: 'nope' }]));
    expect(cart.readCart()).toEqual([]);
  });

  it('clears the cart', () => {
    cart.addItem(1, 1);
    cart.clearCart();
    expect(cart.readCart()).toEqual([]);
  });
});

// ── CheckoutRequest page ─────────────────────────────────────────────

describe('CheckoutRequest', () => {
  it('shows an empty-cart state without a cart', async () => {
    renderCheckout();
    expect(await screen.findByText(/سبد خرید خالی/)).toBeDefined();
  });

  it('submits the cart with contact details and shows the receipt', async () => {
    cart.addItem(12, 2);
    commerceApiMock.submitCommerceRequest.mockResolvedValue({
      data: { receipt_id: 'REQ-ABC123', state: 'pending_review' },
    });

    renderCheckout();
    expect(await screen.findByText(/جاکلیدی تستی/)).toBeDefined();

    fireEvent.change(screen.getByLabelText('نام و نام خانوادگی'), { target: { value: 'رضا' } });
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '09123456789' } });
    fireEvent.change(screen.getByLabelText('پیامرسان'), { target: { value: 'telegram' } });

    // Item 3: the request is only minted after the SMS code is confirmed.
    await submitCartThroughOtp();

    await waitFor(() => expect(commerceApiMock.submitCommerceRequest).toHaveBeenCalledTimes(1));
    const payload = commerceApiMock.submitCommerceRequest.mock.calls[0][0];
    expect(payload.customer_name).toBe('رضا');
    expect(payload.mobile).toBe('09123456789');
    expect(payload.messenger).toBe('telegram');
    expect(payload.items).toEqual([{ product_id: 12, qty: 2 }]);
    // The cart is not an authoritative price source.
    expect(Object.keys(payload).sort()).toEqual(
      ['customer_name', 'items', 'messenger', 'mobile', 'otp_challenge_id', 'otp_code'].sort()
    );

    expect(await screen.findByText(/REQ-ABC123/)).toBeDefined();
    // Cart cleared only after a successful request.
    expect(cart.readCart()).toEqual([]);
  });

  it('keeps the cart and shows the server error on failure', async () => {
    cart.addItem(12, 2);
    commerceApiMock.submitCommerceRequest.mockRejectedValue({
      response: { data: { detail: 'برخی محصولات موجود یا فعال نیستند' } },
    });

    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);

    fireEvent.change(screen.getByLabelText('نام و نام خانوادگی'), { target: { value: 'رضا' } });
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '09123456789' } });
    // Item 3: reach the server only through a confirmed OTP step.
    await submitCartThroughOtp();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('برخی محصولات موجود یا فعال نیستند');
    expect(cart.readCart()).toEqual([{ id: 12, qty: 2 }]);
  });
});

// ── estimated cart total (item 4) ────────────────────────────────────

describe('CheckoutRequest estimated total', () => {
  it('shows the indicative total as qty × catalogue price, clearly labelled as an estimate', async () => {
    cart.addItem(12, 2);
    renderCheckout();

    await screen.findByText(/جاکلیدی تستی/);

    expect(await screen.findByText('تخمین قیمت')).toBeDefined();
    const total = await screen.findByTestId('checkout-estimated-total');
    // 2 × 30,000 = 60,000, formatted with the project's Toman formatter.
    expect(total.textContent).toBe(formatPrice(60000));
  });

  it('falls back gracefully and never fabricates a number when the product has no price', async () => {
    catalogApiMock.getCatalog.mockResolvedValue({
      data: [{ id: 12, name: 'جاکلیدی بی‌قیمت', final_price: null, slug: 'no-price-keychain' }],
    });
    cart.addItem(12, 1);
    renderCheckout();

    await screen.findByText(/جاکلیدی بی‌قیمت/);

    const total = await screen.findByTestId('checkout-estimated-total');
    expect(total.textContent).toBe('قیمت تماس بگیرید');
  });

  it('never sends a price in the request payload', async () => {
    cart.addItem(12, 2);
    commerceApiMock.submitCommerceRequest.mockResolvedValue({
      data: { receipt_id: 'REQ-XYZ', state: 'pending_review' },
    });
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);

    fireEvent.change(screen.getByLabelText('نام و نام خانوادگی'), { target: { value: 'رضا' } });
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '09123456789' } });
    // Item 3: reach the server only through a confirmed OTP step.
    await submitCartThroughOtp();

    await waitFor(() => expect(commerceApiMock.submitCommerceRequest).toHaveBeenCalledTimes(1));
    const payload = commerceApiMock.submitCommerceRequest.mock.calls[0][0];
    expect(Object.keys(payload).sort()).toEqual(
      ['customer_name', 'items', 'messenger', 'mobile', 'otp_challenge_id', 'otp_code'].sort()
    );
    expect(payload.items).toEqual([{ product_id: 12, qty: 2 }]);
    expect(JSON.stringify(payload)).not.toContain('60000');
  });
});
