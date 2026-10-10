import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// The public cart OTP gate (item 3): pressing «ثبت درخواست» no longer posts the
// request — it asks commerceApi.requestOtp for a code. Only after the customer
// enters the SMS code does the page POST /requests with the OTP proof.
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
import CheckoutRequest from '../pages/CheckoutRequest';

function renderCheckout() {
  return render(
    <MemoryRouter>
      <CheckoutRequest />
    </MemoryRouter>
  );
}

/** Fill the contact form and press «ثبت درخواست» to open the OTP step. */
async function openOtpStep() {
  fireEvent.change(screen.getByLabelText('نام و نام خانوادگی'), { target: { value: 'رضا' } });
  fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '09123456789' } });
  fireEvent.change(screen.getByLabelText('پیامرسان'), { target: { value: 'telegram' } });
  fireEvent.click(screen.getByRole('button', { name: 'ثبت درخواست' }));
  return screen.findByTestId('checkout-otp-step');
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  cart.clearCart();
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

describe('CheckoutRequest cart OTP gate', () => {
  it('opens the OTP step on submit and mints no request until confirmed', async () => {
    cart.addItem(12, 2);
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);

    const step = await openOtpStep();

    // The code was requested for the entered mobile, and nothing was persisted.
    expect(commerceApiMock.requestOtp).toHaveBeenCalledTimes(1);
    expect(commerceApiMock.requestOtp.mock.calls[0][0]).toEqual({ mobile: '09123456789' });
    expect(commerceApiMock.submitCommerceRequest).not.toHaveBeenCalled();
    expect(step).toBeInTheDocument();
    // The catalogue mobile is masked, never echoed in full.
    expect(step.textContent).toContain('0912***6789');
  });

  it('posts otp_challenge_id + otp_code on confirm, and the payload carries no price', async () => {
    cart.addItem(12, 2);
    commerceApiMock.submitCommerceRequest.mockResolvedValue({
      data: { receipt_id: 'REQ-OTP1', state: 'pending_review' },
    });
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);
    await openOtpStep();

    fireEvent.change(screen.getByLabelText('کد تأیید'), { target: { value: '12345' } });
    fireEvent.click(screen.getByRole('button', { name: 'تأیید و ثبت درخواست' }));

    await waitFor(() => expect(commerceApiMock.submitCommerceRequest).toHaveBeenCalledTimes(1));
    const payload = commerceApiMock.submitCommerceRequest.mock.calls[0][0];
    expect(payload.otp_challenge_id).toBe(7);
    expect(payload.otp_code).toBe('12345');
    expect(payload.mobile).toBe('09123456789');
    expect(payload.items).toEqual([{ product_id: 12, qty: 2 }]);
    // Exactly the accepted fields — no client-supplied price anywhere.
    expect(Object.keys(payload).sort()).toEqual(
      ['customer_name', 'items', 'messenger', 'mobile', 'otp_challenge_id', 'otp_code'].sort()
    );
    expect(JSON.stringify(payload)).not.toContain('60000');

    expect(await screen.findByText(/REQ-OTP1/)).toBeDefined();
    // Cleared only after the confirmed request succeeded.
    expect(cart.readCart()).toEqual([]);
  });

  it('keeps the user on the OTP step with an error when the code is rejected', async () => {
    cart.addItem(12, 2);
    commerceApiMock.submitCommerceRequest.mockRejectedValue({
      response: { data: { detail: 'کد تأیید نادرست است' } },
    });
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);
    await openOtpStep();

    fireEvent.change(screen.getByLabelText('کد تأیید'), { target: { value: '00000' } });
    fireEvent.click(screen.getByRole('button', { name: 'تأیید و ثبت درخواست' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('کد تأیید نادرست است');
    // Still on the OTP step, cart intact (no request was created).
    expect(screen.getByTestId('checkout-otp-step')).toBeInTheDocument();
    expect(cart.readCart()).toEqual([{ id: 12, qty: 2 }]);
  });

  it('disables the resend button until the countdown ends', async () => {
    cart.addItem(12, 2);
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);
    await openOtpStep();

    const resend = screen.getByRole('button', { name: /ارسال مجدد/ });
    expect(resend).toBeDisabled();

    // resend_after is 2s in the mock; the button enables when it reaches 0.
    await waitFor(() => expect(resend).not.toBeDisabled(), { timeout: 5000 });
  });

  it('shows the Persian delivery error and stays on the form when the code cannot be sent (503)', async () => {
    cart.addItem(12, 2);
    commerceApiMock.requestOtp.mockRejectedValue({
      response: {
        status: 503,
        data: { detail: 'ارسال کد تأیید ناموفق بود؛ لطفاً دوباره تلاش کنید' },
      },
    });
    renderCheckout();
    await screen.findByText(/جاکلیدی تستی/);

    fireEvent.change(screen.getByLabelText('نام و نام خانوادگی'), { target: { value: 'رضا' } });
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '09123456789' } });
    fireEvent.click(screen.getByRole('button', { name: 'ثبت درخواست' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('ارسال کد تأیید ناموفق بود');
    // No OTP step opened: the customer stays on the form.
    expect(screen.queryByTestId('checkout-otp-step')).toBeNull();
    expect(commerceApiMock.submitCommerceRequest).not.toHaveBeenCalled();
  });
});
