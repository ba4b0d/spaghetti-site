// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

// Task 5 — the admin invoice workspace upgrade: status tabs with per-tab
// counts, a debounced search over name/mobile/invoice id, the «ثبت پرداخت
// دستی» modal that posts an off-gateway payment, and the printable postal
// label. Everything goes through the staff commerce client only.
const commerceApiMock = vi.hoisted(() => ({
  getStaffRequests: vi.fn(),
  getStaffInvoices: vi.fn(),
  createStaffInvoice: vi.fn(),
  updateStaffInvoice: vi.fn(),
  approveStaffInvoice: vi.fn(),
  revokeStaffInvoice: vi.fn(),
  manualPayStaffInvoice: vi.fn(),
  getStaffInvoicePdfUrl: vi.fn((id) => `/api/v1/commerce/staff/invoices/${id}/pdf`),
}));
const apiMock = vi.hoisted(() => ({ getProductsAll: vi.fn() }));

vi.mock('../lib/commerceApi', () => commerceApiMock);
vi.mock('../lib/api', () => apiMock);

import CommerceAdmin, { SEARCH_DEBOUNCE_MS } from '../pages/CommerceAdmin';
import { formatPrice } from '../lib/utils';
import { todayGregorianIso } from '../lib/shamsi';

function renderPage() {
  return render(
    <MemoryRouter>
      <CommerceAdmin />
    </MemoryRouter>
  );
}

function makeInvoice(overrides = {}) {
  return {
    id: 101,
    request_id: null,
    customer_name: 'سارا احمدی',
    mobile: '09129998888',
    messenger: 'telegram',
    messenger_handle: '@sara',
    address: 'تهران، خیابان آزادی، پلاک ۱۲',
    specification: 'رنگ نارنجی، ارتفاع ۱۲ سانت',
    internal_note: '',
    shipping_toman: 0,
    total_toman: 120000,
    state: 'draft',
    revision: 1,
    order_id: null,
    has_active_link: false,
    token_expires_at: null,
    approved_at: null,
    revoked_at: null,
    created_at: '2026-10-10T08:00:00Z',
    updated_at: '2026-10-10T08:00:00Z',
    items: [
      { product_id: null, description: 'جاکلیدی تستی', qty: 2, unit_toman: 60000, line_total_toman: 120000 },
    ],
    ...overrides,
  };
}

// Four invoices — one per status bucket — with distinct names, mobiles and ids
// so a search hit is unambiguous.
const DRAFT = makeInvoice({
  id: 101,
  customer_name: 'زهرا محمودی',
  mobile: '09121110000',
  state: 'draft',
  messenger_handle: '@zahra',
  total_toman: 50000,
});
const APPROVED = makeInvoice({
  id: 102,
  customer_name: 'مهدی کریمی',
  mobile: '09351112222',
  state: 'approved',
  has_active_link: true,
  messenger_handle: '@mehdi',
  total_toman: 80000,
});
const PAID = makeInvoice({
  id: 103,
  customer_name: 'سارا احمدی',
  mobile: '09129998888',
  state: 'paid',
  payment_method: 'card_to_card',
  reference_code: 'REF-7788',
  total_toman: 120000,
});
const REVOKED = makeInvoice({
  id: 104,
  customer_name: 'نگار رستمی',
  mobile: '09121234567',
  state: 'revoked',
  total_toman: 30000,
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getProductsAll.mockResolvedValue({ data: [] });
  commerceApiMock.getStaffRequests.mockResolvedValue({ data: [] });
  commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [] });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── status tabs ──────────────────────────────────────────────────────

