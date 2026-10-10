import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Plus,
  Trash2,
  Copy,
  Check,
  Ban,
  FileText,
  Loader2,
  AlertTriangle,
  Link2,
  ArrowLeft,
  Inbox,
} from 'lucide-react';
import { getProductsAll } from '../lib/api';
import {
  getStaffRequests,
  getStaffInvoices,
  createStaffInvoice,
  updateStaffInvoice,
  approveStaffInvoice,
  revokeStaffInvoice,
} from '../lib/commerceApi';
import { formatPrice } from '../lib/utils';
import Modal from '../components/Modal';

/**
 * Staff commerce admin — Task 2.
 *
 * A focused workspace, separate from the legacy Orders board, for the reviewed
 * invoice flow: convert a website request or build a manual draft, then approve
 * to mint a private share link. The link is ONLY surfaced for staff to copy and
 * paste into an existing Telegram/Bale conversation — nothing here ever
 * auto-forwards it to a messenger.
 */

// The staff request queue is paginated (server caps `limit` at 200). We page
// until a short page comes back so a large queue never loads all at once.
export const REQUESTS_PAGE_SIZE = 50;
export const INVOICES_PAGE_SIZE = 100;
// How long the "کپی شد" affordance stays before it resets.
export const COPY_RESET_MS = 2000;

const MESSENGER_OPTIONS = [
  { value: 'telegram', label: 'تلگرام' },
  { value: 'bale', label: 'بله' },
];

const STATE_META = {
  draft: { label: 'پیش‌نویس', color: '#94a3b8', bg: 'rgba(148,163,184,0.15)' },
  approved: { label: 'تأییدشده', color: '#16a34a', bg: 'rgba(34,197,94,0.15)' },
  expired: { label: 'منقضی‌شده', color: '#d97706', bg: 'rgba(245,158,11,0.15)' },
  paid: { label: 'پرداخت‌شده', color: '#0ea5e9', bg: 'rgba(14,165,233,0.15)' },
  revoked: { label: 'لغو‌شده', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
};

const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
const MOBILE_RE = /^09\d{9}$/;

/** Normalise Persian/Arabic-Indic digits to ASCII so ۰۹۱۲… validates. */
function normalizeDigits(value) {
  return String(value ?? '').replace(/[۰-۹٠-٩]/g, (ch) => {
    const fa = PERSIAN_DIGITS.indexOf(ch);
    if (fa > -1) return String(fa);
    const ar = ARABIC_DIGITS.indexOf(ch);
    if (ar > -1) return String(ar);
    return ch;
  });
}

/** Human-readable message from an Axios/FastAPI error. */
function extractError(err) {
  const data = err?.response?.data;
  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'string') return first;
    if (first?.msg) return String(first.msg);
  }
  if (typeof data?.message === 'string' && data.message.trim()) return data.message;
  return 'عملیات ناموفق بود. لطفاً دوباره تلاش کنید.';
}

function isCanceled(err) {
  return err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED';
}

/** Effective display state — an approved invoice past expiry reads as expired. */
function invoiceDisplayState(invoice) {
  if (invoice.state === 'approved' && invoice.has_active_link === false) return 'expired';
  return invoice.state;
}

/**
 * Best catalogue price to seed a line with. Only a POSITIVE price counts: a
 * `suggested_price` of 0 (or null) must fall through to `final_price` instead
 * of silently pricing the line at 0. Returns 0 when neither is usable.
 */
function catalogPrice(product) {
  const suggested = Number(product?.suggested_price);
  if (Number.isFinite(suggested) && suggested > 0) return suggested;
  const final = Number(product?.final_price);
  if (Number.isFinite(final) && final > 0) return final;
  return 0;
}

const emptyForm = {
  customer_name: '',
  mobile: '',
  messenger: 'telegram',
  messenger_handle: '',
  address: '',
  specification: '',
  internal_note: '',
  shipping_toman: '',
};

const emptyItem = () => ({
  product_id: null,
  description: '',
  qty: 1,
  unit_toman: '',
  showDropdown: false,
});

