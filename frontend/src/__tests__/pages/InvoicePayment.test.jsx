// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The pay page talks ONLY to the two public commerce endpoints. The token is a
// private bearer credential: these mocks let us prove it is used exactly as the
// path segment of those calls and never leaks into a log or the DOM.
const commerceApiMock = vi.hoisted(() => ({
  getPublicInvoice: vi.fn(),
  payInvoice: vi.fn(),
}));
vi.mock('../../lib/commerceApi', () => commerceApiMock);

import InvoicePayment, {
  ALLOWED_GATEWAY_HOSTS,
  validateGatewayUrl,
} from '../../pages/InvoicePayment';
import { formatPrice } from '../../lib/constants';
import { NO_REFERRER_META_ID } from '../../hooks/useNoReferrerPolicy';

const TOKEN = 'raw-BEARER-token-123';

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

beforeEach(() => {
  vi.clearAllMocks();
  commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice() });
});

afterEach(() => {
  cleanup();
});

describe('validateGatewayUrl', () => {
  it('accepts the DigiPay live and UAT web-pay HTTPS hosts only', () => {
    expect(validateGatewayUrl('https://web.mydigipay.com/web-pay/tgs/v2:abc')).toBe(
      'https://web.mydigipay.com/web-pay/tgs/v2:abc'
    );
    expect(validateGatewayUrl('https://uatweb.mydigipay.info/web-pay/tgs/v2:abc')).toContain(
      'uatweb.mydigipay.info'
    );
  });

  it('rejects plaintext, arbitrary hosts, redirects-with-credentials and junk', () => {
    expect(validateGatewayUrl('http://web.mydigipay.com/pay')).toBeNull();
    expect(validateGatewayUrl('https://evil.example.com/pay')).toBeNull();
    expect(validateGatewayUrl('https://user:pass@web.mydigipay.com/pay')).toBeNull();
    expect(validateGatewayUrl('https://web.mydigipay.com.evil.com/pay')).toBeNull();
    expect(validateGatewayUrl('javascript:alert(1)')).toBeNull();
    expect(validateGatewayUrl('')).toBeNull();
    expect(validateGatewayUrl(null)).toBeNull();
  });

  it('exposes the allowlist used for the redirect decision', () => {
    expect(ALLOWED_GATEWAY_HOSTS).toContain('web.mydigipay.com');
    expect(ALLOWED_GATEWAY_HOSTS).toContain('uatweb.mydigipay.info');
  });
});

describe('InvoicePayment approved invoice', () => {
  it('renders final items, specification, shipping and the payable Toman total', async () => {
    renderAt();

    expect(await screen.findByText('قطعه الف')).toBeInTheDocument();
    expect(screen.getByText('رنگ مشکی، ارتفاع ۱۲ سانتی‌متر')).toBeInTheDocument();
    expect(screen.getByTestId('invoice-shipping')).toHaveTextContent(formatPrice(20000));
    expect(screen.getByTestId('invoice-total')).toHaveTextContent(formatPrice(70000));

    // Only DigiPay is enabled; the other methods are visibly disabled.
    const digipay = screen.getByRole('radio', { name: /دیجی‌پی/ });
    expect(digipay).toBeChecked();
    expect(digipay).toBeEnabled();
    expect(screen.getByRole('radio', { name: /بیت‌پی/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: /اسنپ‌پی/ })).toBeDisabled();
  });

  it('loads the invoice through the token path and posts a pay request on click', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: {
        state: 'pending',
        amount_rial: 700000,
        redirect_url: 'https://web.mydigipay.com/web-pay/tgs/v2:abc123',
      },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: /پرداخت با دیجی‌پی/ }));

    await waitFor(() => expect(commerceApiMock.payInvoice).toHaveBeenCalledWith(TOKEN));
    expect(commerceApiMock.getPublicInvoice).toHaveBeenCalledWith(
      TOKEN,
      expect.objectContaining({ signal: expect.anything() })
    );
    // Redirect happens only to the validated server URL.
    await waitFor(() =>
      expect(redirect).toHaveBeenCalledWith('https://web.mydigipay.com/web-pay/tgs/v2:abc123')
    );
  });

  it('refuses to redirect to a non-approved gateway URL and surfaces an error', async () => {
    commerceApiMock.payInvoice.mockResolvedValue({
      data: { state: 'pending', amount_rial: 700000, redirect_url: 'https://evil.example.com/pay' },
    });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: /پرداخت با دیجی‌پی/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('shows the server error and allows retrying the payment', async () => {
    commerceApiMock.payInvoice
      .mockRejectedValueOnce(httpError(502, 'درگاه پرداخت در دسترس نیست'))
      .mockResolvedValueOnce({
        data: {
          state: 'pending',
          amount_rial: 700000,
          redirect_url: 'https://web.mydigipay.com/web-pay/tgs/v2:retry',
        },
      });

    const { redirect } = renderAt();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: /پرداخت با دیجی‌پی/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('درگاه پرداخت در دسترس نیست');
    expect(redirect).not.toHaveBeenCalled();

    // A repeated click after a failure is safe and starts the flow again.
    await user.click(screen.getByRole('button', { name: /پرداخت با دیجی‌پی/ }));
    await waitFor(() =>
      expect(redirect).toHaveBeenCalledWith('https://web.mydigipay.com/web-pay/tgs/v2:retry')
    );
  });
});

describe('InvoicePayment non-payable states', () => {
  it('shows an expired state when the link is past its expiry (410)', async () => {
    commerceApiMock.getPublicInvoice.mockRejectedValue(
      httpError(410, 'لینک فاکتور منقضی شده است')
    );

    renderAt();

    expect(await screen.findByText('لینک پرداخت منقضی شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با دیجی‌پی/ })).toBeNull();
  });

  it('shows a generic inaccessible state for an unknown or revoked token (404)', async () => {
    commerceApiMock.getPublicInvoice.mockRejectedValue(httpError(404, 'لینک فاکتور یافت نشد'));

    renderAt();

    expect(await screen.findByText('این لینک پرداخت در دسترس نیست')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با دیجی‌پی/ })).toBeNull();
  });

  it('shows a paid state with no pay action for a settled invoice', async () => {
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice({ state: 'paid' }) });

    renderAt();

    expect(await screen.findByText('این فاکتور پرداخت شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با دیجی‌پی/ })).toBeNull();
  });

  it('shows a distinct revoked state when a revoked invoice is ever returned', async () => {
    commerceApiMock.getPublicInvoice.mockResolvedValue({ data: makeInvoice({ state: 'revoked' }) });

    renderAt();

    expect(await screen.findByText('این لینک لغو شده است')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /پرداخت با دیجی‌پی/ })).toBeNull();
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
        redirect_url: 'https://web.mydigipay.com/web-pay/tgs/v2:secret-redirect',
      },
    });
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});

    renderAt();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /پرداخت با دیجی‌پی/ }));
    await waitFor(() => expect(commerceApiMock.payInvoice).toHaveBeenCalled());

    const allCalls = [logSpy, errSpy, warnSpy, infoSpy].flatMap((spy) =>
      spy.mock.calls.map((args) => JSON.stringify(args))
    );
    expect(allCalls.some((line) => line.includes(TOKEN))).toBe(false);
    expect(allCalls.some((line) => line.includes('secret-redirect'))).toBe(false);
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
