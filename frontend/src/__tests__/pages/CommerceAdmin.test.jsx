// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

// Staff invoice admin talks only to the commerce client (staff endpoints) and
// the catalogue list (optional product attach). Nothing here may reach a
// Telegram/Bale sender — approval only ever surfaces a copyable link.
const commerceApiMock = vi.hoisted(() => ({
  getStaffRequests: vi.fn(),
  getStaffInvoices: vi.fn(),
  createStaffInvoice: vi.fn(),
  updateStaffInvoice: vi.fn(),
  approveStaffInvoice: vi.fn(),
  revokeStaffInvoice: vi.fn(),
}));
const apiMock = vi.hoisted(() => ({ getProductsAll: vi.fn() }));

vi.mock('../../lib/commerceApi', () => commerceApiMock);
vi.mock('../../lib/api', () => apiMock);

import CommerceAdmin, {
  REQUESTS_PAGE_SIZE,
  INVOICES_PAGE_SIZE,
  COPY_RESET_MS,
} from '../../pages/CommerceAdmin';

function renderPage() {
  return render(
    <MemoryRouter>
      <CommerceAdmin />
    </MemoryRouter>
  );
}

function makeRequest(overrides = {}) {
  return {
    id: 5,
    receipt_id: 'REQ-AAA111',
    customer_name: 'رضا رضایی',
    mobile: '09123456789',
    messenger: 'telegram',
    messenger_handle: '@reza',
    address: '',
    note: 'یادداشت مشتری',
    state: 'pending_review',
    created_at: '2026-10-10T08:00:00Z',
    items: [
      { product_id: 12, display_name: 'جاکلیدی تستی', qty: 2, indicative_unit_price_toman: 30000 },
    ],
    ...overrides,
  };
}

function makeInvoice(overrides = {}) {
  return {
    id: 9,
    request_id: null,
    customer_name: 'سارا',
    mobile: '09120000000',
    messenger: 'telegram',
    messenger_handle: '',
    address: '',
    specification: '',
    internal_note: '',
    shipping_toman: 0,
    total_toman: 50000,
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
      { product_id: null, description: 'آیتم دستی', qty: 1, unit_toman: 50000, line_total_toman: 50000 },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('open', vi.fn());
  apiMock.getProductsAll.mockResolvedValue({ data: [] });
  commerceApiMock.getStaffRequests.mockResolvedValue({ data: [] });
  commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [] });
});

// ── request queue pagination ─────────────────────────────────────────

describe('CommerceAdmin request queue', () => {
  it('pages website requests until a short page is returned', async () => {
    const firstPage = Array.from({ length: REQUESTS_PAGE_SIZE }, (_, i) =>
      makeRequest({ id: i + 1, customer_name: `مشتری ${i + 1}` })
    );
    const secondPage = [makeRequest({ id: 999, customer_name: 'مشتری آخر' })];
    commerceApiMock.getStaffRequests.mockImplementation(({ offset } = {}) =>
      Promise.resolve({ data: offset === 0 ? firstPage : secondPage })
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('مشتری 1');
    expect(commerceApiMock.getStaffRequests).toHaveBeenLastCalledWith({
      limit: REQUESTS_PAGE_SIZE,
      offset: 0,
    });

    await user.click(screen.getByRole('button', { name: /بارگذاری بیشتر/ }));

    await screen.findByText('مشتری آخر');
    expect(commerceApiMock.getStaffRequests).toHaveBeenLastCalledWith({
      limit: REQUESTS_PAGE_SIZE,
      offset: REQUESTS_PAGE_SIZE,
    });
    // A short page means the queue is exhausted.
    expect(screen.queryByRole('button', { name: /بارگذاری بیشتر/ })).toBeNull();
  });
});

// ── manual draft with a custom line item ─────────────────────────────

describe('CommerceAdmin manual invoice', () => {
  it('creates a draft with a custom line item and no catalogue product', async () => {
    commerceApiMock.createStaffInvoice.mockResolvedValue({
      data: makeInvoice({ id: 21, customer_name: 'علی' }),
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /فاکتور جدید/ }));

    await user.type(screen.getByLabelText(/نام مشتری/), 'علی');
    await user.type(screen.getByLabelText(/شماره موبایل/), '09121112233');
    await user.type(screen.getByLabelText('شرح آیتم'), 'قطعه سفارشی');
    await user.clear(screen.getByLabelText('تعداد'));
    await user.type(screen.getByLabelText('تعداد'), '3');
    await user.type(screen.getByLabelText('قیمت واحد (تومان)'), '12000');

    await user.click(screen.getByRole('button', { name: 'ذخیره' }));

    await waitFor(() => expect(commerceApiMock.createStaffInvoice).toHaveBeenCalledTimes(1));
    const payload = commerceApiMock.createStaffInvoice.mock.calls[0][0];
    expect(payload.request_id).toBeNull();
    expect(payload.customer_name).toBe('علی');
    expect(payload.mobile).toBe('09121112233');
    expect(payload.items).toEqual([
      { product_id: null, description: 'قطعه سفارشی', qty: 3, unit_toman: 12000 },
    ]);
    // Totals stay integer Toman; shipping defaults to 0.
    expect(payload.shipping_toman).toBe(0);
  });
});

