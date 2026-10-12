// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The pay page talks ONLY to the public commerce endpoints. The token is a
// private bearer credential: these mocks let us prove it is used exactly as the
// path segment of those calls and never leaks into a log or the DOM.
const commerceApiMock = vi.hoisted(() => ({
  getPaymentMethods: vi.fn(),
  getPublicInvoice: vi.fn(),
  payInvoice: vi.fn(),
  getPublicInvoicePdfUrl: vi.fn((token) => `/api/v1/commerce/invoices/${token}/pdf`),
}));
vi.mock('../../lib/commerceApi', () => commerceApiMock);

import InvoicePayment, {
  ALLOWED_GATEWAY_HOSTS,
  GATEWAY_ALLOWLIST,
  PAYMENT_STORAGE_UNAVAILABLE_MESSAGE,
  validateGatewayUrl,
} from '../../pages/InvoicePayment';
import { formatPrice } from '../../lib/constants';
import { NO_REFERRER_META_ID } from '../../hooks/useNoReferrerPolicy';
import { GATEWAY_HANDOFF_KEY, GATEWAY_HANDOFF_PATH } from '../../lib/paymentHandoff';
import { PAYMENT_RECEIPT_KEY, readPaymentReceipt } from '../../lib/paymentReceipt';

const TOKEN = 'raw-BEARER-token-123';

// Backend readiness shape (see GET /api/v1/commerce/payment-methods).
const READY_BITPAY = {
  bitpay: { enabled: true, configured: true, environment: 'test' },
  digipay: { enabled: false },
  snapppay: { enabled: false },
};
const NONE_READY = {
  bitpay: { enabled: false, configured: false, environment: 'live' },
  digipay: { enabled: false },
  snapppay: { enabled: false },
};

function makeInvoice(overrides = {}) {
  return {
    id: 42,
    state: 'approved',
    revision: 1,
    shipping_toman: 20000,
    total_toman: 70000,
    specification: 'رنگ مشکی، ارتفاع ۱۲ سانتی‌متر',
    items: [
      { description: 'قطعه الف', qty: 2, unit_toman: 25000, line_total_toman: 50000 },
    ],
    expires_at: '2026-10-17T08:00:00Z',
    approved_at: '2026-10-10T08:00:00Z',
    ...overrides,
  };
}

function renderAt(redirect = vi.fn()) {
  const utils = render(
    <MemoryRouter initialEntries={[`/pay/${TOKEN}`]}>
      <Routes>
        <Route path="/pay/:token" element={<InvoicePayment redirect={redirect} />} />
      </Routes>
    </MemoryRouter>
  );
  return { ...utils, redirect };
}

function httpError(status, detail) {
  const err = new Error(detail);
  err.response = { status, data: detail ? { detail } : {} };
  return err;
}

const BITPAY_OK_URL = 'https://bitpay.ir/payment/gateway-987654-get';

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice() });
  commerceApiMock.getPaymentMethods.mockResolvedValue({ data: READY_BITPAY });
});

afterEach(() => {
  cleanup();
});

