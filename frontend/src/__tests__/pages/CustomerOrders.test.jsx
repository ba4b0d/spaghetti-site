import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// The one-visit «سفارش‌های من» page. It must never persist personal data
// anywhere except the tab session module (which is mocked here), never leak the
// phone into a URL, never render a payment CTA (the raw invoice link is not
// recoverable), and must wipe its in-memory history on 401/sign-out even when
// the revoke call itself fails.
const apiMock = vi.hoisted(() => ({
  requestHistoryOtp: vi.fn(),
  verifyHistoryOtp: vi.fn(),
  getCustomerHistory: vi.fn(),
  getCustomerProfile: vi.fn(),
  payCustomerInvoice: vi.fn(),
  signOutHistory: vi.fn(),
}));
const sessionMock = vi.hoisted(() => ({
  readHistorySession: vi.fn(),
  writeHistorySession: vi.fn(),
  clearHistorySession: vi.fn(),
}));

vi.mock('../../lib/commerceHistoryApi', () => apiMock);
vi.mock('../../lib/commerceHistorySession', () => sessionMock);

import CustomerOrders from '../../pages/CustomerOrders';
import { formatPrice } from '../../lib/utils';

const MOBILE = '09123456789';
const MASKED = '0912***6789';
const TOKEN = 'history-token-1';

const futureIso = () => new Date(Date.now() + 30 * 60 * 1000).toISOString();

const requestEntry = {
  kind: 'request',
  id: 11,
  request_id: 11,
  state: 'pending_review',
  created_at: '2026-10-10T08:00:00Z',
  items: [{ name: 'جاکلیدی تستی', qty: 2 }],
};

const draftInvoice = {
  kind: 'invoice',
  id: 21,
  request_id: 11,
  state: 'draft',
  created_at: '2026-10-11T08:00:00Z',
  items: [{ name: 'قطعهٔ سفارشی', qty: 1 }],
};

const approvedInvoice = {
  kind: 'invoice',
  id: 22,
  request_id: null,
  state: 'approved',
  created_at: '2026-10-12T08:00:00Z',
  items: [{ name: 'قطعهٔ تأییدشده', qty: 1, unit_toman: 100000, line_total_toman: 100000 }],
  shipping_toman: 20000,
  total_toman: 120000,
};

const paidInvoice = {
  kind: 'invoice',
  id: 23,
  request_id: null,
  state: 'paid',
  created_at: '2026-10-12T09:00:00Z',
  items: [{ name: 'قطعهٔ پرداخت‌شده', qty: 1, unit_toman: 50000, line_total_toman: 50000 }],
  shipping_toman: 0,
  total_toman: 50000,
};

const renderPage = (initialEntries = ['/my-orders']) =>
  render(
    <MemoryRouter initialEntries={initialEntries}>
      <CustomerOrders />
    </MemoryRouter>
  );

const withSession = () => sessionMock.readHistorySession.mockReturnValue({ token: TOKEN, expiresAt: Date.now() + 60000 });

/** Fill the mobile form and press «دریافت کد تأیید» to reach the OTP step. */
async function openOtpStep() {
  fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: MOBILE } });
  fireEvent.click(screen.getByRole('button', { name: 'دریافت کد تأیید' }));
  return screen.findByTestId('my-orders-otp-step');
}