// ── website request conversion ───────────────────────────────────────

describe('CommerceAdmin request conversion', () => {
  it('prefills the editor from a request and links it on save', async () => {
    commerceApiMock.getStaffRequests.mockResolvedValue({ data: [makeRequest()] });
    commerceApiMock.createStaffInvoice.mockResolvedValue({
      data: makeInvoice({ id: 22, request_id: 5, customer_name: 'رضا رضایی' }),
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /تبدیل به فاکتور/ }));

    const nameField = await screen.findByLabelText(/نام مشتری/);
    expect(nameField).toHaveValue('رضا رضایی');
    expect(screen.getByLabelText(/شماره موبایل/)).toHaveValue('09123456789');
    // The request's line item seeds the editor with its indicative price.
    expect(screen.getByLabelText('شرح آیتم')).toHaveValue('جاکلیدی تستی');
    expect(screen.getByLabelText('قیمت واحد (تومان)')).toHaveValue(30000);

    await user.click(screen.getByRole('button', { name: 'ذخیره' }));

    await waitFor(() => expect(commerceApiMock.createStaffInvoice).toHaveBeenCalledTimes(1));
    const payload = commerceApiMock.createStaffInvoice.mock.calls[0][0];
    expect(payload.request_id).toBe(5);
    expect(payload.items[0]).toEqual({
      product_id: 12,
      description: 'جاکلیدی تستی',
      qty: 2,
      unit_toman: 30000,
    });
  });
});

// ── approve / copy / revoke ──────────────────────────────────────────

describe('CommerceAdmin approval and link lifecycle', () => {
  it('approves an invoice, shows the share link and copies it without auto-sending', async () => {
    const shareUrl = 'https://spaghettiprints.ir/pay/RAWTOKEN123';
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [makeInvoice()] });
    commerceApiMock.approveStaffInvoice.mockResolvedValue({
      data: { id: 9, state: 'approved', revision: 1, share_url: shareUrl, expires_at: '2026-10-17T08:00:00Z' },
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /تأیید و صدور لینک/ }));

    await waitFor(() => expect(commerceApiMock.approveStaffInvoice).toHaveBeenCalledWith(9));
    await screen.findByText(shareUrl);

    await user.click(screen.getByRole('button', { name: /کپی لینک/ }));
    // user-event.setup() installs its own clipboard stub; read the copied value
    // back from it to prove the share link reaches the clipboard.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /کپی شد/ })).toBeInTheDocument()
    );
    expect(await navigator.clipboard.readText()).toBe(shareUrl);

    // The link is only ever surfaced for staff to paste manually.
    expect(window.open).not.toHaveBeenCalled();
  });

  it('revokes the link and shows a revoked state', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [makeInvoice({ state: 'approved', has_active_link: true })],
    });
    commerceApiMock.revokeStaffInvoice.mockResolvedValue({
      data: makeInvoice({ state: 'revoked', has_active_link: false, revoked_at: '2026-10-10T09:00:00Z' }),
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^لغو لینک$/ }));

    await waitFor(() => expect(commerceApiMock.revokeStaffInvoice).toHaveBeenCalledWith(9));
    expect(await screen.findByText('لغو‌شده')).toBeInTheDocument();
  });

  it('re-editing an approved invoice revises it back to draft and clears the link', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [makeInvoice({ state: 'approved', has_active_link: true, revision: 1 })],
    });
    commerceApiMock.updateStaffInvoice.mockResolvedValue({
      data: makeInvoice({ state: 'draft', revision: 2, has_active_link: false }),
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^ویرایش$/ }));

    // Editing an approved invoice is gated behind a confirmation first.
    const confirmDialog = await screen.findByRole('dialog');
    await user.click(within(confirmDialog).getByRole('button', { name: /ادامه و ویرایش/ }));

    const priceField = await screen.findByLabelText('قیمت واحد (تومان)');
    await user.clear(priceField);
    await user.type(priceField, '60000');
    await user.click(screen.getByRole('button', { name: 'ذخیره' }));

    await waitFor(() => expect(commerceApiMock.updateStaffInvoice).toHaveBeenCalledTimes(1));
    expect(commerceApiMock.updateStaffInvoice.mock.calls[0][0]).toBe(9);
    expect(await screen.findByText('پیش‌نویس')).toBeInTheDocument();
  });
});