describe('validateGatewayUrl', () => {
  it('accepts the BitPay live and test portal URLs only for the bitpay provider', () => {
    expect(validateGatewayUrl('https://bitpay.ir/payment/gateway-123-get', 'bitpay')).toBe(
      'https://bitpay.ir/payment/gateway-123-get'
    );
    expect(
      validateGatewayUrl('https://bitpay.ir/payment-test/gateway-123-get', 'bitpay')
    ).toBe('https://bitpay.ir/payment-test/gateway-123-get');
  });

  it('rejects a BitPay URL on any other host, path, scheme or shape', () => {
    expect(validateGatewayUrl('http://bitpay.ir/payment/gateway-1-get', 'bitpay')).toBeNull();
    expect(validateGatewayUrl('https://evil.example.com/payment/gateway-1-get', 'bitpay')).toBeNull();
    expect(validateGatewayUrl('https://bitpay.ir.evil.com/payment/gateway-1-get', 'bitpay')).toBeNull();
    // a sub-domain is not the exact allowed host
    expect(validateGatewayUrl('https://pay.bitpay.ir/payment/gateway-1-get', 'bitpay')).toBeNull();
    // documented portal URLs carry no query/fragment
    expect(validateGatewayUrl('https://bitpay.ir/payment/gateway-1-get?x=1', 'bitpay')).toBeNull();
    // non-digit id_get, wrong suffix, arbitrary path
    expect(validateGatewayUrl('https://bitpay.ir/payment/gateway-abc-get', 'bitpay')).toBeNull();
    expect(validateGatewayUrl('https://bitpay.ir/payment/gateway-1-return', 'bitpay')).toBeNull();
    expect(validateGatewayUrl('https://bitpay.ir/payment/anything', 'bitpay')).toBeNull();
    // embedded credentials
    expect(validateGatewayUrl('https://user:pass@bitpay.ir/payment/gateway-1-get', 'bitpay')).toBeNull();
  });

  it('keeps the DigiPay host allowlist and refuses an unknown provider (fail closed)', () => {
    expect(validateGatewayUrl('https://web.mydigipay.com/web-pay/tgs/v2:abc', 'digipay')).toBe(
      'https://web.mydigipay.com/web-pay/tgs/v2:abc'
    );
    expect(validateGatewayUrl('https://evil.example.com/pay', 'digipay')).toBeNull();
    // A BitPay URL must not validate under the DigiPay provider and vice-versa.
    expect(validateGatewayUrl(BITPAY_OK_URL, 'digipay')).toBeNull();
    expect(validateGatewayUrl('https://web.mydigipay.com/pay', 'bitpay')).toBeNull();
    // No provider, or an unknown one, is rejected rather than defaulted.
    expect(validateGatewayUrl(BITPAY_OK_URL)).toBeNull();
    expect(validateGatewayUrl(BITPAY_OK_URL, 'paypal')).toBeNull();
    expect(validateGatewayUrl(BITPAY_OK_URL, 'toString')).toBeNull();
    expect(validateGatewayUrl('javascript:alert(1)', 'bitpay')).toBeNull();
    expect(validateGatewayUrl('', 'bitpay')).toBeNull();
    expect(validateGatewayUrl(null, 'bitpay')).toBeNull();
  });

  it('exposes the per-provider allowlist used for the redirect decision', () => {
    expect(ALLOWED_GATEWAY_HOSTS).toContain('web.mydigipay.com');
    expect(ALLOWED_GATEWAY_HOSTS).toContain('uatweb.mydigipay.info');
    expect(GATEWAY_ALLOWLIST.bitpay.hosts).toContain('bitpay.ir');
  });
});

