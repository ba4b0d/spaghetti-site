// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// The result page may OPTIONALLY read the private invoice behind a parked,
// per-tab receipt; it talks only to the public commerce endpoints.
const commerceApiMock = vi.hoisted(() => ({ getPublicInvoice: vi.fn() }));
vi.mock('../../lib/commerceApi', () => commerceApiMock);

import PaymentResult from '../../pages/PaymentResult';
import { formatPrice } from '../../lib/constants';
import { NO_REFERRER_META_ID } from '../../hooks/useNoReferrerPolicy';
import {
  PAYMENT_RECEIPT_KEY,
  writePaymentReceipt,
  readPaymentReceipt,
} from '../../lib/paymentReceipt';

const RECEIPT_TOKEN = 'raw-BEARER-token-555';

/** The public invoice payload the server returns once it has SETTLED (paid). */
const PAID_INVOICE = {
  id: 42,
  state: 'paid',
  revision: 1,
  shipping_toman: 20000,
  total_toman: 70000,
  specification: 'رنگ مشکی، ارتفاع ۱۲ سانتی‌متر',
  items: [
    { description: 'قطعه الف', qty: 2, unit_toman: 25000, line_total_toman: 50000 },
  ],
  expires_at: '2026-10-17T08:00:00Z',
  approved_at: '2026-10-10T08:00:00Z',
};

function renderAt(search = '') {
  return render(
    <MemoryRouter initialEntries={[`/pay/result${search}`]}>
      <PaymentResult />
    </MemoryRouter>
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  commerceApiMock.getPublicInvoice.mockReset();
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});

describe('PaymentResult query handling', () => {
  it('treats a success hint as non-authoritative and never claims payment', () => {
    renderAt('?payment=success');

    // Neutral, non-committal copy — the query is only a presentation hint.
    expect(screen.getByText('درخواست پرداخت شما دریافت شد')).toBeInTheDocument();
    const text = document.body.textContent;
    expect(text).not.toMatch(/پرداخت (با )?موفق/);
    expect(text).not.toMatch(/با موفقیت انجام شد/);
    // The server remains the authority for the final status.
    expect(text).toMatch(/سرور/);
  });

  it('shows the failed hint without implying a charge', () => {
    renderAt('?payment=failed');
    expect(screen.getByText('پرداخت ناموفق بود یا لغو شد')).toBeInTheDocument();
  });

  it('shows the pending hint', () => {
    renderAt('?payment=pending');
    expect(screen.getByText('در حال بررسی نتیجه پرداخت')).toBeInTheDocument();
  });

  it('falls back to a neutral state for an unknown or harmful hint', () => {
    renderAt('?payment=<script>alert(1)</script>');
    expect(screen.getByText('وضعیت پرداخت نامشخص است')).toBeInTheDocument();
    // The untrusted raw value is never echoed into the DOM.
    expect(document.body.textContent).not.toContain('<script>');
  });

  it('renders a neutral state when no hint is present', () => {
    renderAt();
    expect(screen.getByText('وضعیت پرداخت نامشخص است')).toBeInTheDocument();
  });
});

describe('PaymentResult safety', () => {
  it('never reads, logs or echoes a token accidentally placed in the URL', () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const secret = 'SECRET-BEARER-TOKEN';

    renderAt(`?payment=success&token=${secret}`);

    expect(document.body.textContent).not.toContain(secret);
    const allCalls = [logSpy, errSpy, warnSpy, infoSpy].flatMap((spy) =>
      spy.mock.calls.map((args) => JSON.stringify(args))
    );
    expect(allCalls.some((line) => line.includes(secret))).toBe(false);

    logSpy.mockRestore();
    errSpy.mockRestore();
    warnSpy.mockRestore();
    infoSpy.mockRestore();
  });

  it('applies a document no-referrer policy while mounted', () => {
    const { unmount } = renderAt('?payment=success');
    const meta = document.getElementById(NO_REFERRER_META_ID);
    expect(meta).not.toBeNull();
    expect(meta.getAttribute('content')).toBe('no-referrer');
    unmount();
    expect(document.getElementById(NO_REFERRER_META_ID)).toBeNull();
  });

  it('never queries the private invoice when no receipt is parked (no credential → no call)', () => {
    renderAt('?payment=success');
    expect(commerceApiMock.getPublicInvoice).not.toHaveBeenCalled();
  });
});