// ── explicit paid / expired states ───────────────────────────────────

describe('CommerceAdmin invoice states', () => {
  it('shows paid, expired and revoked invoices distinctly with no approve action', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [
        makeInvoice({ id: 30, customer_name: 'مشتری الف', state: 'paid' }),
        makeInvoice({ id: 31, customer_name: 'مشتری ب', state: 'approved', has_active_link: false }),
        makeInvoice({ id: 32, customer_name: 'مشتری ج', state: 'revoked' }),
      ],
    });

    renderPage();

    expect(await screen.findByText('پرداخت‌شده')).toBeInTheDocument();
    expect(screen.getByText('منقضی‌شده')).toBeInTheDocument();
    expect(screen.getByText('لغو‌شده')).toBeInTheDocument();
    // A paid invoice can never be re-approved or edited.
    expect(screen.queryByRole('button', { name: /تأیید و صدور لینک/ })).toBeNull();
  });

  it('surfaces the server error message when creation fails', async () => {
    commerceApiMock.createStaffInvoice.mockRejectedValue({
      response: { data: { detail: 'مبلغ کل فاکتور بیش از حد مجاز است' } },
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /فاکتور جدید/ }));
    await user.type(screen.getByLabelText(/نام مشتری/), 'علی');
    await user.type(screen.getByLabelText(/شماره موبایل/), '09121112233');
    await user.type(screen.getByLabelText('شرح آیتم'), 'قطعه');
    await user.type(screen.getByLabelText('قیمت واحد (تومان)'), '50000');
    await user.click(screen.getByRole('button', { name: 'ذخیره' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('مبلغ کل فاکتور بیش از حد مجاز است');
  });
});

// ── catalogue attach price seeding ───────────────────────────────────

describe('CommerceAdmin catalogue attach', () => {
  it('seeds the unit price from final_price when suggested_price is zero', async () => {
    apiMock.getProductsAll.mockResolvedValue({
      data: [
        { id: 7, name: 'محصول بدون قیمت پیشنهادی', suggested_price: 0, final_price: 45000, is_active: true },
      ],
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /فاکتور جدید/ }));
    await user.type(await screen.findByLabelText('شرح آیتم'), 'محصول');

    const option = await screen.findByRole('button', { name: /محصول بدون قیمت پیشنهادی/ });
    await user.click(option);

    // A zero suggested_price must NOT price the line at 0 — final_price wins.
    expect(screen.getByLabelText('قیمت واحد (تومان)')).toHaveValue(45000);
  });

  it('keeps a typed price when the catalogue product has no usable price', async () => {
    apiMock.getProductsAll.mockResolvedValue({
      data: [{ id: 8, name: 'محصول بی‌قیمت', suggested_price: 0, final_price: 0, is_active: true }],
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /فاکتور جدید/ }));
    await user.type(await screen.findByLabelText('قیمت واحد (تومان)'), '12345');

    await user.type(await screen.findByLabelText('شرح آیتم'), 'بی');
    const option = await screen.findByRole('button', { name: /محصول بی‌قیمت/ });
    await user.click(option);

    expect(screen.getByLabelText('قیمت واحد (تومان)')).toHaveValue(12345);
  });
});