describe('InvoicePayment approved invoice', () => {
  it('renders final items, specification, shipping and the payable Toman total', async () => {
    renderAt();

    expect(await screen.findByText('قطعه الف')).toBeInTheDocument();
    expect(screen.getByText('رنگ مشکی، ارتفاع ۱۲ سانتی‌متر')).toBeInTheDocument();
    expect(screen.getByTestId('invoice-shipping')).toHaveTextContent(formatPrice(20000));
    expect(screen.getByTestId('invoice-total')).toHaveTextContent(formatPrice(70000));

    // BitPay is the single selectable method once the server reports it ready;
    // DigiPay is parked and SnappPay is disabled.
    const bitpay = screen.getByRole('radio', { name: /بیت‌پی/ });
    await waitFor(() => expect(bitpay).toBeChecked());
    expect(bitpay).toBeEnabled();
    expect(screen.getByRole('radio', { name: /دیجی‌پی/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /اسنپ‌پی/ })).toBeDisabled();

    const pdfLink = screen.getByRole('link', { name: /دریافت نسخه PDF فاکتور/ });
    expect(pdfLink).toHaveAttribute('href', `/api/v1/commerce/invoices/${TOKEN}/pdf`);
  });

  it('reads server readiness once before any CTA is usable', async () => {
    renderAt();
    await screen.findByText('قطعه الف');

    expect(commerceApiMock.getPaymentMethods).toHaveBeenCalledWith(
      expect.objectContaining({ signal: expect.anything() })
    );
  });

  it('parks the validated gateway URL and hands off to the token-free /pay/redirect page', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { provider: 'bitpay', state: 'pending', amount_rial: 700000, redirect_url: BITPAY_OK_URL },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    // The method is explicit — no ambient default.
    await waitFor(() => expect(commerceApiMock.payInvoice).toHaveBeenCalledWith(TOKEN, 'bitpay'));
    expect(commerceApiMock.getPublicInvoice).toHaveBeenCalledWith(
      TOKEN,
      expect.objectContaining({ signal: expect.anything() })
    );

    // The browser is NOT sent straight to the gateway from this no-referrer
    // document (which is what made BitPay answer «آدرس ارجاعی نامعتبر»); it is
    // sent to the token-free intermediate page instead.
    await waitFor(() => expect(redirect).toHaveBeenCalledWith(GATEWAY_HANDOFF_PATH));
    expect(redirect).not.toHaveBeenCalledWith(BITPAY_OK_URL);

    // The gateway URL travels through sessionStorage, and the bearer token
    // never does.
    const stored = window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY);
    expect(stored).toBeTruthy();
    expect(stored).toContain(BITPAY_OK_URL);
    expect(stored).not.toContain(TOKEN);
  });

  it('parks the invoice token for the token-free result page, outside the gateway hand-off entry', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { provider: 'bitpay', state: 'pending', amount_rial: 700000, redirect_url: BITPAY_OK_URL },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    await waitFor(() => expect(redirect).toHaveBeenCalledWith(GATEWAY_HANDOFF_PATH));

    // The result page needs the private invoice read to show a TRUTHFUL
    // confirmation, so the token is parked for it here — under a dedicated
    // receipt key, never inside the (token-free) gateway hand-off entry and
    // never in a URL or query string.
    expect(readPaymentReceipt()).toEqual({ token: TOKEN });
    const handoff = window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY);
    expect(handoff).toBeTruthy();
    expect(handoff).not.toContain(TOKEN);
  });

  it('parks no receipt when the hand-off is refused (invalid gateway URL)', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { state: 'pending', amount_rial: 700000, redirect_url: 'https://evil.example.com/pay' },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    await screen.findByRole('alert');
    expect(redirect).not.toHaveBeenCalled();
    // No hand-off means no server-side attempt reached a gateway we trust, so
    // nothing is parked for the result page either.
    expect(readPaymentReceipt()).toBeNull();
    expect(window.sessionStorage.getItem(PAYMENT_RECEIPT_KEY)).toBeNull();
  });

  it('writes no hand-off and redirects nowhere when the gateway URL is not allow-listed', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { state: 'pending', amount_rial: 700000, redirect_url: 'https://evil.example.com/pay' },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY)).toBeNull();
  });

  it('fails safe (never a direct no-Referer navigation) when sessionStorage is unavailable', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { provider: 'bitpay', state: 'pending', amount_rial: 700000, redirect_url: BITPAY_OK_URL },
    });
    // Force per-tab storage to be unusable (private mode / disabled storage).
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
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
      const { redirect } = renderAt();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
      await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

      // Navigating the portal straight from this no-referrer document is
      // KNOWN-BROKEN (BitPay answers «آدرس ارجاعی نامعتبر»), so the customer
      // must NOT be sent there — and nowhere else either, since nothing was
      // parked for the token-free hand-off page.
      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(PAYMENT_STORAGE_UNAVAILABLE_MESSAGE);
      expect(redirect).not.toHaveBeenCalledWith(BITPAY_OK_URL);
      expect(redirect).not.toHaveBeenCalledWith(GATEWAY_HANDOFF_PATH);
      expect(redirect).not.toHaveBeenCalled();

      // No server-side payment attempt was created for a hand-off that cannot
      // complete (so a retry is clean, not a 409 "attempt in flight").
      expect(commerceApiMock.payInvoice).not.toHaveBeenCalled();

      // The CTA is still offered so the customer can retry.
      expect(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ })).toBeInTheDocument();
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });

  it('lets the customer retry the hand-off once sessionStorage is available again', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { provider: 'bitpay', state: 'pending', amount_rial: 700000, redirect_url: BITPAY_OK_URL },
    });
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
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
      const { redirect } = renderAt();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
      await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));
      await screen.findByRole('alert');
      expect(redirect).not.toHaveBeenCalled();

      // Storage is available again (private mode closed / permission granted).
      if (original) Object.defineProperty(window, 'sessionStorage', original);

      await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

      await waitFor(() => expect(redirect).toHaveBeenCalledWith(GATEWAY_HANDOFF_PATH));
      expect(redirect).not.toHaveBeenCalledWith(BITPAY_OK_URL);
      const stored = window.sessionStorage.getItem(GATEWAY_HANDOFF_KEY);
      expect(stored).toContain(BITPAY_OK_URL);
      expect(stored).not.toContain(TOKEN);
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });

  it('refuses to redirect to a non-approved gateway host and surfaces an error', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { state: 'pending', amount_rial: 700000, redirect_url: 'https://evil.example.com/pay' },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('refuses a DigiPay URL returned under the BitPay method (cross-provider tamper)', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: {
        state: 'pending',
        amount_rial: 700000,
        redirect_url: 'https://web.mydigipay.com/web-pay/tgs/v2:abc',
      },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('shows a clear unavailable message when the gateway answers 503', async () => {
    commerceApiMock.payInvoice.mockRejectedValue(
      httpError(503, 'درگاه پرداخت پیکربندی نشده است')
    );

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('درگاه پرداخت در حال حاضر در دسترس نیست');
    expect(redirect).not.toHaveBeenCalled();
  });

  it('surfaces the server conflict detail on a 409 (attempt in flight)', async () => {
    commerceApiMock.payInvoice.mockRejectedValue(
      httpError(409, 'پرداخت از درگاه دیگری برای این فاکتور در حال انجام است')
    );

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'پرداخت از درگاه دیگری برای این فاکتور در حال انجام است'
    );
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe('InvoicePayment when BitPay is not configured', () => {
  beforeEach(() => {
    commerceApiMock.getPaymentMethods.mockResolvedValue({ data: NONE_READY });
  });

  it('renders every method disabled and no payable CTA', async () => {
    renderAt();

    expect(await screen.findByText('قطعه الف')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('payment-unavailable')).toBeInTheDocument());
    expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /دیجی‌پی/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /اسنپ‌پی/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /پرداخت با/ })).toBeNull();
  });

  it('fails closed when the readiness call itself errors', async () => {
    commerceApiMock.getPaymentMethods.mockRejectedValue(httpError(500, 'boom'));

    renderAt();

    expect(await screen.findByText('قطعه الف')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('payment-unavailable')).toBeInTheDocument());
    expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /پرداخت با/ })).toBeNull();
  });
});