async function confirmCode(value = '12345') {
  fireEvent.change(screen.getByLabelText('کد تأیید'), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'تأیید و مشاهده سفارش‌ها' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  sessionMock.readHistorySession.mockReturnValue(null);
  sessionMock.writeHistorySession.mockReturnValue(true);
  sessionMock.clearHistorySession.mockReset();
  apiMock.requestHistoryOtp.mockResolvedValue({
    data: {
      challenge_id: 7,
      expires_in: 120,
      resend_after: 0,
      delivery: 'sms',
      masked_mobile: MASKED,
    },
  });
  apiMock.verifyHistoryOtp.mockResolvedValue({ data: { token: TOKEN, expires_at: futureIso() } });
  apiMock.getCustomerHistory.mockResolvedValue({ data: { items: [], has_more: false } });
  apiMock.getCustomerProfile.mockResolvedValue({
    data: {
      customer_name: 'رضا',
      email: 'reza@example.com',
      addresses: ['تهران، خیابان آزادی، پلاک ۱۰'],
      stats: { total_orders: 0, pending_payment: 0, paid: 0 },
    },
  });
  apiMock.signOutHistory.mockResolvedValue({ data: { ok: true } });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CustomerOrders — verification entry', () => {
  it('shows the RTL mobile form, requests an OTP and never puts the phone in the URL', async () => {
    const { container } = renderPage();

    expect(container.querySelector('[dir="rtl"]')).not.toBeNull();
    const input = screen.getByLabelText('شماره موبایل');
    fireEvent.change(input, { target: { value: MOBILE } });
    fireEvent.click(screen.getByRole('button', { name: 'دریافت کد تأیید' }));

    const step = await screen.findByTestId('my-orders-otp-step');
    expect(apiMock.requestHistoryOtp).toHaveBeenCalledWith({ mobile: MOBILE });
    expect(step.textContent).toContain(MASKED);

    // The phone is never a URL/query/hash value.
    expect(window.location.search).toBe('');
    expect(window.location.href).not.toContain(MOBILE);
  });

  it('rejects a malformed mobile with an inline error and no network call', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: '12345' } });
    fireEvent.click(screen.getByRole('button', { name: 'دریافت کد تأیید' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('۰۹');
    expect(apiMock.requestHistoryOtp).not.toHaveBeenCalled();
  });

  it('focuses the code input when the OTP step opens', async () => {
    renderPage();
    await openOtpStep();
    expect(document.activeElement).toBe(screen.getByLabelText('کد تأیید'));
  });

  it('surfaces the rate-limit message on a 429', async () => {
    apiMock.requestHistoryOtp.mockRejectedValue({ response: { status: 429, data: {} } });
    renderPage();
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: MOBILE } });
    fireEvent.click(screen.getByRole('button', { name: 'دریافت کد تأیید' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('بیش از حد مجاز');
    // The throttle keeps the visitor on the form; no OTP step is opened.
    expect(screen.queryByTestId('my-orders-otp-step')).toBeNull();
  });

  it('shows the delivery failure message and stays on the form on a 503', async () => {
    apiMock.requestHistoryOtp.mockRejectedValue({
      response: { status: 503, data: { detail: 'ارسال کد تأیید ناموفق بود' } },
    });
    renderPage();
    fireEvent.change(screen.getByLabelText('شماره موبایل'), { target: { value: MOBILE } });
    fireEvent.click(screen.getByRole('button', { name: 'دریافت کد تأیید' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('ارسال کد تأیید ناموفق بود');
    expect(screen.queryByTestId('my-orders-otp-step')).toBeNull();
  });
});

describe('CustomerOrders — session and list lifecycle', () => {
  it('verifies the code, stores the session and loads the first page', async () => {
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });
    renderPage();
    await openOtpStep();
    await confirmCode();

    await screen.findByTestId('my-orders-list');
    expect(sessionMock.writeHistorySession).toHaveBeenCalledWith(TOKEN, expect.any(String));
    expect(apiMock.getCustomerHistory).toHaveBeenCalledWith(
      TOKEN,
      { limit: 20, offset: 0 },
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(await screen.findByText('جاکلیدی تستی')).toBeInTheDocument();
  });

  it('renders personalized customer greeting, stats and saved addresses in the profile tab', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });
    apiMock.getCustomerProfile.mockResolvedValue({
      data: {
        customer_name: 'باربد',
        mobile: '09123456789',
        masked_mobile: '0912***6789',
        email: 'barbad@example.com',
        messenger: 'telegram',
        messenger_handle: '@barbad',
        addresses: ['تهران، خیابان آزادی، کوچه صادقی، پلاک ۱۵'],
        stats: { total_orders: 4, pending_payment: 1, paid: 3 },
      },
    });

    renderPage();

    // Verify name greeting
    expect(await screen.findByText('سلام، باربد عزیز 👋')).toBeInTheDocument();

    // Click profile tab
    fireEvent.click(screen.getByRole('button', { name: /نشانی‌ها و مشخصات/ }));

    // Verify address and email displayed
    expect(await screen.findByText(/تهران، خیابان آزادی، کوچه صادقی، پلاک ۱۵/)).toBeInTheDocument();
    expect(screen.getAllByText('barbad@example.com').length).toBeGreaterThanOrEqual(1);
  });

  it('still shows the list when tab storage is unavailable (write returns false)', async () => {
    sessionMock.writeHistorySession.mockReturnValue(false);
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });
    renderPage();
    await openOtpStep();
    await confirmCode();

    expect(await screen.findByText('جاکلیدی تستی')).toBeInTheDocument();
  });

  it('resumes straight to the list from a live tab session', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });

    renderPage();

    await screen.findByTestId('my-orders-list');
    expect(apiMock.requestHistoryOtp).not.toHaveBeenCalled();
    expect(apiMock.getCustomerHistory).toHaveBeenCalledWith(
      TOKEN,
      { limit: 20, offset: 0 },
      expect.anything()
    );
  });

  it('falls back to the OTP screen when the stored session is stale (module returns null)', async () => {
    sessionMock.readHistorySession.mockReturnValue(null);
    renderPage();

    expect(await screen.findByTestId('my-orders-verify')).toBeInTheDocument();
    expect(apiMock.getCustomerHistory).not.toHaveBeenCalled();
  });

  it('clears the session and data and returns to verification on a 401', async () => {
    withSession();
    apiMock.getCustomerHistory.mockRejectedValue({ response: { status: 401, data: {} } });

    renderPage();

    expect(await screen.findByTestId('my-orders-verify')).toBeInTheDocument();
    expect(sessionMock.clearHistorySession).toHaveBeenCalled();
    expect(screen.queryByTestId('my-orders-list')).toBeNull();
    expect(screen.getByRole('alert').textContent).toMatch(/نشست شما معتبر نیست/);
  });

  it('clears the session on a 401 during pagination', async () => {
    withSession();
    apiMock.getCustomerHistory
      .mockResolvedValueOnce({ data: { items: [requestEntry], has_more: true } })
      .mockRejectedValueOnce({ response: { status: 401, data: {} } });

    renderPage();
    await screen.findByTestId('load-more');
    fireEvent.click(screen.getByTestId('load-more'));

    await screen.findByTestId('my-orders-verify');
    expect(sessionMock.clearHistorySession).toHaveBeenCalled();
  });

  it('sign-out revokes server-side and wipes data even when the network fails', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });
    apiMock.signOutHistory.mockRejectedValue(new Error('offline'));

    renderPage();
    await screen.findByText('جاکلیدی تستی');
    fireEvent.click(screen.getByTestId('sign-out'));

    expect(await screen.findByTestId('my-orders-verify')).toBeInTheDocument();
    expect(sessionMock.clearHistorySession).toHaveBeenCalled();
    expect(screen.queryByText('جاکلیدی تستی')).toBeNull();
    await waitFor(() => expect(apiMock.signOutHistory).toHaveBeenCalledWith(TOKEN));
  });

  it('does not restore old history after sign-out + back navigation (remount)', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });

    const first = renderPage();
    await screen.findByText('جاکلیدی تستی');
    fireEvent.click(screen.getByTestId('sign-out'));
    await screen.findByTestId('my-orders-verify');
    first.unmount();

    // A back navigation re-mounts the page; storage is gone so there is no data.
    sessionMock.readHistorySession.mockReturnValue(null);
    renderPage();
    await screen.findByTestId('my-orders-verify');
    expect(screen.queryByText('جاکلیدی تستی')).toBeNull();
  });

  it('aborts the history fetch on unmount', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({ data: { items: [], has_more: false } });

    const { unmount } = renderPage();
    await waitFor(() => expect(apiMock.getCustomerHistory).toHaveBeenCalled());

    const config = apiMock.getCustomerHistory.mock.calls[0][2];
    expect(config.signal).toBeInstanceOf(AbortSignal);
    unmount();
    expect(config.signal.aborted).toBe(true);
  });
});