// ── invoice queue pagination ─────────────────────────────────────────

describe('CommerceAdmin invoice queue', () => {
  it('loads more invoices when the first page is full', async () => {
    const firstPage = Array.from({ length: INVOICES_PAGE_SIZE }, (_, i) =>
      makeInvoice({ id: i + 1, customer_name: `فاکتور ${i + 1}` })
    );
    const secondPage = [makeInvoice({ id: 9000, customer_name: 'فاکتور آخر' })];
    commerceApiMock.getStaffInvoices.mockImplementation(({ offset } = {}) =>
      Promise.resolve({ data: offset === 0 ? firstPage : secondPage })
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('فاکتور 1');
    expect(commerceApiMock.getStaffInvoices).toHaveBeenLastCalledWith({
      limit: INVOICES_PAGE_SIZE,
      offset: 0,
    });

    await user.click(screen.getByRole('button', { name: /بارگذاری بیشتر/ }));

    await screen.findByText('فاکتور آخر');
    expect(commerceApiMock.getStaffInvoices).toHaveBeenLastCalledWith({
      limit: INVOICES_PAGE_SIZE,
      offset: INVOICES_PAGE_SIZE,
    });
    // A short page means the invoice queue is exhausted.
    expect(screen.queryByRole('button', { name: /بارگذاری بیشتر/ })).toBeNull();
  });
});

// ── confirmation before invalidating a shared link ───────────────────

describe('CommerceAdmin edit confirmation', () => {
  it('requires confirmation before editing an approved invoice with a live link', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [makeInvoice({ state: 'approved', has_active_link: true })],
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^ویرایش$/ }));

    // The editor must not open before staff confirm the link will be voided.
    expect(screen.queryByLabelText(/نام مشتری/)).toBeNull();

    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toMatch(/لینک/);

    await user.click(within(dialog).getByRole('button', { name: /ادامه و ویرایش/ }));

    expect(await screen.findByLabelText(/نام مشتری/)).toHaveValue('سارا');
  });

  it('cancelling the confirmation leaves the invoice untouched', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({
      data: [makeInvoice({ state: 'approved', has_active_link: true })],
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^ویرایش$/ }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'انصراف' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.queryByLabelText(/نام مشتری/)).toBeNull();
    expect(commerceApiMock.updateStaffInvoice).not.toHaveBeenCalled();
  });

  it('opens the editor directly for a draft invoice with no confirm step', async () => {
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [makeInvoice({ state: 'draft' })] });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^ویرایش$/ }));

    expect(await screen.findByLabelText(/نام مشتری/)).toHaveValue('سارا');
  });
});

// ── async status announcements ───────────────────────────────────────

describe('CommerceAdmin status announcements', () => {
  it('announces copy in a polite live region and resets the copied affordance', async () => {
    const shareUrl = 'https://spaghettiprints.ir/pay/RAWTOKEN999';
    commerceApiMock.getStaffInvoices.mockResolvedValue({ data: [makeInvoice()] });
    commerceApiMock.approveStaffInvoice.mockResolvedValue({
      data: { id: 9, state: 'approved', revision: 1, share_url: shareUrl, expires_at: '2026-10-17T08:00:00Z' },
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /تأیید و صدور لینک/ }));
    await screen.findByText(shareUrl);

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status.textContent).toContain('لینک'));

    await user.click(screen.getByRole('button', { name: /کپی لینک/ }));
    await screen.findByRole('button', { name: /کپی شد/ });
    await waitFor(() => expect(status.textContent).toContain('کپی'));

    // The copied indicator must not stick forever.
    await waitFor(
      () => expect(screen.getByRole('button', { name: /کپی لینک/ })).toBeInTheDocument(),
      { timeout: COPY_RESET_MS + 1500 }
    );
  });
});