describe('CommerceAdmin status tabs', () => {
  it('exposes a 300ms search debounce window', () => {
    expect(SEARCH_DEBOUNCE_MS).toBe(300);
  });

  it('counts each status bucket and filters the list to the selected tab', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [DRAFT, APPROVED, PAID, REVOKED],
    });

    const user = userEvent.setup();
    renderPage();

    await screen.findByTestId('invoice-tab-all');

    // Per-tab counts over the loaded dataset.
    expect(screen.getByTestId('invoice-tab-all').textContent).toContain('(4)');
    expect(screen.getByTestId('invoice-tab-draft').textContent).toContain('(1)');
    expect(screen.getByTestId('invoice-tab-approved').textContent).toContain('(1)');
    expect(screen.getByTestId('invoice-tab-paid').textContent).toContain('(1)');
    expect(screen.getByTestId('invoice-tab-cancelled_or_expired').textContent).toContain('(1)');

    // «همه» is the default: every invoice is listed.
    expect(screen.getByText('زهرا محمودی')).toBeInTheDocument();
    expect(screen.getByText('مهدی کریمی')).toBeInTheDocument();
    expect(screen.getByText('سارا احمدی')).toBeInTheDocument();
    expect(screen.getByText('نگار رستمی')).toBeInTheDocument();

    await user.click(screen.getByTestId('invoice-tab-draft'));
    expect(screen.getByText('زهرا محمودی')).toBeInTheDocument();
    expect(screen.queryByText('مهدی کریمی')).toBeNull();
    expect(screen.queryByText('سارا احمدی')).toBeNull();

    await user.click(screen.getByTestId('invoice-tab-approved'));
    expect(screen.getByText('مهدی کریمی')).toBeInTheDocument();
    expect(screen.queryByText('زهرا محمودی')).toBeNull();

    await user.click(screen.getByTestId('invoice-tab-paid'));
    expect(screen.getByText('سارا احمدی')).toBeInTheDocument();
    expect(screen.queryByText('نگار رستمی')).toBeNull();

    await user.click(screen.getByTestId('invoice-tab-cancelled_or_expired'));
    expect(screen.getByText('نگار رستمی')).toBeInTheDocument();
    expect(screen.queryByText('سارا احمدی')).toBeNull();

    await user.click(screen.getByTestId('invoice-tab-all'));
    expect(screen.getByText('زهرا محمودی')).toBeInTheDocument();
    expect(screen.getByText('نگار رستمی')).toBeInTheDocument();
  });
});

// ── debounced search ─────────────────────────────────────────────────

describe('CommerceAdmin invoice search', () => {
  it('filters by customer name, by mobile prefix and by invoice id', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [DRAFT, APPROVED, PAID],
    });

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('زهرا محمودی');
    const input = screen.getByLabelText('جستجوی فاکتور');

    // Customer name.
    await user.type(input, 'مهدی');
    await waitFor(() => expect(screen.queryByText('زهرا محمودی')).toBeNull());
    expect(screen.getByText('مهدی کریمی')).toBeInTheDocument();
    expect(screen.queryByText('سارا احمدی')).toBeNull();

    // The clear button restores the full list.
    await user.click(screen.getByTestId('invoice-search-clear'));
    await waitFor(() => expect(screen.getByText('زهرا محمودی')).toBeInTheDocument());

    // Invoice id (`#103` is what staff copy out of the board).
    await user.type(input, '103');
    await waitFor(() => expect(screen.queryByText('مهدی کریمی')).toBeNull());
    expect(screen.getByText('سارا احمدی')).toBeInTheDocument();

    // Mobile prefix.
    await user.clear(input);
    await user.type(input, '0912111');
    await waitFor(() => expect(screen.queryByText('سارا احمدی')).toBeNull());
    expect(screen.getByText('زهرا محمودی')).toBeInTheDocument();
  });

  it('shows a filtered empty state instead of a blank panel', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [DRAFT] });

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('زهرا محمودی');
    await user.type(screen.getByLabelText('جستجوی فاکتور'), 'ناموجود');

    expect(await screen.findByTestId('invoice-filter-empty')).toHaveTextContent(
      /فاکتوری با این فیلتر یافت نشد/
    );
  });
});

// ── manual payment ───────────────────────────────────────────────────