describe('CustomerOrders — entry cards, states and money', () => {
  it('renders request and manual-invoice cards with server-owned status labels', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry, draftInvoice], has_more: false },
    });
    renderPage();
    await screen.findByTestId('entry-request-11');

    expect(screen.getByText('در حال بررسی')).toBeInTheDocument();
    expect(screen.getByText('پیش‌نویس')).toBeInTheDocument();
    expect(screen.getByText('جاکلیدی تستی')).toBeInTheDocument();
    expect(screen.getByText('قطعهٔ سفارشی')).toBeInTheDocument();
    // A request/draft carries no frozen money at all.
    expect(screen.queryByTestId('entry-total-request-11')).toBeNull();
    expect(screen.queryByTestId('entry-total-invoice-21')).toBeNull();
  });

  it('shows frozen totals for an approved invoice with an online pay CTA', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [approvedInvoice], has_more: false },
    });
    const { container } = renderPage();

    await screen.findByTestId('entry-invoice-22');
    expect(screen.getByText('تأییدشده')).toBeInTheDocument();
    const totals = screen.getByTestId('entry-total-invoice-22');
    expect(totals.textContent).toContain(formatPrice(120000));

    // The approved invoice is payable from the customer area: a prominent CTA,
    // and still no raw /pay link anywhere in the DOM.
    expect(screen.getByTestId('pay-online-btn-22')).toBeInTheDocument();
    const links = container.querySelectorAll('a[href]');
    expect(
      Array.from(links).some((a) => (a.getAttribute('href') || '').startsWith('/pay'))
    ).toBe(false);
  });

  it('shows paid totals but no pay CTA and no support note', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [paidInvoice], has_more: false },
    });
    renderPage();

    await screen.findByTestId('entry-invoice-23');
    expect(screen.getByText('پرداخت‌شده')).toBeInTheDocument();
    expect(screen.getByTestId('entry-total-invoice-23').textContent).toContain(formatPrice(50000));
    expect(screen.queryByTestId('pay-support')).toBeNull();
    expect(screen.queryByTestId('pay-online-btn-23')).toBeNull();
    expect(screen.queryByRole('button', { name: /پرداخت/ })).toBeNull();
  });

  it('labels revoked and unknown states, with a neutral fallback', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: {
        items: [
          { kind: 'invoice', id: 30, request_id: null, state: 'revoked', created_at: '2026-10-12T00:00:00Z', items: [] },
          { kind: 'request', id: 31, request_id: 31, state: 'brand_new_state', created_at: '2026-10-12T00:00:00Z', items: [] },
        ],
        has_more: false,
      },
    });
    renderPage();

    await screen.findByTestId('entry-invoice-30');
    expect(screen.getByText('لغو‌شده')).toBeInTheDocument();
    expect(screen.getByText('وضعیت نامشخص')).toBeInTheDocument();
  });

  it('shows an empty state when the verified number has no history', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({ data: { items: [], has_more: false } });
    renderPage();

    expect(await screen.findByTestId('my-orders-empty')).toBeInTheDocument();
  });

  it('never claims payment success from a redirect-style query string', async () => {
    renderPage(['/my-orders?state=paid&payment=success&status=paid']);

    await screen.findByTestId('my-orders-verify');
    expect(screen.queryByText('پرداخت‌شده')).toBeNull();
    expect(screen.queryByText(/پرداخت موفق/)).toBeNull();
  });
});

