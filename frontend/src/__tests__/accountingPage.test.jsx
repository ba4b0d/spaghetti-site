// @vitest-environment jsdom
/**
 * Accounting page contract: KPI summary, ledger table, add-expense modal and
 * chart-of-accounts modal — plus the invoice-linked immutability guardrail the
 * backend enforces (frozen amount/account, no delete, four editable fields).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Accounting from '../pages/Accounting';
import { formatPrice } from '../lib/utils';
import {
  getAccountingCategories,
  getAccountingTransactions,
  getAccountingSummary,
  createAccountingTransaction,
  updateAccountingTransaction,
  deleteAccountingTransaction,
  createAccountingCategory,
  uploadAccountingAttachment,
  getAccountingExportUrl,
} from '../lib/api';

vi.mock('../lib/api', () => ({
  getAccountingCategories: vi.fn(),
  createAccountingCategory: vi.fn(),
  updateAccountingCategory: vi.fn(),
  deleteAccountingCategory: vi.fn(),
  getAccountingTransactions: vi.fn(),
  createAccountingTransaction: vi.fn(),
  updateAccountingTransaction: vi.fn(),
  deleteAccountingTransaction: vi.fn(),
  getAccountingSummary: vi.fn(),
  uploadAccountingAttachment: vi.fn(),
  getAccountingExportUrl: vi.fn(() => '/api/v1/accounting/export'),
}));

const ok = (data) => Promise.resolve({ data });

const categories = [
  { id: 1, name: 'فروش محصولات', type: 'income', is_system: true, is_active: true },
  { id: 2, name: 'خرید مواد اولیه', type: 'expense', is_system: true, is_active: true },
  { id: 3, name: 'اجاره کارگاه', type: 'expense', is_system: false, is_active: true },
];

const summary = {
  total_income: 1500000,
  total_expense: 500000,
  net_profit: 1000000,
  profit_margin_pct: 66.67,
  transaction_count: 2,
};

const manualExpense = {
  id: 10,
  title: 'خرید فیلامنت PLA',
  category_id: 2,
  category_name: 'خرید مواد اولیه',
  category_type: 'expense',
  type: 'expense',
  type_label: 'هزینه',
  amount_toman: 500000,
  transaction_date: '2026-10-01',
  account_type: 'bank',
  account_type_label: 'بانک',
  reference_code: 'REF-1',
  description: 'خرید ماهانه',
  attachment_url: '/uploads/accounting/receipt-1.pdf',
  invoice_id: null,
  is_invoice_linked: false,
};

const invoiceLinkedIncome = {
  id: 11,
  title: 'پرداخت فاکتور فروش',
  category_id: 1,
  category_name: 'فروش محصولات',
  category_type: 'income',
  type: 'income',
  type_label: 'درآمد',
  amount_toman: 1500000,
  transaction_date: '2026-10-05',
  account_type: 'gateway',
  account_type_label: 'درگاه آنلاین',
  reference_code: 'TRX-9',
  description: '',
  attachment_url: null,
  invoice_id: 7,
  is_invoice_linked: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <Accounting />
    </MemoryRouter>
  );
}

describe('Accounting page', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    getAccountingSummary.mockImplementation(() => ok(summary));
    getAccountingCategories.mockImplementation(() => ok(categories));
    getAccountingTransactions.mockImplementation(() =>
      ok({ items: [manualExpense, invoiceLinkedIncome], total_count: 2, has_more: false })
    );
    getAccountingExportUrl.mockReturnValue('/api/v1/accounting/export');
    createAccountingTransaction.mockImplementation((payload) => ok({ id: 99, ...payload }));
    updateAccountingTransaction.mockImplementation((id, payload) => ok({ id, ...payload }));
    deleteAccountingTransaction.mockResolvedValue({ data: { id: 10 } });
    createAccountingCategory.mockImplementation((payload) => ok({ id: 50, ...payload }));
    uploadAccountingAttachment.mockResolvedValue({ data: { attachment_url: '/uploads/accounting/a.pdf' } });
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('alert', vi.fn());
  });

  it('renders the KPI cards with summary amounts and profit margin badge', async () => {
    renderPage();

    expect(await screen.findByText('درآمد کل')).toBeTruthy();
    expect(screen.getByText('مجموع هزینه‌ها')).toBeTruthy();
    expect(screen.getByText('سود خالص')).toBeTruthy();
    expect(screen.getByText('حاشیه سود')).toBeTruthy();

    // Amounts also appear in the table rows, so match any occurrence.
    expect(screen.getAllByText(formatPrice(1500000)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(formatPrice(500000)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(formatPrice(1000000)).length).toBeGreaterThan(0);
    expect(screen.getByTestId('profit-margin-badge').textContent).toBe('66.67%');

    await waitFor(() => expect(getAccountingSummary).toHaveBeenCalled());
    const params = getAccountingSummary.mock.calls[0][0];
    expect(params).toMatchObject({
      start_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      end_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
  });

  it('renders the ledger table with type badges, invoice pill and receipt link', async () => {
    renderPage();

    // The category names also live in the filter dropdown, so scope to the table.
    const table = await screen.findByRole('table');
    expect(within(table).getByText('خرید فیلامنت PLA')).toBeTruthy();
    expect(within(table).getByText('پرداخت فاکتور فروش')).toBeTruthy();

    // Category + account labels resolve from the API payload.
    expect(within(table).getByText('خرید مواد اولیه')).toBeTruthy();
    expect(within(table).getByText('درگاه آنلاین')).toBeTruthy();
    expect(within(table).getByText(formatPrice(500000))).toBeTruthy();

    // Income/expense badges.
    expect(within(table).getAllByText('درآمد').length).toBeGreaterThan(0);
    expect(within(table).getAllByText('هزینه').length).toBeGreaterThan(0);

    // Invoice-linked row shows the invoice pill…
    expect(within(table).getByText('#فاکتور 7')).toBeTruthy();

    // …receipt link points at the stored attachment…
    const receiptLink = screen.getByRole('link', { name: /مشاهده رسید/ });
    expect(receiptLink.getAttribute('href')).toBe('/uploads/accounting/receipt-1.pdf');

    // …and the invoice-linked row's delete button is disabled.
    expect(
      screen.getByRole('button', { name: 'حذف تراکنش پرداخت فاکتور فروش' }).disabled
    ).toBe(true);
    expect(
      screen.getByRole('button', { name: 'حذف تراکنش خرید فیلامنت PLA' }).disabled
    ).toBe(false);
  });

  it('opens the add-expense modal and submits a manual expense', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('خرید فیلامنت PLA');
    await user.click(screen.getByRole('button', { name: /ثبت هزینه جدید/ }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('ثبت هزینه جدید')).toBeTruthy();

    await user.type(within(dialog).getByLabelText('عنوان'), 'خرید فیلامنت PLA');
    await user.type(within(dialog).getByLabelText('مبلغ به تومان'), '250000');
    await user.selectOptions(within(dialog).getByLabelText('سرفصل'), '3');

    await user.click(within(dialog).getByRole('button', { name: 'ثبت تراکنش' }));

    await waitFor(() => expect(createAccountingTransaction).toHaveBeenCalledTimes(1));
    expect(createAccountingTransaction).toHaveBeenCalledWith({
      category_id: 3,
      reference_code: '',
      description: '',
      attachment_url: null,
      title: 'خرید فیلامنت PLA',
      type: 'expense',
      amount_toman: 250000,
      transaction_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      account_type: 'bank',
    });
    // The list is reloaded after a successful write.
    await waitFor(() => expect(getAccountingTransactions.mock.calls.length).toBeGreaterThan(1));
  });

  it('freezes amount, title, account and date when editing an invoice-linked row', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('پرداخت فاکتور فروش');
    await user.click(
      screen.getByRole('button', { name: 'ویرایش تراکنش پرداخت فاکتور فروش' })
    );

    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(
        'این تراکنش متصل به فاکتور #7 است و مبلغ و اطلاعات حساب آن غیرقابل تغییر است.'
      )
    ).toBeTruthy();
    expect(within(dialog).getByLabelText('عنوان').disabled).toBe(true);
    expect(within(dialog).getByLabelText('مبلغ به تومان').disabled).toBe(true);
    expect(within(dialog).getByLabelText('حساب / صندوق').disabled).toBe(true);
    expect(within(dialog).getByLabelText('نوع تراکنش').disabled).toBe(true);
    // Only the four editable fields stay writable.
    expect(within(dialog).getByLabelText('سرفصل').disabled).toBe(false);
    expect(within(dialog).getByLabelText('شماره پیگیری').disabled).toBe(false);
    expect(within(dialog).getByLabelText('توضیحات').disabled).toBe(false);

    await user.type(within(dialog).getByLabelText('توضیحات'), 'تسویه شد');
    await user.click(within(dialog).getByRole('button', { name: 'ذخیره تغییرات' }));

    await waitFor(() => expect(updateAccountingTransaction).toHaveBeenCalledTimes(1));
    const [id, payload] = updateAccountingTransaction.mock.calls[0];
    expect(id).toBe(11);
    // Frozen fields are omitted entirely (never echoed back).
    expect(Object.keys(payload).sort()).toEqual([
      'attachment_url',
      'category_id',
      'description',
      'reference_code',
    ]);
    expect(payload.description).toBe('تسویه شد');
  });

  it('opens the category management modal and lists categories with system badges', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('خرید فیلامنت PLA');
    await user.click(screen.getByRole('button', { name: /مدیریت سرفصل‌ها/ }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('فروش محصولات')).toBeTruthy();
    expect(within(dialog).getByText('خرید مواد اولیه')).toBeTruthy();
    expect(within(dialog).getByText('اجاره کارگاه')).toBeTruthy();
    expect(within(dialog).getAllByText('سیستمی')).toHaveLength(2);

    // System categories cannot be archived; custom ones can.
    expect(within(dialog).getByRole('button', { name: 'حذف سرفصل فروش محصولات' }).disabled).toBe(true);
    expect(within(dialog).getByRole('button', { name: 'حذف سرفصل اجاره کارگاه' }).disabled).toBe(false);

    // Adding a custom category hits the API with the typed name/type.
    await user.type(within(dialog).getByLabelText('نام سرفصل جدید'), 'تعمیرات');
    await user.click(within(dialog).getByRole('button', { name: /افزودن سرفصل/ }));
    await waitFor(() =>
      expect(createAccountingCategory).toHaveBeenCalledWith({ name: 'تعمیرات', type: 'expense' })
    );
  });
});