describe('CommerceAdmin manual payment', () => {
  it('validates the reference code and submits the converted payload', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [APPROVED] });
    commerceApiMock.manualPayStaffInvoice.mockResolvedValue({
      data: makeInvoice({ id: 102, state: 'paid' }),
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId('manual-pay-btn-102'));

    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('ثبت پرداخت دستی فاکتور #102');
    expect(dialog.textContent).toContain('مهدی کریمی');
    expect(dialog.textContent).toContain(formatPrice(APPROVED.total_toman));

    // کارت به کارت is the default method.
    expect(screen.getByRole('radio', { name: 'کارت به کارت' })).toBeChecked();

    // The reference code is required — nothing is sent without it.
    await user.click(screen.getByTestId('manual-pay-submit'));
    expect(await screen.findByRole('alert')).toHaveTextContent(/شماره پیگیری/);
    expect(commerceApiMock.manualPayStaffInvoice).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/شماره پیگیری/), 'REF-9911');
    await user.click(screen.getByRole('radio', { name: 'نقدی / واریز دستی' }));
    await user.type(screen.getByLabelText(/یادداشت/), 'در محل تحویل شد');
    await user.click(screen.getByTestId('manual-pay-submit'));

    // The Shamsi field defaults to today and is submitted as Gregorian ISO.
    await waitFor(() => expect(commerceApiMock.manualPayStaffInvoice).toHaveBeenCalledTimes(1));
    expect(commerceApiMock.manualPayStaffInvoice).toHaveBeenCalledWith(102, {
      payment_method: 'cash',
      reference_code: 'REF-9911',
      paid_at: todayGregorianIso(),
      note: 'در محل تحویل شد',
    });

    // On success the card flips to paid locally, the modal closes and the
    // payment method / reference badge is shown.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.getByTestId('invoice-state-102').textContent).toContain('پرداخت');
    expect(screen.getByTestId('payment-method-102').textContent).toContain('نقدی');
    expect(screen.getByTestId('payment-reference-102').textContent).toContain('REF-9911');
  });

  it('keeps the modal open and surfaces the server refusal', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [APPROVED] });
    commerceApiMock.manualPayStaffInvoice.mockRejectedValue({
      response: { status: 400, data: { detail: 'فاکتور قبلاً پرداخت شده است' } },
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId('manual-pay-btn-102'));
    await screen.findByRole('dialog');

    await user.type(screen.getByLabelText(/شماره پیگیری/), 'REF-0001');
    await user.click(screen.getByTestId('manual-pay-submit'));

    expect(await screen.findByRole('alert')).toHaveTextContent('فاکتور قبلاً پرداخت شده است');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('offers no manual-pay action on an already paid invoice', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [PAID] });

    renderPage();

    expect(await screen.findByTestId('invoice-state-103')).toHaveTextContent(/پرداخت/);
    expect(screen.queryByTestId('manual-pay-btn-103')).toBeNull();
  });

  it('shows the gateway pill and tracking code on a paid invoice', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [
        makeInvoice({ id: 105, state: 'paid', payment_method: 'کارت به کارت', reference_code: 'REF-5555' }),
      ],
    });

    renderPage();

    // A string or an integer method code must both degrade safely.
    expect(await screen.findByTestId('payment-method-105')).toHaveTextContent('کارت به کارت');
    expect(screen.getByTestId('payment-reference-105')).toHaveTextContent('REF-5555');
  });
});

// ── postal packing slip ──────────────────────────────────────────────

describe('CommerceAdmin postal label', () => {
  it('renders the recipient details, package contents and prints / copies', async () => {
    const printSpy = vi.fn();
    vi.stubGlobal('print', printSpy);
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [PAID] });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId('postal-slip-btn-103'));

    const slip = await screen.findByTestId('postal-slip');
    // Sender block.
    expect(slip.textContent).toContain('اسپاگتی پرینت');
    expect(slip.textContent).toContain('اسپاگتی پرینت');
    expect(slip.textContent).toContain('spaghettiprints.ir');
    // Recipient block.
    expect(slip.textContent).toContain('سارا احمدی');
    expect(slip.textContent).toContain('09129998888');
    expect(slip.textContent).toContain('تهران، خیابان آزادی، پلاک ۱۲');
    expect(slip.textContent).toContain('@sara');
    // Package contents.
    expect(slip.textContent).toContain('جاکلیدی تستی × 2');
    expect(slip.textContent).toContain('رنگ نارنجی، ارتفاع ۱۲ سانت');
    // Print styling only ever prints the label itself.
    expect(slip.id).toBe('postal-slip-print');
    expect(document.querySelector('style')).not.toBeNull();

    await user.click(screen.getByTestId('postal-slip-copy'));
    const copied = await navigator.clipboard.readText();
    expect(copied).toContain('سارا احمدی');
    expect(copied).toContain('09129998888');
    expect(copied).toContain('تهران، خیابان آزادی، پلاک ۱۲');

    await user.click(screen.getByTestId('postal-slip-print'));
    expect(printSpy).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId('postal-slip-close'));
    await waitFor(() => expect(screen.queryByTestId('postal-slip')).toBeNull());
  });

  it('offers the postal label for approved and paid invoices only', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [DRAFT, APPROVED, PAID] });

    renderPage();

    expect(await screen.findByTestId('postal-slip-btn-102')).toBeInTheDocument();
    expect(screen.getByTestId('postal-slip-btn-103')).toBeInTheDocument();
    // A draft has nothing to ship yet.
    expect(screen.queryByTestId('postal-slip-btn-101')).toBeNull();
  });
});

// ── commerceApi contract (real module, not the mock) ─────────────────

describe('commerceApi.manualPayStaffInvoice', () => {
  it('posts to the admin manual-pay endpoint', async () => {
    const actual = await vi.importActual('../lib/commerceApi');
    const postSpy = vi.spyOn(actual.default, 'post').mockResolvedValue({ data: {} });

    const payload = { payment_method: 'card_to_card', reference_code: 'R1', paid_at: '2026-10-17', note: '' };
    await actual.manualPayStaffInvoice(9, payload);

    // The backend route is `/admin/invoices/{id}/manual-pay` (routers/commerce.py
    // `pay_invoice_manually`) and is staff-role gated, not `/staff/invoices/...`.
    expect(postSpy).toHaveBeenCalledWith('/admin/invoices/9/manual-pay', payload);
    postSpy.mockRestore();
  });
});