describe('CustomerOrders — pagination boundary', () => {
  it('pages with the running offset and hides the control at the end', async () => {
    withSession();
    const firstPage = Array.from({ length: 20 }, (_, i) => ({
      kind: 'request',
      id: 100 + i,
      request_id: 100 + i,
      state: 'pending_review',
      created_at: '2026-10-12T00:00:00Z',
      items: [{ name: `قلم ${i}`, qty: 1 }],
    }));
    apiMock.getCustomerHistory
      .mockResolvedValueOnce({ data: { items: firstPage, has_more: true } })
      .mockResolvedValueOnce({ data: { items: [requestEntry], has_more: false } });

    renderPage();
    const more = await screen.findByTestId('load-more');
    fireEvent.click(more);

    await waitFor(() =>
      expect(apiMock.getCustomerHistory).toHaveBeenLastCalledWith(
        TOKEN,
        { limit: 20, offset: 20 },
        expect.anything()
      )
    );
    await waitFor(() => expect(screen.queryByTestId('load-more')).toBeNull());
  });
});

describe('CustomerOrders — privacy invariants', () => {
  it('never writes to localStorage across a full verify + list flow', async () => {
    const localSpy = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(() => null),
      get length() {
        return 0;
      },
    };
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      writable: true,
      value: localSpy,
    });

    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry], has_more: false },
    });
    renderPage();
    await openOtpStep();
    await confirmCode();
    await screen.findByTestId('my-orders-list');

    expect(localSpy.setItem).not.toHaveBeenCalled();
    expect(localSpy.getItem).not.toHaveBeenCalled();
    // The only persistence is the tab session module.
    expect(sessionMock.writeHistorySession).toHaveBeenCalledTimes(1);
  });
});

