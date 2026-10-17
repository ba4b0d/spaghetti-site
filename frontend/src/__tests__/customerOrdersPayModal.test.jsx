import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Task 3 — the «پرداخت آنلاین» button + gateway-picker modal on the
// one-visit «سفارش‌های من» page. Proven here: an approved invoice exposes the
// CTA, the modal shows the frozen breakdown and both gateways (DigiPay
// preselected), submitting calls the history API with the chosen gateway and
// hands the browser to the returned redirect_url, and a server refusal is
// surfaced as an in-modal Persian error.
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

vi.mock('../lib/commerceHistoryApi', () => apiMock);
vi.mock('../lib/commerceHistorySession', () => sessionMock);

import CustomerOrders from '../pages/CustomerOrders';
import { formatPrice } from '../lib/utils';

const TOKEN = 'history-token-pay';
const REDIRECT = 'https://gw.example/web-pay/tgs/v2:xyz';

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

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/my-orders']}>
      <CustomerOrders />
    </MemoryRouter>
  );

// ── window.location capture ──────────────────────────────────────────
// The modal leaves the SPA via `window.location.href = url`; capture the
// assignment instead of letting jsdom attempt a real navigation.
let redirects = [];
let originalLocation;

beforeEach(() => {
  originalLocation = window.location;
  redirects = [];
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: {
      get href() {
        return 'http://localhost/my-orders';
      },
      set href(url) {
        redirects.push(url);
      },
    },
  });
});

afterEach(() => {
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: originalLocation,
  });
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionMock.readHistorySession.mockReturnValue({ token: TOKEN, expiresAt: Date.now() + 60000 });
  sessionMock.writeHistorySession.mockReturnValue(true);
  apiMock.getCustomerHistory.mockResolvedValue({
    data: { items: [approvedInvoice], has_more: false },
  });
  apiMock.getCustomerProfile.mockResolvedValue({ data: { stats: {} } });
  apiMock.payCustomerInvoice.mockResolvedValue({ data: { redirect_url: REDIRECT } });
});

async function openModal() {
  renderPage();
  const cta = await screen.findByTestId('pay-online-btn-22');
  fireEvent.click(cta);
  return screen.findByTestId('pay-modal');
}

describe('CustomerOrders — online payment modal', () => {
  it('renders a «پرداخت آنلاین» button on an approved invoice', async () => {
    renderPage();

    const cta = await screen.findByTestId('pay-online-btn-22');
    expect(cta.textContent).toContain('پرداخت آنلاین');
    expect(screen.queryByTestId('pay-modal')).toBeNull();
  });

  it('does not offer the CTA on a paid invoice', async () => {
    apiMock.getCustomerHistory.mockResolvedValue({ data: { items: [paidInvoice], has_more: false } });
    renderPage();

    await screen.findByTestId('entry-invoice-23');
    expect(screen.queryByTestId('pay-online-btn-23')).toBeNull();
  });

  it('opens a modal with the frozen breakdown and both gateways (DigiPay default)', async () => {
    const modal = await openModal();

    expect(modal.textContent).toContain('پرداخت آنلاین فاکتور #22');
    // مبلغ اقلام + هزینه بسته‌بندی و ارسال + مبلغ کل قابل پرداخت
    expect(modal.textContent).toContain('مبلغ اقلام سفارش');
    expect(modal.textContent).toContain('هزینه بسته‌بندی و ارسال');
    expect(modal.textContent).toContain('مبلغ کل قابل پرداخت');
    expect(screen.getByTestId('pay-total').textContent).toContain(formatPrice(120000));
    expect(screen.getByTestId('pay-breakdown').textContent).toContain(formatPrice(20000));

    // Both gateways are selectable; DigiPay is the default.
    expect(screen.getByTestId('gateway-digipay')).toBeInTheDocument();
    expect(screen.getByTestId('gateway-bitpay')).toBeInTheDocument();
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(2);
    expect(radios[0]).toBeChecked();
  });

  it('calls payCustomerInvoice with the selected gateway and redirects the browser', async () => {
    await openModal();

    fireEvent.click(screen.getByRole('radio', { name: /بیت‌پی/ }));
    expect(screen.getAllByRole('radio')[1]).toBeChecked();

    fireEvent.click(screen.getByTestId('pay-submit'));

    await waitFor(() =>
      expect(apiMock.payCustomerInvoice).toHaveBeenCalledWith(TOKEN, 22, 'bitpay')
    );
    await waitFor(() => expect(redirects).toEqual([REDIRECT]));
  });

  it('uses DigiPay when the default gateway is left untouched', async () => {
    await openModal();

    fireEvent.click(screen.getByTestId('pay-submit'));

    await waitFor(() =>
      expect(apiMock.payCustomerInvoice).toHaveBeenCalledWith(TOKEN, 22, 'digipay')
    );
    await waitFor(() => expect(redirects).toEqual([REDIRECT]));
  });

  it('shows a Persian error inside the modal and stays put when the server refuses', async () => {
    apiMock.payCustomerInvoice.mockRejectedValue({
      response: { status: 400, data: { detail: 'مهلت پرداخت فاکتور به پایان رسیده است' } },
    });
    await openModal();

    fireEvent.click(screen.getByTestId('pay-submit'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('مهلت پرداخت فاکتور به پایان رسیده است');
    expect(redirects).toEqual([]);
    // The modal stays open so the customer can retry or dismiss it.
    expect(screen.getByTestId('pay-modal')).toBeInTheDocument();
  });

  it('closes the modal on «انصراف» without calling the gateway', async () => {
    await openModal();

    fireEvent.click(screen.getByRole('button', { name: 'انصراف' }));

    await waitFor(() => expect(screen.queryByTestId('pay-modal')).toBeNull());
    expect(apiMock.payCustomerInvoice).not.toHaveBeenCalled();
  });
});