/** One editable invoice line: free-text description with an optional catalogue attach. */
function LineItemRow({ item, index, products, onChange, onRemove, canRemove }) {
  const term = (item.description || '').toLowerCase();
  const filtered = term
    ? products.filter(
        (p) =>
          (p.name || '').toLowerCase().includes(term) ||
          (p.product_id || '').toLowerCase().includes(term)
      )
    : products;

  return (
    <div
      className="rounded-lg border p-2"
      style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
    >
      <div className="flex gap-2 items-start">
        <div className="relative flex-1">
          <input
            type="text"
            className="input-field w-full text-xs"
            aria-label="شرح آیتم"
            placeholder="شرح آیتم یا جستجوی محصول کاتالوگ..."
            value={item.description}
            onChange={(e) => onChange({ description: e.target.value, showDropdown: true })}
            onFocus={() => onChange({ showDropdown: true })}
            onBlur={() => setTimeout(() => onChange({ showDropdown: false }), 150)}
          />
          {item.product_id != null && (
            <span
              className="absolute left-1 top-1/2 -translate-y-1/2 text-[10px] px-1.5 py-0.5 rounded-full flex items-center gap-1"
              style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}
              title="متصل به محصول کاتالوگ"
            >
              کاتالوگ
              <button
                type="button"
                aria-label="قطع اتصال محصول"
                onClick={() => onChange({ product_id: null })}
                style={{ color: 'inherit' }}
              >
                <Trash2 size={10} />
              </button>
            </span>
          )}
          {item.showDropdown && filtered.length > 0 && (
            <div
              className="absolute z-50 w-full mt-1 rounded-lg border shadow-lg max-h-40 overflow-y-auto"
              style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
            >
              {filtered.slice(0, 15).map((p) => {
                const price = catalogPrice(p);
                return (
                  <button
                    key={p.id}
                    type="button"
                    className="w-full text-right px-3 py-1.5 text-xs flex items-center justify-between"
                    style={{ borderBottom: '1px solid var(--border-color)' }}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() =>
                      onChange({
                        product_id: p.id,
                        description: p.name || '',
                        // A positive catalogue price seeds the line; otherwise
                        // keep whatever staff already typed.
                        unit_toman: price > 0 ? price : item.unit_toman ?? '',
                        showDropdown: false,
                      })
                    }
                  >
                    <span style={{ color: 'var(--text-primary)' }}>{p.name}</span>
                    {price > 0 && (
                      <span style={{ color: 'var(--text-muted)' }}>{formatPrice(price)}</span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <input
          type="number"
          min="1"
          className="input-field w-16 text-xs text-center"
          aria-label="تعداد"
          value={item.qty}
          onChange={(e) => onChange({ qty: e.target.value })}
        />
        <input
          type="number"
          min="0"
          className="input-field w-28 text-xs"
          aria-label="قیمت واحد (تومان)"
          placeholder="قیمت واحد"
          value={item.unit_toman}
          onChange={(e) => onChange({ unit_toman: e.target.value })}
        />
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="p-1.5 rounded-lg flex-shrink-0"
            style={{ color: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)' }}
            aria-label={`حذف آیتم ${index + 1}`}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

export default function CommerceAdmin() {
  const [products, setProducts] = useState([]);
  const [productsError, setProductsError] = useState(false);

  // Website request queue
  const [requests, setRequests] = useState([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [requestsHasMore, setRequestsHasMore] = useState(false);
  const [requestsError, setRequestsError] = useState(null);

  // Invoice queue
  const [invoices, setInvoices] = useState([]);
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  const [invoicesError, setInvoicesError] = useState(null);
  const [invoicesHasMore, setInvoicesHasMore] = useState(false);

  // One-time private links (never returned by the list endpoint).
  const [shareLinks, setShareLinks] = useState({});
  const [copiedId, setCopiedId] = useState(null);
  const [statusMessage, setStatusMessage] = useState('');
  // Reset the "copied" affordance after a beat so it never sticks forever.
  const copyResetRef = useRef(null);
  const [actionError, setActionError] = useState(null);
  // Invoice awaiting confirmation before an edit that would kill its live link.
  const [confirmEdit, setConfirmEdit] = useState(null);

  // Editor
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [linkedRequestId, setLinkedRequestId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [items, setItems] = useState([emptyItem()]);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  const fetchRequestsPage = useCallback(async (offset) => {
    setRequestsLoading(true);
    try {
      const res = await getStaffRequests({ limit: REQUESTS_PAGE_SIZE, offset });
      const page = Array.isArray(res.data) ? res.data : [];
      setRequests((prev) => (offset === 0 ? page : [...prev, ...page]));
      setRequestsHasMore(page.length === REQUESTS_PAGE_SIZE);
      setRequestsError(null);
    } catch (err) {
      if (!isCanceled(err)) setRequestsError('خطا در بارگذاری درخواست‌ها');
    } finally {
      setRequestsLoading(false);
    }
  }, []);

  const loadInvoices = useCallback(async (offset = 0) => {
    setInvoicesLoading(true);
    try {
      const res = await getStaffInvoices({ limit: INVOICES_PAGE_SIZE, offset });
      const page = Array.isArray(res.data) ? res.data : [];
      setInvoices((prev) => (offset === 0 ? page : [...prev, ...page]));
      setInvoicesHasMore(page.length === INVOICES_PAGE_SIZE);
      setInvoicesError(null);
    } catch (err) {
      if (!isCanceled(err)) setInvoicesError('خطا در بارگذاری فاکتورها');
    } finally {
      setInvoicesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRequestsPage(0);
  }, [fetchRequestsPage]);

  useEffect(() => {
    loadInvoices(0);
  }, [loadInvoices]);

  useEffect(() => {
    getProductsAll()
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : res.data?.items ?? [];
        setProducts(list.filter((p) => p.is_active !== false));
        setProductsError(false);
      })
      .catch((err) => {
        // Surface a hint instead of silently showing an empty catalogue.
        if (!isCanceled(err)) setProductsError(true);
      });
  }, []);

  // Never leave a pending copy-reset timer running after unmount.
  useEffect(
    () => () => {
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
    },
    []
  );

  // ── Editor open helpers ────────────────────────────────────────────

  const openCreate = () => {
    setEditingId(null);
    setLinkedRequestId(null);
    setForm(emptyForm);
    setItems([emptyItem()]);
    setFormError(null);
    setShowModal(true);
  };

  const openConvert = (request) => {
    setEditingId(null);
    setLinkedRequestId(request.id);
    setForm({
      customer_name: request.customer_name || '',
      mobile: request.mobile || '',
      messenger: request.messenger || 'telegram',
      messenger_handle: request.messenger_handle || '',
      address: request.address || '',
      specification: '',
      internal_note: request.note || '',
      shipping_toman: '',
    });
    const reqItems = (request.items || []).map((i) => ({
      product_id: i.product_id ?? null,
      description: i.display_name || '',
      qty: i.qty || 1,
      unit_toman: i.indicative_unit_price_toman ?? '',
      showDropdown: false,
    }));
    setItems(reqItems.length ? reqItems : [emptyItem()]);
    setFormError(null);
    setShowModal(true);
  };

  const openEdit = (invoice) => {
    setEditingId(invoice.id);
    setLinkedRequestId(null);
    setForm({
      customer_name: invoice.customer_name || '',
      mobile: invoice.mobile || '',
      messenger: invoice.messenger || 'telegram',
      messenger_handle: invoice.messenger_handle || '',
      address: invoice.address || '',
      specification: invoice.specification || '',
      internal_note: invoice.internal_note || '',
      shipping_toman: invoice.shipping_toman ?? '',
    });
    const invItems = (invoice.items || []).map((i) => ({
      product_id: i.product_id ?? null,
      description: i.description || '',
      qty: i.qty || 1,
      unit_toman: i.unit_toman ?? '',
      showDropdown: false,
    }));
    setItems(invItems.length ? invItems : [emptyItem()]);
    setFormError(null);
    setShowModal(true);
  };

  /**
   * Editing an approved invoice bumps the revision and invalidates the live
   * share link the customer may already hold — confirm before doing that to an
   * approved invoice, edit drafts/expired/revoked straight away.
   */
  const requestEdit = (invoice) => {
    if (invoiceDisplayState(invoice) === 'approved') {
      setConfirmEdit(invoice);
      return;
    }
    openEdit(invoice);
  };

  const confirmEditProceed = () => {
    const invoice = confirmEdit;
    setConfirmEdit(null);
    if (invoice) openEdit(invoice);
  };

  const closeModal = () => {
    if (saving) return;
    setShowModal(false);
  };

  // ── Line item handlers ─────────────────────────────────────────────

  const updateItem = (idx, patch) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const addItem = () => setItems((prev) => [...prev, emptyItem()]);
  const removeItem = (idx) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const itemsTotal = useMemo(
    () => items.reduce((sum, it) => sum + (Number(it.qty) || 0) * (Number(it.unit_toman) || 0), 0),
    [items]
  );
  const shippingTotal = Number(form.shipping_toman) || 0;

  // ── Save (create or revise) ────────────────────────────────────────

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (saving) return;
    setFormError(null);

    const name = form.customer_name.trim();
    const mobile = normalizeDigits(form.mobile).replace(/\s+/g, '');
    if (!name) {
      setFormError('نام مشتری الزامی است');
      return;
    }
    if (!MOBILE_RE.test(mobile)) {
      setFormError('شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد');
      return;
    }

    const cleaned = items
      .map((it) => ({
        product_id: it.product_id ?? null,
        description: (it.description || '').trim(),
        qty: Number(it.qty),
        unit_toman: Number(it.unit_toman),
      }))
      .filter((it) => it.description);

    if (cleaned.length === 0) {
      setFormError('حداقل یک آیتم فاکتور اضافه کنید');
      return;
    }
    for (const it of cleaned) {
      if (!Number.isInteger(it.qty) || it.qty < 1) {
        setFormError('تعداد هر آیتم باید عددی صحیح و حداقل ۱ باشد');
        return;
      }
      if (!Number.isInteger(it.unit_toman) || it.unit_toman < 1) {
        setFormError('قیمت واحد هر آیتم باید عددی صحیح و حداقل ۱ باشد');
        return;
      }
    }

    const payload = {
      // A revision must never silently re-point the invoice at another request.
      request_id: editingId ? null : linkedRequestId ?? null,
      customer_name: name,
      mobile,
      messenger: form.messenger,
      messenger_handle: form.messenger_handle.trim(),
      address: form.address.trim(),
      specification: form.specification.trim(),
      internal_note: form.internal_note.trim(),
      shipping_toman: shippingTotal,
      items: cleaned,
    };

    setSaving(true);
    try {
      if (editingId) {
        const res = await updateStaffInvoice(editingId, payload);
        const updated = res?.data;
        setInvoices((prev) => prev.map((inv) => (inv.id === editingId ? updated : inv)));
        setShareLinks((prev) => {
          const next = { ...prev };
          delete next[editingId];
          return next;
        });
      } else {
        const res = await createStaffInvoice(payload);
        const created = res?.data;
        setInvoices((prev) => [created, ...prev]);
        if (linkedRequestId != null) {
          setRequests((prev) =>
            prev.map((r) => (r.id === linkedRequestId ? { ...r, state: 'converted' } : r))
          );
        }
      }
      setShowModal(false);
    } catch (err) {
      setFormError(extractError(err));
    } finally {
      setSaving(false);
    }
  };

  // ── Approve / revoke / copy ────────────────────────────────────────

  const handleApprove = async (invoice) => {
    setActionError(null);
    try {
      const res = await approveStaffInvoice(invoice.id);
      const data = res?.data || {};
      if (data.share_url) {
        setShareLinks((prev) => ({ ...prev, [invoice.id]: data.share_url }));
      }
      setInvoices((prev) =>
        prev.map((inv) =>
          inv.id === invoice.id
            ? {
                ...inv,
                state: data.state || 'approved',
                revision: data.revision ?? inv.revision,
                has_active_link: true,
                token_expires_at: data.expires_at || inv.token_expires_at,
              }
            : inv
        )
      );
      setStatusMessage('لینک پرداخت ساخته شد. آن را کپی و در گفتگوی مشتری ارسال کنید.');
    } catch (err) {
      setActionError(extractError(err));
    }
  };

  const handleRevoke = async (invoice) => {
    setActionError(null);
    try {
      const res = await revokeStaffInvoice(invoice.id);
      const updated = res?.data;
      setInvoices((prev) => prev.map((inv) => (inv.id === invoice.id ? updated : inv)));
      setShareLinks((prev) => {
        const next = { ...prev };
        delete next[invoice.id];
        return next;
      });
      setStatusMessage('لینک پرداخت باطل شد.');
    } catch (err) {
      setActionError(extractError(err));
    }
  };

  const handleCopy = async (id, url) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        // Fallback for browsers without the async clipboard API.
        const el = document.createElement('textarea');
        el.value = url;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
      }
      setCopiedId(id);
      setStatusMessage('لینک کپی شد. آن را دستی در گفتگوی پیام‌رسان بچسبانید.');
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
      copyResetRef.current = setTimeout(() => setCopiedId(null), COPY_RESET_MS);
    } catch {
      setActionError('کپی لینک ناموفق بود؛ لینک را دستی انتخاب کنید.');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold" style={{ color: '#ffffff' }}>
            فاکتور و لینک پرداخت
          </h2>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            صدور فاکتور بررسی‌شده، تأیید و ساخت لینک پرداخت خصوصی. لینک فقط برای کپی و ارسال دستی در
            گفت‌وگوی پیام‌رسان است.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/orders" className="btn-secondary text-xs inline-flex items-center gap-1.5">
            <ArrowLeft size={14} /> برد سفارش‌ها
          </Link>
          <button type="button" onClick={openCreate} className="btn-primary">
            <Plus size={16} /> فاکتور جدید
          </button>
        </div>
      </div>

      {actionError && (
        <div
          role="alert"
          className="p-3 rounded-xl text-xs border flex items-center gap-2"
          style={{ backgroundColor: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.35)', color: '#ef4444' }}
        >
          <AlertTriangle size={15} /> {actionError}
        </div>
      )}

      {/* Async status announcements for assistive tech. */}
      <div role="status" aria-live="polite" className="sr-only">
        {statusMessage}
      </div>

      {/* ── Website requests ── */}
      <section className="card p-0 overflow-hidden" aria-busy={requestsLoading}>
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <Inbox size={16} /> درخواست‌های سایت
          </h3>
          {requestsHasMore && (
            <button
              type="button"
              onClick={() => fetchRequestsPage(requests.length)}
              className="btn-secondary text-xs"
              disabled={requestsLoading}
            >
              {requestsLoading ? <Loader2 size={13} className="animate-spin" /> : null} بارگذاری بیشتر
            </button>
          )}
        </div>

        {requestsError ? (
          <p className="px-4 py-6 text-xs" style={{ color: '#ef4444' }}>{requestsError}</p>
        ) : requests.length === 0 ? (
          <p className="px-4 py-6 text-xs text-center" style={{ color: 'var(--text-muted)' }}>
            درخواست جدیدی برای بررسی وجود ندارد.
          </p>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
            {requests.map((req) => {
              const convertible = req.state === 'pending_review';
              return (
                <div key={req.id} className="px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                        {req.customer_name}
                      </span>
                      <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)', direction: 'ltr' }}>
                        {req.receipt_id}
                      </span>
                      {!convertible && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded-full"
                          style={{ backgroundColor: 'rgba(34,197,94,0.15)', color: '#16a34a' }}
                        >
                          تبدیل‌شده
                        </span>
                      )}
                    </div>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                      {(req.items || []).map((i) => `${i.display_name}×${i.qty}`).join('، ') || '—'}
                    </p>
                    <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)', direction: 'ltr' }}>
                      {req.mobile}
                    </p>
                  </div>
                  {convertible && (
                    <button
                      type="button"
                      onClick={() => openConvert(req)}
                      className="btn-primary text-xs shrink-0"
                    >
                      <FileText size={14} /> تبدیل به فاکتور
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Invoices ── */}
      <section className="card p-0 overflow-hidden" aria-busy={invoicesLoading}>
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <FileText size={16} /> فاکتورها
          </h3>
          <div className="flex items-center gap-2">
            {invoicesLoading && (
              <Loader2
                size={14}
                className="animate-spin"
                style={{ color: 'var(--text-muted)' }}
                aria-hidden="true"
              />
            )}
            {invoicesHasMore && (
              <button
                type="button"
                onClick={() => loadInvoices(invoices.length)}
                className="btn-secondary text-xs"
                disabled={invoicesLoading}
              >
                بارگذاری بیشتر
              </button>
            )}
          </div>
        </div>

        {invoicesError ? (
          <p className="px-4 py-6 text-xs" style={{ color: '#ef4444' }}>{invoicesError}</p>
        ) : invoices.length === 0 ? (
          <p className="px-4 py-6 text-xs text-center" style={{ color: 'var(--text-muted)' }}>
            هنوز فاکتوری ساخته نشده است.
          </p>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
            {invoices.map((invoice) => {
              const display = invoiceDisplayState(invoice);
              const meta = STATE_META[display] || STATE_META.draft;
              const shareUrl = shareLinks[invoice.id];
              const editable = invoice.state !== 'paid';
              return (
                <div key={invoice.id} className="px-4 py-3 space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                          {invoice.customer_name}
                        </span>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          #{invoice.id} · نسخه {invoice.revision}
                        </span>
                        <span
                          className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ backgroundColor: meta.bg, color: meta.color }}
                        >
                          {meta.label}
                        </span>
                      </div>
                      <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                        {formatPrice(invoice.total_toman)}
                        {invoice.shipping_toman > 0 && (
                          <span style={{ color: 'var(--text-muted)' }}>
                            {' '}(+ {formatPrice(invoice.shipping_toman)} ارسال)
                          </span>
                        )}
                      </p>
                    </div>

                    <div className="flex items-center gap-1 flex-wrap justify-end">
                      {editable && (
                        <button
                          type="button"
                          onClick={() => requestEdit(invoice)}
                          className="btn-secondary text-xs"
                        >
                          ویرایش
                        </button>
                      )}
                      {display === 'draft' && (
                        <button
                          type="button"
                          onClick={() => handleApprove(invoice)}
                          className="btn-primary text-xs"
                        >
                          <Link2 size={13} /> تأیید و صدور لینک
                        </button>
                      )}
                      {(display === 'expired' || display === 'revoked') && (
                        <button
                          type="button"
                          onClick={() => handleApprove(invoice)}
                          className="btn-primary text-xs"
                        >
                          <Link2 size={13} /> صدور لینک جدید
                        </button>
                      )}
                      {display === 'approved' && (
                        <button
                          type="button"
                          onClick={() => handleRevoke(invoice)}
                          className="btn-secondary text-xs inline-flex items-center gap-1"
                          style={{ color: '#ef4444' }}
                        >
                          <Ban size={13} /> لغو لینک
                        </button>
                      )}
                    </div>
                  </div>

                  {shareUrl && (
                    <div
                      className="flex flex-col sm:flex-row sm:items-center gap-2 rounded-lg px-3 py-2 border"
                      style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
                    >
                      <code
                        className="text-[11px] flex-1 break-all"
                        style={{ color: 'var(--text-primary)', direction: 'ltr' }}
                      >
                        {shareUrl}
                      </code>
                      <button
                        type="button"
                        onClick={() => handleCopy(invoice.id, shareUrl)}
                        className="btn-secondary text-xs shrink-0 inline-flex items-center gap-1"
                      >
                        {copiedId === invoice.id ? <Check size={13} /> : <Copy size={13} />}
                        {copiedId === invoice.id ? 'کپی شد' : 'کپی لینک'}
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Confirm edit of an approved invoice ── */}
      <Modal
        isOpen={confirmEdit != null}
        onClose={() => setConfirmEdit(null)}
        title="تأیید ویرایش فاکتور"
        size="sm"
      >
        <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          این فاکتور تأییدشده است و لینک پرداخت آن پیش‌تر ساخته شده. با ویرایش، فاکتور به پیش‌نویس
          بازمی‌گردد، شماره نسخه افزایش می‌یابد و لینک فعلی بلافاصله باطل می‌شود؛ سپس باید لینک
          تازه‌ای صادر کنید. ادامه می‌دهید؟
        </p>
        <div className="flex gap-2 pt-4">
          <button
            type="button"
            className="btn-secondary flex-1 justify-center"
            onClick={() => setConfirmEdit(null)}
          >
            انصراف
          </button>
          <button
            type="button"
            className="btn-primary flex-1 justify-center"
            onClick={confirmEditProceed}
          >
            ادامه و ویرایش
          </button>
        </div>
      </Modal>

      {/* ── Editor ── */}
      <Modal
        isOpen={showModal}
        onClose={closeModal}
        title={editingId ? 'ویرایش فاکتور' : 'فاکتور جدید'}
        size="lg"
      >
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="inv-name" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                نام مشتری *
              </label>
              <input
                id="inv-name"
                className="input-field w-full"
                value={form.customer_name}
                onChange={(e) => setForm((f) => ({ ...f, customer_name: e.target.value }))}
                maxLength={120}
              />
            </div>
            <div>
              <label htmlFor="inv-mobile" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                شماره موبایل *
              </label>
              <input
                id="inv-mobile"
                className="input-field w-full"
                style={{ direction: 'ltr' }}
                inputMode="numeric"
                placeholder="09xxxxxxxxx"
                value={form.mobile}
                onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))}
                maxLength={11}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="inv-messenger" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                پیام‌رسان
              </label>
              <select
                id="inv-messenger"
                className="select-field w-full"
                value={form.messenger}
                onChange={(e) => setForm((f) => ({ ...f, messenger: e.target.value }))}
              >
                {MESSENGER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="inv-handle" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                شناسه پیام‌رسان
              </label>
              <input
                id="inv-handle"
                className="input-field w-full"
                style={{ direction: 'ltr' }}
                value={form.messenger_handle}
                onChange={(e) => setForm((f) => ({ ...f, messenger_handle: e.target.value }))}
                maxLength={100}
              />
            </div>
          </div>

          <div>
            <label htmlFor="inv-address" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              آدرس
            </label>
            <input
              id="inv-address"
              className="input-field w-full"
              value={form.address}
              onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
              maxLength={500}
            />
          </div>

          {/* Line items */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
                آیتم‌های فاکتور
              </label>
              <button
                type="button"
                onClick={addItem}
                className="text-xs font-medium flex items-center gap-1 px-2 py-1 rounded-lg"
                style={{ color: 'var(--accent)', backgroundColor: 'var(--accent-light)' }}
              >
                <Plus size={12} /> افزودن آیتم
              </button>
            </div>
            {productsError && (
              <p className="text-[11px] mb-2" style={{ color: '#d97706' }}>
                بارگذاری محصولات کاتالوگ ناموفق بود؛ می‌توانید آیتم را دستی وارد کنید.
              </p>
            )}
            <div className="space-y-2">
              {items.map((it, idx) => (
                <LineItemRow
                  key={idx}
                  item={it}
                  index={idx}
                  products={products}
                  onChange={(patch) => updateItem(idx, patch)}
                  onRemove={() => removeItem(idx)}
                  canRemove={items.length > 1}
                />
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="inv-shipping" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                هزینه ارسال (تومان)
              </label>
              <input
                id="inv-shipping"
                type="number"
                min="0"
                className="input-field w-full"
                value={form.shipping_toman}
                onChange={(e) => setForm((f) => ({ ...f, shipping_toman: e.target.value }))}
              />
            </div>
            <div className="flex flex-col justify-center">
              <div className="rounded-lg px-3 py-2" style={{ backgroundColor: 'var(--bg-secondary)' }}>
                <div className="flex justify-between text-xs mb-1">
                  <span style={{ color: 'var(--text-muted)' }}>جمع اقلام:</span>
                  <span style={{ color: 'var(--text-primary)' }}>{formatPrice(itemsTotal)}</span>
                </div>
                <div className="flex justify-between text-xs font-semibold">
                  <span style={{ color: 'var(--text-muted)' }}>مبلغ کل:</span>
                  <span style={{ color: 'var(--accent)' }}>{formatPrice(itemsTotal + shippingTotal)}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="inv-spec" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                مشخصات نهایی (نمایش به مشتری)
              </label>
              <textarea
                id="inv-spec"
                rows={2}
                className="input-field w-full"
                value={form.specification}
                onChange={(e) => setForm((f) => ({ ...f, specification: e.target.value }))}
                maxLength={2000}
              />
            </div>
            <div>
              <label htmlFor="inv-note" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                یادداشت داخلی (مخصوص کارکنان)
              </label>
              <textarea
                id="inv-note"
                rows={2}
                className="input-field w-full"
                value={form.internal_note}
                onChange={(e) => setForm((f) => ({ ...f, internal_note: e.target.value }))}
                maxLength={2000}
              />
            </div>
          </div>

          {formError && (
            <div
              role="alert"
              className="p-3 rounded-xl text-xs border"
              style={{ backgroundColor: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.35)', color: '#ef4444' }}
            >
              {formError}
            </div>
          )}

          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            ذخیره فقط پیش‌نویس می‌سازد؛ برای ساخت لینک پرداخت باید فاکتور را تأیید کنید. ویرایش هر فاکتور
            تأییدشده، لینک قبلی را باطل می‌کند.
          </p>

          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1 justify-center" onClick={closeModal} disabled={saving}>
              انصراف
            </button>
            <button type="submit" className="btn-primary flex-1 justify-center" disabled={saving}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : null} ذخیره
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
