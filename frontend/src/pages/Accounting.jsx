/**
 * دفتر حسابداری — accounting ledger (P&L) management page.
 *
 * Cash-basis view over `/api/v1/accounting/*`:
 *  • KPI cards (income / expense / net profit / margin) driven by `summary`
 *  • Shamsi period switcher + type / category / search filters
 *  • Ledger table with invoice-linked guardrails (frozen amount & account,
 *    no delete) that mirror the backend's `LINKED_UPDATE_FIELDS` rules
 *  • Add-expense / add-income / edit modal, chart-of-accounts modal, CSV export
 *
 * Storage/API stay Gregorian ISO YYYY-MM-DD; the UI shows and edits Shamsi.
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Landmark,
  TrendingUp,
  TrendingDown,
  Wallet,
  Percent,
  Plus,
  Tags,
  Download,
  Search,
  Edit2,
  Trash2,
  Paperclip,
  Upload,
  X,
} from 'lucide-react';
import { toJalaali, toGregorian } from 'jalaali-js';
import {
  getAccountingCategories,
  createAccountingCategory,
  updateAccountingCategory,
  deleteAccountingCategory,
  getAccountingTransactions,
  createAccountingTransaction,
  updateAccountingTransaction,
  deleteAccountingTransaction,
  getAccountingSummary,
  uploadAccountingAttachment,
  getAccountingExportUrl,
} from '../lib/api';
import { formatPrice } from '../lib/utils';
import {
  formatShamsiDate,
  gregorianIsoToShamsi,
  shamsiToGregorianIso,
  todayGregorianIso,
} from '../lib/shamsi';
import Modal from '../components/Modal';
import ShamsiDateField from '../components/ShamsiDateField';
import StatCard from '../components/StatCard';

const pad2 = (n) => String(n).padStart(2, '0');

const PERIOD_OPTIONS = [
  { value: 'current_month', label: 'ماه جاری' },
  { value: 'last_3_months', label: '۳ ماه اخیر' },
  { value: 'current_year', label: 'سال جاری' },
  { value: 'custom', label: 'بازه دلخواه' },
];

const TYPE_FILTERS = [
  { value: '', label: 'همه' },
  { value: 'income', label: 'درآمدها' },
  { value: 'expense', label: 'هزینه‌ها' },
];

const ACCOUNT_TYPES = [
  { value: 'bank', label: 'بانک' },
  { value: 'cash', label: 'صندوق نقدی' },
  { value: 'gateway', label: 'درگاه آنلاین' },
  { value: 'other', label: 'سایر' },
];

const ACCOUNT_TYPE_LABELS = ACCOUNT_TYPES.reduce(
  (acc, item) => ({ ...acc, [item.value]: item.label }),
  {}
);

const TYPE_LABELS = { income: 'درآمد', expense: 'هزینه' };

const TYPE_BADGE_STYLE = {
  income: { backgroundColor: 'rgba(34,197,94,0.15)', color: '#16a34a' },
  expense: { backgroundColor: 'rgba(239,68,68,0.15)', color: '#ef4444' },
};

const SOFT_BADGE = {
  backgroundColor: 'var(--bg-tertiary)',
  color: 'var(--text-secondary)',
};

const NUMBER_INPUT_PROPS = { inputMode: 'numeric', min: 0, step: 1 };

/** Today in the Jalali calendar. */
function jalaaliToday() {
  const [gy, gm, gd] = todayGregorianIso().split('-').map(Number);
  return toJalaali(gy, gm, gd);
}

function gregorianFromJalaali(jy, jm, jd) {
  const { gy, gm, gd } = toGregorian(jy, jm, jd);
  return `${gy}-${pad2(gm)}-${pad2(gd)}`;
}

/**
 * Shamsi period preset → inclusive Gregorian ISO range.
 * Custom ranges come from the two Shamsi date fields (empty = open end).
 */
export function periodToRange(period, custom = {}) {
  if (period === 'custom') {
    return {
      start_date: shamsiToGregorianIso(custom.start) || '',
      end_date: shamsiToGregorianIso(custom.end) || '',
    };
  }
  const today = todayGregorianIso();
  const { jy, jm } = jalaaliToday();
  if (period === 'current_year') {
    return { start_date: gregorianFromJalaali(jy, 1, 1), end_date: today };
  }
  if (period === 'last_3_months') {
    let year = jy;
    let month = jm - 2;
    while (month <= 0) {
      month += 12;
      year -= 1;
    }
    return { start_date: gregorianFromJalaali(year, month, 1), end_date: today };
  }
  return { start_date: gregorianFromJalaali(jy, jm, 1), end_date: today };
}