describe('PaymentResult — truthful confirmation from the parked receipt', () => {
  it('shows the SERVER-confirmed invoice number and amount when the parked invoice is paid', async () => {
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: PAID_INVOICE });

    renderAt('?payment=success');

    expect(await screen.findByTestId('invoice-number')).toHaveTextContent('#42');
    expect(screen.getByTestId('invoice-paid-amount')).toHaveTextContent(formatPrice(70000));

    // The private invoice is read with the parked token, as the path segment of
    // the public invoice GET (never a query, log or Referer).
    expect(commerceApiMock.getPublicInvoice).toHaveBeenCalledWith(
      RECEIPT_TOKEN,
      expect.objectContaining({ signal: expect.anything() })
    );

    // Consumed: the settled payment is done, so the raw token is dropped.
    expect(readPaymentReceipt()).toBeNull();
  });

  it('does NOT claim payment when the server invoice is not paid', async () => {
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockResolvedValue({
      data: { ...PAID_INVOICE, state: 'approved' },
    });

    renderAt('?payment=success');

    // Generic, non-committal copy remains; no confirmed card.
    expect(await screen.findByText('درخواست پرداخت شما دریافت شد')).toBeInTheDocument();
    expect(screen.queryByTestId('invoice-number')).toBeNull();
    expect(document.body.textContent).not.toMatch(/پرداخت شما تأیید شد/);
  });

  it('does not confirm from a stale success hint alone — only the server settles', async () => {
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockResolvedValue({
      data: { ...PAID_INVOICE, state: 'approved' },
    });

    renderAt('?payment=success');

    await screen.findByText('درخواست پرداخت شما دریافت شد');
    expect(screen.queryByTestId('invoice-paid-amount')).toBeNull();
  });

  it('fails closed (generic copy) when the invoice read errors', async () => {
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockRejectedValue(new Error('network down'));

    renderAt('?payment=success');

    expect(await screen.findByText('درخواست پرداخت شما دریافت شد')).toBeInTheDocument();
    expect(screen.queryByTestId('invoice-number')).toBeNull();
  });

  it('shows the confirmed invoice even when the query hint is a stale pending', async () => {
    // The query is only a presentation hint; a server-confirmed paid invoice
    // must be shown truthfully whatever the (untrusted) hint says.
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: PAID_INVOICE });

    renderAt('?payment=pending');

    expect(await screen.findByTestId('invoice-number')).toHaveTextContent('#42');
  });

  it('never renders, or logs, the parked bearer token', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    writePaymentReceipt(RECEIPT_TOKEN);
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: PAID_INVOICE });

    renderAt('?payment=success');
    await screen.findByTestId('invoice-number');

    expect(document.body.textContent).not.toContain(RECEIPT_TOKEN);
    const allCalls = [logSpy, errSpy, warnSpy, infoSpy].flatMap((spy) =>
      spy.mock.calls.map((args) => JSON.stringify(args))
    );
    expect(allCalls.some((line) => line.includes(RECEIPT_TOKEN))).toBe(false);

    logSpy.mockRestore();
    errSpy.mockRestore();
    warnSpy.mockRestore();
    infoSpy.mockRestore();
  });
});

describe('PaymentResult — receipt fail-closed fallbacks', () => {
  it('applies the same receipt contract (expired entries are ignored)', async () => {
    // An expired entry must never be used to query the invoice.
    window.sessionStorage.setItem(
      PAYMENT_RECEIPT_KEY,
      JSON.stringify({ token: RECEIPT_TOKEN, ts: Date.now() - 10 * 60 * 60 * 1000 })
    );

    renderAt('?payment=success');

    expect(await screen.findByText('درخواست پرداخت شما دریافت شد')).toBeInTheDocument();
    expect(commerceApiMock.getPublicInvoice).not.toHaveBeenCalled();
  });
});