describe('CustomerOrders — final hardening (masking, single alert, request link)', () => {
  it('fails closed when the OTP response omits masked_mobile (never renders the full number)', async () => {
    // Server contract drift: no masked_mobile field at all.
    apiMock.requestHistoryOtp.mockResolvedValue({
      data: { challenge_id: 9, expires_in: 120, resend_after: 0, delivery: 'sms' },
    });
    renderPage();
    const step = await openOtpStep();

    // The raw number must never be displayed; a local masking of the already
    // validated number (or the generic label) stands in for the server value.
    expect(step.textContent).not.toContain(MOBILE);
    expect(step.textContent).toMatch(/0912\*\*\*6789|شماره شما/);
  });

  it('renders a single error alert on a pagination failure and keeps retry', async () => {
    withSession();
    apiMock.getCustomerHistory
      .mockResolvedValueOnce({ data: { items: [requestEntry], has_more: true } })
      .mockRejectedValueOnce({ response: { status: 500, data: { detail: 'خطای صفحه‌بندی' } } });

    renderPage();
    await screen.findByTestId('load-more');
    fireEvent.click(screen.getByTestId('load-more'));

    await screen.findByTestId('my-orders-page-error');
    // Exactly one accessible alert and one instance of the message — the old
    // full error card and the inline box must not both render.
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getAllByText('خطای صفحه‌بندی')).toHaveLength(1);
    // The first-page full error card is not the pagination surface.
    expect(screen.queryByTestId('my-orders-error')).toBeNull();
    // Retry UX is preserved for the failed page.
    expect(screen.getByRole('button', { name: /تلاش دوباره/ })).toBeInTheDocument();
  });

  it('surfaces the request link on a linked invoice without adding a pay CTA', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [requestEntry, draftInvoice], has_more: false },
    });
    renderPage();
    await screen.findByTestId('entry-invoice-21');

    const link = screen.getByTestId('entry-link-invoice-21');
    expect(link.textContent).toMatch(/مرتبط با درخواست/);
    expect(link.textContent).toContain('#11');
    // No payment authority is introduced by the relationship label.
    expect(screen.queryByRole('button', { name: /پرداخت/ })).toBeNull();
  });

  it('does not show a request link on an unlinked invoice', async () => {
    withSession();
    apiMock.getCustomerHistory.mockResolvedValue({
      data: { items: [approvedInvoice], has_more: false },
    });
    renderPage();
    await screen.findByTestId('entry-invoice-22');

    expect(screen.queryByTestId('entry-link-invoice-22')).toBeNull();
  });
});