describe('InvoicePayment non-payable states', () => {
  it('shows an expired state when the link is past its expiry (410)', async () => {
    commerceApiMock.getPublicInvoice.mockRejectedValue(
      httpError(410, 'لینک فاکتور منقضی شده است')
    );

    renderAt();

    expect(await screen.findByText('لینک پرداخت منقضی شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با بیت‌پی/ })).toBeNull();
  });

  it('shows a generic inaccessible state for an unknown or revoked token (404)', async () => {
    commerceApiMock.getPublicInvoice.mockRejectedValue(httpError(404, 'لینک فاکتور یافت نشد'));

    renderAt();

    expect(await screen.findByText('این لینک پرداخت در دسترس نیست')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با بیت‌پی/ })).toBeNull();
  });

  it('shows a paid state with no pay action for a settled invoice', async () => {
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice({ state: 'paid' }) });

    renderAt();

    expect(await screen.findByText('این فاکتور پرداخت شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با بیت‌پی/ })).toBeNull();
  });

  it('shows a distinct revoked state when a revoked invoice is ever returned', async () => {
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice({ state: 'revoked' }) });

    renderAt();

    expect(await screen.findByText('این لینک لغو شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با بیت‌پی/ })).toBeNull();
  });

  it('offers a retry for a transient load failure', async () => {
    commerceApiMock.getPublicInvoice
      .mockRejectedValueOnce(httpError(500, 'خطای موقت سرور'))
      .mockResolvedValueOnce({ data: makeInvoice() });

    renderAt();
    const user = userEvent.setup();

    expect(await screen.findByRole('alert')).toHaveTextContent('خطای موقت سرور');
    await user.click(screen.getByRole('button', { name: /تلاش دوباره/ }));

    expect(await screen.findByText('قطعه الف')).toBeInTheDocument();
  });
});

describe('InvoicePayment safety', () => {
  it('never logs the bearer token or sensitive response data', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: {
        state: 'pending',
        amount_rial: 700000,
        redirect_url: 'https://bitpay.ir/payment/gateway-424242-get',
      },
    });
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});

    renderAt();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeChecked());
    await user.click(screen.getByRole('button', { name: /پرداخت با بیت‌پی/ }));
    await waitFor(() => expect(commerceApiMock.payInvoice).toHaveBeenCalled());

    const allCalls = [logSpy, errSpy, warnSpy, infoSpy].flatMap((spy) =>
      spy.mock.calls.map((args) => JSON.stringify(args))
    );
    expect(allCalls.some((line) => line.includes(TOKEN))).toBe(false);
    expect(allCalls.some((line) => line.includes('gateway-424242-get'))).toBe(false);
    // The token must not be rendered into the page either.
    expect(document.body.textContent).not.toContain(TOKEN);

    logSpy.mockRestore();
    errSpy.mockRestore();
    warnSpy.mockRestore();
    infoSpy.mockRestore();
  });

  it('applies a document no-referrer policy while mounted and cleans it up', async () => {
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice() });

    const { unmount } = renderAt();

    await screen.findByText('قطعه الف');
    const meta = document.getElementById(NO_REFERRER_META_ID);
    expect(meta).not.toBeNull();
    expect(meta.getAttribute('name')).toBe('referrer');
    expect(meta.getAttribute('content')).toBe('no-referrer');

    unmount();
    expect(document.getElementById(NO_REFERRER_META_ID)).toBeNull();
  });
});