/** Drop empty filter entries so the query string stays clean. */
function compactParams(params) {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  );
}

const emptyForm = (type, defaultCategoryId = '') => ({
  type,
  title: '',
  category_id: defaultCategoryId,
  amount_toman: '',
  transaction_date: gregorianIsoToShamsi(todayGregorianIso()),
  account_type: 'bank',
  reference_code: '',
  description: '',
  attachment_url: '',
});

export default function Accounting() {
  const [summary, setSummary] = useState({});
  const [transactions, setTransactions] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  // ── Filters ──
  const [period, setPeriod] = useState('current_month');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // ── Transaction modal ──
  const [txnModalOpen, setTxnModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm('expense'));
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  // ── Categories modal ──
  const [catModalOpen, setCatModalOpen] = useState(false);
  const [catError, setCatError] = useState('');
  const [newCat, setNewCat] = useState({ name: '', type: 'expense' });
  const [editingCatId, setEditingCatId] = useState(null);
  const [editingCatName, setEditingCatName] = useState('');

  const range = useMemo(
    () => periodToRange(period, { start: customStart, end: customEnd }),
    [period, customStart, customEnd]
  );

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const loadCategories = useCallback(async () => {
    try {
      const res = await getAccountingCategories();
      const list = Array.isArray(res.data) ? res.data : [];
      setCategories(list);
      return list;
    } catch (err) {
      console.error(err);
      return [];
    }
  }, []);

  const loadSummary = useCallback(async () => {
    try {
      const res = await getAccountingSummary(compactParams(range));
      setSummary(res.data || {});
    } catch (err) {
      console.error(err);
      setLoadError('خطا در بارگذاری خلاصه حساب‌ها');
    }
  }, [range]);

  const loadTransactions = useCallback(async () => {
    try {
      const res = await getAccountingTransactions(
        compactParams({
          ...range,
          type: typeFilter,
          category_id: categoryFilter,
          search: debouncedSearch,
          limit: 50,
          offset: 0,
        })
      );
      setTransactions(Array.isArray(res.data?.items) ? res.data.items : []);
      setTotalCount(Number(res.data?.total_count) || 0);
    } catch (err) {
      console.error(err);
      setLoadError('خطا در بارگذاری تراکنش‌ها');
    }
  }, [range, typeFilter, categoryFilter, debouncedSearch]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      await Promise.all([loadSummary(), loadTransactions(), loadCategories()]);
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSummary, loadTransactions, loadCategories]);

  /** Reload everything after a write. */
  const reload = async () => {
    await Promise.all([loadSummary(), loadTransactions()]);
  };

  // ── Transactions ──
  const openAdd = (type) => {
    const firstMatch = categories.find((c) => c.type === type);
    setEditing(null);
    setFormError('');
    setForm(emptyForm(type, firstMatch ? firstMatch.id : ''));
    setTxnModalOpen(true);
  };

  const openEdit = (txn) => {
    setEditing(txn);
    setFormError('');
    setForm({
      type: txn.type,
      title: txn.title || '',
      category_id: txn.category_id ?? '',
      amount_toman: txn.amount_toman ?? '',
      transaction_date: gregorianIsoToShamsi(txn.transaction_date),
      account_type: txn.account_type || 'bank',
      reference_code: txn.reference_code || '',
      description: txn.description || '',
      attachment_url: txn.attachment_url || '',
    });
    setTxnModalOpen(true);
  };

  const isLinked = Boolean(editing && (editing.is_invoice_linked || editing.invoice_id != null));

  const categoriesForForm = useMemo(
    () => categories.filter((c) => c.type === form.type),
    [categories, form.type]
  );

  const setField = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  const handleTypeChange = (value) => {
    setForm((prev) => {
      const stillValid = categories.some(
        (c) => c.id === Number(prev.category_id) && c.type === value
      );
      return {
        ...prev,
        type: value,
        category_id: stillValid ? prev.category_id : '',
      };
    });
  };

  const handleAttachment = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFormError('');
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadAccountingAttachment(fd);
      setField('attachment_url', res.data?.attachment_url || '');
    } catch (err) {
      setFormError(err.response?.data?.detail || 'خطا در بارگذاری فایل رسید');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setFormError('');

    const transactionDate = shamsiToGregorianIso(form.transaction_date);
    if (!form.title.trim()) {
      setFormError('عنوان تراکنش نمی‌تواند خالی باشد');
      return;
    }
    if (!form.category_id) {
      setFormError('انتخاب سرفصل الزامی است');
      return;
    }
    if (!form.amount_toman || Number(form.amount_toman) <= 0) {
      setFormError('مبلغ باید بزرگ‌تر از صفر باشد');
      return;
    }
    if (!transactionDate) {
      setFormError('تاریخ تراکنش نامعتبر است');
      return;
    }

    // An invoice-linked booking only allows these four fields through; the
    // frozen ones are omitted entirely rather than echoed back.
    const editable = {
      category_id: Number(form.category_id),
      reference_code: form.reference_code,
      description: form.description,
      attachment_url: form.attachment_url || null,
    };
    const payload = isLinked
      ? editable
      : {
          ...editable,
          title: form.title.trim(),
          type: form.type,
          amount_toman: Number(form.amount_toman),
          transaction_date: transactionDate,
          account_type: form.account_type,
        };

    setSaving(true);
    try {
      if (editing) {
        await updateAccountingTransaction(editing.id, payload);
      } else {
        await createAccountingTransaction(payload);
      }
      setTxnModalOpen(false);
      setEditing(null);
      await reload();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'خطا در ذخیره تراکنش');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (txn) => {
    if (txn.is_invoice_linked || txn.invoice_id != null) return;
    if (!confirm(`آیا از حذف تراکنش «${txn.title}» مطمئن هستید؟`)) return;
    try {
      await deleteAccountingTransaction(txn.id);
      await reload();
    } catch (err) {
      alert(err.response?.data?.detail || 'خطا در حذف تراکنش');
    }
  };

  const handleExport = () => {
    const url = getAccountingExportUrl(
      compactParams({
        ...range,
        type: typeFilter,
        category_id: categoryFilter,
        search: debouncedSearch,
      })
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'accounting_transactions.csv';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  // ── Categories ──
  const handleCreateCategory = async (event) => {
    event.preventDefault();
    setCatError('');
    if (!newCat.name.trim()) {
      setCatError('نام سرفصل نمی‌تواند خالی باشد');
      return;
    }
    try {
      await createAccountingCategory({ name: newCat.name.trim(), type: newCat.type });
      setNewCat({ name: '', type: newCat.type });
      await loadCategories();
    } catch (err) {
      setCatError(err.response?.data?.detail || 'خطا در ثبت سرفصل');
    }
  };

  const handleRenameCategory = async (category) => {
    setCatError('');
    try {
      await updateAccountingCategory(category.id, { name: editingCatName.trim() });
      setEditingCatId(null);
      setEditingCatName('');
      await loadCategories();
    } catch (err) {
      setCatError(err.response?.data?.detail || 'خطا در ویرایش سرفصل');
    }
  };

  const handleArchiveCategory = async (category) => {
    setCatError('');
    if (category.is_system) return;
    if (!confirm(`آیا از بایگانی سرفصل «${category.name}» مطمئن هستید؟`)) return;
    try {
      await deleteAccountingCategory(category.id);
      await loadCategories();
    } catch (err) {
      setCatError(err.response?.data?.detail || 'خطا در بایگانی سرفصل');
    }
  };

  const marginPct = summary.profit_margin_pct || 0;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
            style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}
          >
            <Landmark size={22} />
          </div>
          <div>
            <h2 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
              دفتر حسابداری
            </h2>
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              درآمد، هزینه و سود خالص کسب‌وکار
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => openAdd('expense')} className="btn-primary">
            <Plus size={16} /> ثبت هزینه جدید
          </button>
          <button type="button" onClick={() => openAdd('income')} className="btn-secondary">
            <Plus size={16} /> ثبت درآمد متفرقه
          </button>
          <button
            type="button"
            onClick={() => {
              setCatError('');
              setCatModalOpen(true);
            }}
            className="btn-secondary"
          >
            <Tags size={16} /> مدیریت سرفصل‌ها
          </button>
          <button type="button" onClick={handleExport} className="btn-secondary">
            <Download size={16} /> خروجی اکسل / CSV
          </button>
        </div>
      </div>

      {/* ── KPI cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          icon={TrendingUp}
          title="درآمد کل"
          value={formatPrice(summary.total_income || 0)}
          color="#22c55e"
        />
        <StatCard
          icon={TrendingDown}
          title="مجموع هزینه‌ها"
          value={formatPrice(summary.total_expense || 0)}
          color="#f43f5e"
        />
        <StatCard
          icon={Wallet}
          title="سود خالص"
          value={formatPrice(summary.net_profit || 0)}
          color="#3b82f6"
        />
        <StatCard
          icon={Percent}
          title="حاشیه سود"
          color="#10b981"
          value={
            <span
              className="text-sm font-bold inline-block px-2.5 py-1 rounded-lg"
              style={{ backgroundColor: 'rgba(16,185,129,0.15)', color: '#10b981' }}
              data-testid="profit-margin-badge"
            >
              {marginPct}%
            </span>
          }
        />
      </div>

      {/* ── Filters ── */}
      <div className="card p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <div>
            <label htmlFor="acct-period" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              بازه زمانی
            </label>
            <select
              id="acct-period"
              className="select-field"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              {PERIOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="acct-type" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              نوع تراکنش
            </label>
            <select
              id="acct-type"
              className="select-field"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              {TYPE_FILTERS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="acct-category-filter" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              سرفصل
            </label>
            <select
              id="acct-category-filter"
              className="select-field"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              <option value="">همه سرفصل‌ها</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="acct-search" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              جستجو
            </label>
            <div className="relative">
              <Search
                size={16}
                className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"
                style={{ color: 'var(--text-muted)' }}
              />
              <input
                id="acct-search"
                type="search"
                className="input-field pr-9"
                placeholder="عنوان یا شماره پیگیری"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
        </div>

        {period === 'custom' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
            <div>
              <label htmlFor="acct-from" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                از تاریخ
              </label>
              <ShamsiDateField id="acct-from" value={customStart} onChange={setCustomStart} aria-label="از تاریخ" />
            </div>
            <div>
              <label htmlFor="acct-to" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                تا تاریخ
              </label>
              <ShamsiDateField id="acct-to" value={customEnd} onChange={setCustomEnd} aria-label="تا تاریخ" />
            </div>
          </div>
        )}
      </div>

      {/* ── Ledger table ── */}
      <div className="card p-0 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="font-semibold" style={{ color: 'var(--text-primary)' }}>
            تراکنش‌ها
          </h3>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {totalCount} مورد
          </span>
        </div>

        {loadError && (
          <p className="px-4 py-3 text-sm" style={{ color: 'var(--danger)' }}>
            {loadError}
          </p>
        )}

        {loading ? (
          <p className="px-4 py-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            در حال بارگذاری...
          </p>
        ) : transactions.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            تراکنشی با این فیلترها یافت نشد
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                  <th className="text-right px-3 py-2.5 font-medium">تاریخ</th>
                  <th className="text-right px-3 py-2.5 font-medium">عنوان</th>
                  <th className="text-right px-3 py-2.5 font-medium">سرفصل</th>
                  <th className="text-right px-3 py-2.5 font-medium">نوع</th>
                  <th className="text-right px-3 py-2.5 font-medium">مبلغ (تومان)</th>
                  <th className="text-right px-3 py-2.5 font-medium">حساب / صندوق</th>
                  <th className="text-right px-3 py-2.5 font-medium">شماره پیگیری</th>
                  <th className="text-right px-3 py-2.5 font-medium">فاکتور متصل</th>
                  <th className="text-right px-3 py-2.5 font-medium">رسید</th>
                  <th className="text-right px-3 py-2.5 font-medium">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((txn) => {
                  const linked = Boolean(txn.is_invoice_linked || txn.invoice_id != null);
                  return (
                    <tr key={txn.id} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                        {formatShamsiDate(txn.transaction_date)}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--text-primary)' }}>
                        {txn.title}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--text-secondary)' }}>
                        {txn.category_name || '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className="text-xs font-semibold px-2 py-0.5 rounded-lg whitespace-nowrap"
                          style={TYPE_BADGE_STYLE[txn.type] || SOFT_BADGE}
                        >
                          {txn.type_label || TYPE_LABELS[txn.type] || txn.type}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                        {formatPrice(txn.amount_toman)}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--text-secondary)' }}>
                        {txn.account_type_label || ACCOUNT_TYPE_LABELS[txn.account_type] || '—'}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: 'var(--text-secondary)' }}>
                        {txn.reference_code || '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        {txn.invoice_id != null ? (
                          <span
                            className="text-xs font-semibold px-2 py-0.5 rounded-lg whitespace-nowrap"
                            style={{ backgroundColor: 'rgba(99,102,241,0.15)', color: '#6366f1' }}
                          >
                            #فاکتور {txn.invoice_id}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {txn.attachment_url ? (
                          <a
                            href={txn.attachment_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs"
                            style={{ color: 'var(--accent)' }}
                          >
                            <Paperclip size={13} /> مشاهده رسید
                          </a>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => openEdit(txn)}
                            className="p-1.5 rounded-lg"
                            style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
                            title="ویرایش"
                            aria-label={`ویرایش تراکنش ${txn.title}`}
                          >
                            <Edit2 size={14} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(txn)}
                            disabled={linked}
                            className="p-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
                            style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--danger)' }}
                            title={linked ? 'تراکنش متصل به فاکتور قابل حذف نیست' : 'حذف'}
                            aria-label={`حذف تراکنش ${txn.title}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Add / edit transaction ── */}
      <Modal
        isOpen={txnModalOpen}
        onClose={() => {
          setTxnModalOpen(false);
          setEditing(null);
        }}
        title={
          editing
            ? `ویرایش تراکنش #${editing.id}`
            : form.type === 'income'
              ? 'ثبت درآمد متفرقه'
              : 'ثبت هزینه جدید'
        }
        size="lg"
      >
        {isLinked && (
          <div
            className="text-xs mb-4 px-3 py-2.5 rounded-lg leading-6"
            style={{ backgroundColor: 'rgba(99,102,241,0.12)', color: 'var(--text-primary)' }}
          >
            {`این تراکنش متصل به فاکتور #${editing?.invoice_id} است و مبلغ و اطلاعات حساب آن غیرقابل تغییر است.`}
          </div>
        )}

        {formError && (
          <div
            className="text-sm mb-3 py-2 rounded-lg text-center"
            style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--danger)' }}
          >
            {formError}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="acct-form-type" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                نوع تراکنش
              </label>
              <select
                id="acct-form-type"
                className="select-field"
                value={form.type}
                disabled={isLinked}
                onChange={(e) => handleTypeChange(e.target.value)}
              >
                <option value="expense">هزینه</option>
                <option value="income">درآمد</option>
              </select>
            </div>

            <div>
              <label htmlFor="acct-form-account" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                حساب / صندوق
              </label>
              <select
                id="acct-form-account"
                className="select-field"
                value={form.account_type}
                disabled={isLinked}
                onChange={(e) => setField('account_type', e.target.value)}
              >
                {ACCOUNT_TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="acct-form-title" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              عنوان
            </label>
            <input
              id="acct-form-title"
              type="text"
              className="input-field"
              value={form.title}
              disabled={isLinked}
              onChange={(e) => setField('title', e.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="acct-form-category" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                سرفصل
              </label>
              <select
                id="acct-form-category"
                className="select-field"
                value={form.category_id}
                onChange={(e) => setField('category_id', e.target.value)}
              >
                <option value="">— انتخاب سرفصل —</option>
                {categoriesForForm.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="acct-form-amount" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                مبلغ به تومان
              </label>
              <input
                id="acct-form-amount"
                type="number"
                className="input-field"
                value={form.amount_toman}
                disabled={isLinked}
                onChange={(e) => setField('amount_toman', e.target.value)}
                {...NUMBER_INPUT_PROPS}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="acct-form-date" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                تاریخ تراکنش
              </label>
              <ShamsiDateField
                id="acct-form-date"
                value={form.transaction_date}
                onChange={(value) => setField('transaction_date', value)}
                disabled={isLinked}
                aria-label="تاریخ تراکنش"
              />
            </div>

            <div>
              <label htmlFor="acct-form-reference" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                شماره پیگیری
              </label>
              <input
                id="acct-form-reference"
                type="text"
                className="input-field"
                value={form.reference_code}
                onChange={(e) => setField('reference_code', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label htmlFor="acct-form-description" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              توضیحات
            </label>
            <textarea
              id="acct-form-description"
              className="input-field"
              rows={3}
              value={form.description}
              onChange={(e) => setField('description', e.target.value)}
            />
          </div>

          <div>
            <label htmlFor="acct-form-attachment" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              پیوست رسید
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <label
                htmlFor="acct-form-attachment"
                className="btn-secondary cursor-pointer"
                style={{ marginBottom: 0 }}
              >
                <Upload size={15} /> {uploading ? 'در حال بارگذاری...' : 'انتخاب فایل'}
              </label>
              <input
                id="acct-form-attachment"
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.pdf"
                className="hidden"
                onChange={handleAttachment}
                disabled={uploading}
              />
              {form.attachment_url ? (
                <span className="inline-flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
                  <Paperclip size={13} />
                  <a href={form.attachment_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
                    مشاهده رسید
                  </a>
                  <button
                    type="button"
                    onClick={() => setField('attachment_url', '')}
                    aria-label="حذف پیوست"
                    className="p-1 rounded-md"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    <X size={13} />
                  </button>
                </span>
              ) : (
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  تصویر jpg، png، webp یا فایل pdf — حداکثر ۵ مگابایت
                </span>
              )}
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="submit" className="btn-primary flex-1 justify-center" disabled={saving || uploading}>
              {saving ? 'در حال ذخیره...' : editing ? 'ذخیره تغییرات' : 'ثبت تراکنش'}
            </button>
            <button
              type="button"
              className="btn-secondary flex-1 justify-center"
              onClick={() => {
                setTxnModalOpen(false);
                setEditing(null);
              }}
            >
              انصراف
            </button>
          </div>
        </form>
      </Modal>

      {/* ── Chart of accounts ── */}
      <Modal isOpen={catModalOpen} onClose={() => setCatModalOpen(false)} title="مدیریت سرفصل‌ها" size="xl">
        {catError && (
          <div
            className="text-sm mb-3 py-2 rounded-lg text-center"
            style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--danger)' }}
          >
            {catError}
          </div>
        )}

        <form onSubmit={handleCreateCategory} className="flex flex-wrap items-end gap-3 pb-4 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex-1 min-w-[180px]">
            <label htmlFor="acct-new-category" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              نام سرفصل جدید
            </label>
            <input
              id="acct-new-category"
              type="text"
              className="input-field"
              value={newCat.name}
              onChange={(e) => setNewCat({ ...newCat, name: e.target.value })}
            />
          </div>
          <div className="min-w-[140px]">
            <label htmlFor="acct-new-category-type" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              نوع
            </label>
            <select
              id="acct-new-category-type"
              className="select-field"
              value={newCat.type}
              onChange={(e) => setNewCat({ ...newCat, type: e.target.value })}
            >
              <option value="expense">هزینه</option>
              <option value="income">درآمد</option>
            </select>
          </div>
          <button type="submit" className="btn-primary">
            <Plus size={15} /> افزودن سرفصل
          </button>
        </form>

        {categories.length === 0 ? (
          <p className="py-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            سرفصلی ثبت نشده است
          </p>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
            {categories.map((category) => (
              <li
                key={category.id}
                className="flex flex-wrap items-center justify-between gap-2 py-3 border-b"
                style={{ borderColor: 'var(--border-color)' }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {editingCatId === category.id ? (
                    <input
                      type="text"
                      className="input-field"
                      value={editingCatName}
                      aria-label={`نام جدید سرفصل ${category.name}`}
                      onChange={(e) => setEditingCatName(e.target.value)}
                    />
                  ) : (
                    <span className="font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                      {category.name}
                    </span>
                  )}
                  <span
                    className="text-xs font-semibold px-2 py-0.5 rounded-lg whitespace-nowrap"
                    style={TYPE_BADGE_STYLE[category.type] || SOFT_BADGE}
                  >
                    {TYPE_LABELS[category.type] || category.type}
                  </span>
                  {category.is_system && (
                    <span
                      className="text-xs px-2 py-0.5 rounded-lg whitespace-nowrap"
                      style={SOFT_BADGE}
                    >
                      سیستمی
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1.5">
                  {editingCatId === category.id ? (
                    <>
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() => handleRenameCategory(category)}
                      >
                        ذخیره
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => {
                          setEditingCatId(null);
                          setEditingCatName('');
                        }}
                      >
                        انصراف
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="p-1.5 rounded-lg"
                      style={{ backgroundColor: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
                      title={category.is_system ? 'سرفصل‌های سیستمی قابل ویرایش نیستند' : 'ویرایش نام'}
                      aria-label={`ویرایش سرفصل ${category.name}`}
                      disabled={category.is_system}
                      onClick={() => {
                        setEditingCatId(category.id);
                        setEditingCatName(category.name);
                      }}
                    >
                      <Edit2 size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="p-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ backgroundColor: 'rgba(239,68,68,0.08)', color: 'var(--danger)' }}
                    title={category.is_system ? 'سرفصل‌های سیستمی قابل حذف نیستند' : 'بایگانی سرفصل'}
                    aria-label={`حذف سرفصل ${category.name}`}
                    disabled={category.is_system}
                    onClick={() => handleArchiveCategory(category)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </div>
  );
}
