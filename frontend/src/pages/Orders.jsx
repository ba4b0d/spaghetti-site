import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardList, Plus, Archive, Edit2, Download, Trash2, LayoutGrid, List, RotateCcw, Receipt } from 'lucide-react';
import { getOrders, createOrder, updateOrder, deleteOrder, restoreOrder, getOrderStatuses, exportOrdersCsv, getProductsAll } from '../lib/api';
import { formatPrice } from '../lib/utils';
import {
  formatShamsiDate,
  gregorianIsoToShamsi,
  shamsiToGregorianIso,
  todayGregorianIso,
  toGregorianIso,
} from '../lib/shamsi';
import Modal from '../components/Modal';
import ShamsiDateField from '../components/ShamsiDateField';

const STATUS_COLORS = {
  new: { bg: 'rgba(99,102,241,0.15)', color: '#6366f1' },
  quoted: { bg: 'rgba(8,145,178,0.15)', color: '#0891b2' },
  printing: { bg: 'rgba(245,158,11,0.15)', color: '#d97706' },
  ready: { bg: 'rgba(34,197,94,0.15)', color: '#16a34a' },
  delivered: { bg: 'rgba(100,116,139,0.15)', color: '#64748b' },
  cancelled: { bg: 'rgba(239,68,68,0.12)', color: '#ef4444' },
};

const DONE_STATUSES = new Set(['delivered', 'cancelled']);

function readyUrgency(order, todayIso) {
  if (!order?.ready_by || DONE_STATUSES.has(order.status)) return 'none';
  const due = toGregorianIso(order.ready_by);
  if (!due) return 'none';
  if (due < todayIso) return 'overdue';
  if (due === todayIso) return 'today';
  const t = new Date(`${todayIso}T12:00:00`);
  const d = new Date(`${due}T12:00:00`);
  const days = Math.round((d - t) / 86400000);
  if (days <= 2) return 'soon';
  return 'ok';
}

const READY_STYLES = {
  overdue: { color: '#dc2626', fontWeight: 700 },
  today: { color: '#d97706', fontWeight: 700 },
  soon: { color: '#b45309', fontWeight: 600 },
  ok: { color: 'var(--text-secondary)', fontWeight: 500 },
  none: { color: 'var(--text-muted)', fontWeight: 400 },
};

const emptyForm = {
  customer_name: '',
  contact: '',
  paid_amount: '',
  status: 'new',
  notes: '',
  started_at: '',
  ready_by: '',
};

const emptyItem = () => ({
  product_id: null,
  product_label: '',
  qty: 1,
  unit_price: '',
  search: '',
  showDropdown: false,
});

/** Product search combobox for a line item. */
function ProductCombobox({ products, item, onSelect }) {
  return (
    <div className="relative flex-1">
      <input
        type="text"
        className="input-field w-full text-xs"
        placeholder="جستجوی نام یا کد محصول..."
        value={item.search}
        onChange={(e) => onSelect({ search: e.target.value, showDropdown: true })}
        onFocus={() => onSelect({ showDropdown: true })}
        onBlur={() => setTimeout(() => onSelect({ showDropdown: false }), 200)}
      />
      {item.showDropdown && (
        <div
          className="absolute z-50 w-full mt-1 rounded-lg border shadow-lg max-h-40 overflow-y-auto"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          {(() => {
            const term = item.search.toLowerCase();
            const filtered = term
              ? products.filter((p) =>
                  (p.name || '').toLowerCase().includes(term) ||
                  (p.product_id || '').toLowerCase().includes(term)
                )
              : products;
            if (filtered.length === 0) {
              return (
                <div className="px-3 py-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                  نتیجه‌ای یافت نشد
                </div>
              );
            }
            return filtered.slice(0, 15).map((p) => (
              <button
                key={p.id}
                type="button"
                className="w-full text-right px-3 py-1.5 text-xs flex items-center justify-between transition-colors"
                style={{ borderBottom: '1px solid var(--border-color)' }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onSelect({
                  product_id: p.id,
                  product_label: p.name || '',
                  unit_price: p.suggested_price ?? p.final_price ?? '',
                  search: `${p.product_id ? p.product_id + ' — ' : ''}${p.name}`,
                  showDropdown: false,
                })}
              >
                <span style={{ color: 'var(--text-primary)' }}>
                  {p.product_id && (
                    <span className="font-mono ml-1" style={{ color: 'var(--accent)' }}>
                      {p.product_id}
                    </span>
                  )}
                  {p.name}
                </span>
                {p.suggested_price > 0 && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {formatPrice(p.suggested_price)}
                  </span>
                )}
              </button>
            ));
          })()}
        </div>
      )}
    </div>
  );
}

export default function Orders() {
  const [orders, setOrders] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [items, setItems] = useState([emptyItem()]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [viewMode, setViewMode] = useState('table'); // table | board
  const [showArchived, setShowArchived] = useState(false);

  const todayIso = todayGregorianIso();

  const handleCloseModal = useCallback(() => {
    if (saving) return;
    setShowModal(false);
  }, [saving]);

  const load = useCallback(async (signal) => {
    try {
      const params = {};
      if (filter) params.status = filter;
      if (search.trim()) params.search = search.trim();
      if (showArchived) params.include_inactive = true;
      const [oRes, sRes] = await Promise.all([
        getOrders(params, { signal }),
        getOrderStatuses({ signal }),
      ]);
      setOrders(Array.isArray(oRes.data) ? oRes.data : []);
      setStatuses(Array.isArray(sRes.data) ? sRes.data : []);
      setLoadError(null);
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      console.error(err);
      setLoadError('خطا در بارگذاری سفارش‌ها');
    } finally {
      setLoading(false);
    }
  }, [filter, search, showArchived]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    getProductsAll({ signal: controller.signal })
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : res.data?.items ?? res.data?.products ?? [];
        setProducts(list.filter((p) => p.is_active));
      })
      .catch((err) => {
        if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return;
      });
    return () => controller.abort();
  }, []);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setItems([emptyItem()]);
    setError('');
    setShowModal(true);
  };

  const openEdit = (order) => {
    setEditing(order);
    // Convert order.items to form items, or create one from legacy fields
    const orderItems = order.items && order.items.length > 0
      ? order.items.map((oi) => {
          const p = oi.product_id ? products.find((x) => x.id === oi.product_id) : null;
          return {
            product_id: oi.product_id,
            product_label: oi.product_label || '',
            qty: oi.qty || 1,
            unit_price: oi.unit_price || '',
            search: p ? `${p.product_id ? p.product_id + ' — ' : ''}${p.name}` : (oi.product_label || ''),
            showDropdown: false,
          };
        })
      : [{
          product_id: order.product_id,
          product_label: order.product_label || '',
          qty: order.qty || 1,
          unit_price: order.quoted_price || '',
          search: order.product_label || '',
          showDropdown: false,
        }];
    setItems(orderItems.length > 0 ? orderItems : [emptyItem()]);
    setForm({
      customer_name: order.customer_name || '',
      contact: order.contact || '',
      paid_amount: order.paid_amount ?? '',
      status: order.status || 'new',
      notes: order.notes || '',
      started_at: gregorianIsoToShamsi(order.started_at),
      ready_by: gregorianIsoToShamsi(order.ready_by),
    });
    setError('');
    setShowModal(true);
  };

  // Line item handlers
  const addItem = () => setItems((prev) => [...prev, emptyItem()]);
  const removeItem = (idx) => setItems((prev) => prev.filter((_, i) => i !== idx));
  const updateItem = (idx, patch) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  // Compute totals from items
  const itemsTotal = items.reduce((sum, it) => sum + (Number(it.qty) || 1) * (Number(it.unit_price) || 0), 0);
  const paidAmount = Number(form.paid_amount) || 0;
  const remaining = Math.max(0, itemsTotal - paidAmount);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.customer_name.trim()) {
      setError('نام مشتری الزامی است');
      return;
    }
    if (items.length === 0 || items.every((it) => !it.product_label && !it.product_id)) {
      setError('حداقل یک آیتم سفارش اضافه کنید');
      return;
    }
    let startedIso = null;
    let readyIso = null;
    if (form.started_at.trim()) {
      startedIso = shamsiToGregorianIso(form.started_at);
      if (!startedIso) {
        setError('تاریخ شروع شمسی نامعتبر است (مثال: ۱۴۰۵/۰۴/۲۸)');
        return;
      }
    }
    if (form.ready_by.trim()) {
      readyIso = shamsiToGregorianIso(form.ready_by);
      if (!readyIso) {
        setError('موعد آماده ارسال شمسی نامعتبر است (مثال: ۱۴۰۵/۰۴/۲۸)');
        return;
      }
    }
    // Validate paid ≤ total
    if (paidAmount > itemsTotal && itemsTotal > 0) {
      setError(`مبلغ پرداختی (${formatPrice(paidAmount)}) از کل سفارش (${formatPrice(itemsTotal)}) بیشتر است`);
      return;
    }
    setSaving(true);
    const payload = {
      customer_name: form.customer_name.trim(),
      contact: form.contact.trim(),
      paid_amount: paidAmount,
      status: form.status || 'new',
      notes: form.notes.trim(),
      started_at: startedIso,
      ready_by: readyIso,
      items: items
        .filter((it) => it.product_label || it.product_id)
        .map((it) => ({
          product_id: it.product_id || null,
          product_label: it.product_label || '',
          qty: Number(it.qty) || 1,
          unit_price: Number(it.unit_price) || 0,
        })),
    };
    try {
      if (editing) {
        await updateOrder(editing.id, payload);
      } else {
        await createOrder(payload);
      }
      setShowModal(false);
      setLoading(true);
      await load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'خطا در ذخیره سفارش');
    } finally {
      setSaving(false);
    }
  };

  const handleStatusQuick = async (order, status) => {
    if (status === order.status) return;
    setOrders((prev) => prev.map((o) => o.id === order.id ? { ...o, status } : o));
    try {
      await updateOrder(order.id, { status });
    } catch (err) {
      setOrders((prev) => prev.map((o) => o.id === order.id ? { ...o, status: order.status } : o));
      alert(err.response?.data?.detail || 'خطا در تغییر وضعیت');
    }
  };

  const handleArchive = async (order) => {
    if (!confirm(`بایگانی «${order.customer_name}»؟`)) return;
    try {
      await deleteOrder(order.id);
      await load();
    } catch (err) {
      alert(err.response?.data?.detail || 'خطا');
    }
  };

  const handleRestore = async (order) => {
    if (!confirm(`بازیابی «${order.customer_name}»؟`)) return;
    try {
      await restoreOrder(order.id);
      await load();
    } catch (err) {
      alert(err.response?.data?.detail || 'خطا در بازیابی سفارش');
    }
  };

  const handleExportCsv = async () => {
    try {
      const res = await exportOrdersCsv();
      const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'orders.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('خطا در خروجی CSV');
    }
  };

  if (loading && orders.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <span style={{ color: 'var(--text-muted)' }}>در حال بارگذاری...</span>
      </div>
    );
  }

  if (loadError && orders.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <span style={{ color: '#ef4444' }}>{loadError}</span>
      </div>
    );
  }

  const statusOptions = statuses.length
    ? statuses
    : [
        { value: 'new', label: 'جدید' },
        { value: 'quoted', label: 'قیمت‌داده‌شده' },
        { value: 'printing', label: 'در حال چاپ' },
        { value: 'ready', label: 'آماده تحویل' },
        { value: 'delivered', label: 'تحویل‌شده' },
        { value: 'cancelled', label: 'لغو' },
      ];

  const headers = ['مشتری', 'تماس', 'آیتم‌ها', 'شروع', 'موعد ارسال', 'قیمت کل', 'پرداخت', 'مانده', 'وضعیت', ''];

  const totals = orders.reduce(
    (acc, o) => {
      acc.quoted += (o.total_quoted ?? o.quoted_price ?? 0);
      acc.paid += (o.paid_amount ?? 0);
      acc.remaining += (o.remaining ?? 0);
      return acc;
    },
    { quoted: 0, paid: 0, remaining: 0 }
  );

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold" style={{ color: '#ffffff' }}>
            سفارش‌ها
          </h2>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            برد سفارش‌ها و مدیریت پرداخت
          </p>
        </div>
        <div className="flex gap-2">
          <div className="flex items-center rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
            <button
              type="button"
              onClick={() => setViewMode('table')}
              className="p-2 transition-colors"
              style={{
                backgroundColor: viewMode === 'table' ? 'var(--accent)' : 'var(--bg-card)',
                color: viewMode === 'table' ? '#fff' : 'var(--text-secondary)',
              }}
              title="نمای جدولی"
            >
              <List size={16} />
            </button>
            <button
              type="button"
              onClick={() => setViewMode('board')}
              className="p-2 transition-colors"
              style={{
                backgroundColor: viewMode === 'board' ? 'var(--accent)' : 'var(--bg-card)',
                color: viewMode === 'board' ? '#fff' : 'var(--text-secondary)',
              }}
              title="نمای برد"
            >
              <LayoutGrid size={16} />
            </button>
          </div>
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            className="btn-secondary text-xs"
            aria-pressed={showArchived}
          >
            <Archive size={14} /> {showArchived ? 'مخفی کردن بایگانی' : 'نمایش بایگانی'}
          </button>
          <button type="button" onClick={handleExportCsv} className="btn-secondary text-xs">
            <Download size={14} /> CSV
          </button>
          <Link to="/commerce-admin" className="btn-secondary text-xs inline-flex items-center gap-1.5">
            <Receipt size={14} /> فاکتور و پرداخت
          </Link>
          <button type="button" onClick={openCreate} className="btn-primary">
            <Plus size={16} /> سفارش جدید
          </button>
        </div>
      </div>

      {/* Search bar */}
      <div className="relative">
        <input
          type="text"
          placeholder="جستجوی نام مشتری یا شماره تماس..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input-field w-full"
          style={{ paddingLeft: '2.5rem' }}
        />
        <span className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }}>
          🔍
        </span>
      </div>

      <div
        className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        <button
          type="button"
          onClick={() => setFilter('')}
          className="flex-shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors"
          style={{
            backgroundColor: !filter ? 'var(--accent-light)' : 'var(--bg-card)',
            color: !filter ? 'var(--accent)' : 'var(--text-secondary)',
            borderColor: !filter ? 'var(--accent)' : 'var(--border-color)',
          }}
        >
          همه
        </button>
        {statuses.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => setFilter(s.value)}
            className="flex-shrink-0 px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors"
            style={{
              backgroundColor: filter === s.value ? 'var(--accent-light)' : 'var(--bg-card)',
              color: filter === s.value ? 'var(--accent)' : 'var(--text-secondary)',
              borderColor: filter === s.value ? 'var(--accent)' : 'var(--border-color)',
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {viewMode === 'board' ? (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 overflow-x-auto" style={{ gridAutoFlow: 'column', gridAutoColumns: 'minmax(220px, 1fr)' }}>
          {statusOptions.map((st) => {
            const colOrders = orders.filter((o) => o.status === st.value);
            const sc = STATUS_COLORS[st.value] || STATUS_COLORS.new;
            return (
              <div key={st.value} className="rounded-xl flex flex-col min-h-[300px]" style={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
                <div className="flex items-center justify-between px-3 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
                  <span className="text-xs font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: sc.color }} />
                    {st.label}
                  </span>
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: sc.bg, color: sc.color }}>
                    {colOrders.length}
                  </span>
                </div>
                <div className="p-2 space-y-2 flex-1 overflow-y-auto">
                  {colOrders.length === 0 ? (
                    <p className="text-[10px] text-center py-6" style={{ color: 'var(--text-muted)' }}>خالی</p>
                  ) : (
                    colOrders.map((o) => {
                      const urg = readyUrgency(o, todayIso);
                      const readyStyle = READY_STYLES[urg] || READY_STYLES.none;
                      const itemNames = o.items?.length
                        ? o.items.map((i) => i.product_label || '—').join(', ')
                        : (o.product_label || '—');
                      return (
                        <div key={o.id} className="card p-3 space-y-2 cursor-pointer hover:shadow-md transition-shadow" onClick={() => openEdit(o)}>
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>{o.customer_name}</span>
                            <span className="text-[10px] shrink-0" style={{ color: 'var(--text-muted)' }}>#{o.id}</span>
                          </div>
                          <p className="text-xs line-clamp-2" style={{ color: 'var(--text-secondary)' }}>{itemNames}</p>
                          <div className="flex items-center justify-between pt-1 border-t" style={{ borderColor: 'var(--border-color)' }}>
                            <span className="text-xs font-semibold" style={{ color: 'var(--accent)' }}>
                              {formatPrice(o.total_quoted ?? o.quoted_price)}
                            </span>
                            {o.ready_by ? (
                              <span className="text-[10px]" style={readyStyle}>{formatShamsiDate(o.ready_by)}</span>
                            ) : null}
                          </div>
                          <div className="flex gap-1">
                            {statusOptions.filter((s) => s.value !== o.status).slice(0, 2).map((s) => (
                              <button
                                key={s.value}
                                type="button"
                                onClick={(e) => { e.stopPropagation(); handleStatusQuick(o, s.value); }}
                                className="flex-1 text-[10px] py-1 rounded-lg border transition-colors"
                                style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                              >
                                ← {s.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : orders.length === 0 ? (
        <div className="card p-12 text-center">
          <ClipboardList size={48} className="mx-auto mb-4" style={{ color: 'var(--border-color)' }} />
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            هنوز سفارشی ثبت نشده
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ minWidth: 880 }}>
              <thead>
                <tr style={{ backgroundColor: 'var(--bg-tertiary)', borderBottom: '1px solid var(--border-color)' }}>
                  {headers.map((h) => (
                    <th
                      key={h || 'actions'}
                      className="text-right px-3 py-3 font-medium whitespace-nowrap"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const sc = STATUS_COLORS[o.status] || STATUS_COLORS.new;
                  const urg = readyUrgency(o, todayIso);
                  const readyStyle = READY_STYLES[urg] || READY_STYLES.none;
                  const itemNames = o.items?.length
                    ? o.items.map((i) => i.product_label || '—').join(', ')
                    : (o.product_label || '—');
                  return (
                    <tr
                      key={o.id}
                      style={{
                        borderBottom: '1px solid var(--border-color)',
                        opacity: o.is_active === false ? 0.65 : 1,
                      }}
                      className="hover:bg-[color-mix(in_srgb,var(--bg-tertiary)_50%,transparent)]"
                    >
                      <td className="px-3 py-3 font-medium" style={{ color: 'var(--text-primary)' }}>
                        {o.customer_name}
                        {o.is_active === false && (
                          <span className="text-[10px] mr-2 px-1.5 py-0.5 rounded-full" style={{ color: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.12)' }}>
                            بایگانی
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3" style={{ color: 'var(--text-secondary)' }}>
                        {o.contact || '—'}
                      </td>
                      <td
                        className="px-3 py-3 max-w-[12rem] truncate"
                        style={{ color: 'var(--text-secondary)' }}
                        title={itemNames}
                      >
                        {itemNames}
                        {o.items?.length > 1 && (
                          <span className="text-xs ml-1" style={{ color: 'var(--text-muted)' }}>
                            ({o.items.length})
                          </span>
                        )}
                      </td>
                      <td
                        className="px-3 py-3 whitespace-nowrap text-xs text-right"
                        style={{ color: 'var(--text-secondary)' }}
                        dir="ltr"
                      >
                        {formatShamsiDate(o.started_at)}
                      </td>
                      <td
                        className="px-3 py-3 whitespace-nowrap text-xs text-right"
                        style={readyStyle}
                        dir="ltr"
                        title={
                          urg === 'overdue'
                            ? 'موعد گذشته'
                            : urg === 'today'
                              ? 'موعد امروز'
                              : urg === 'soon'
                                ? 'نزدیک'
                                : ''
                        }
                      >
                        {formatShamsiDate(o.ready_by)}
                        {urg === 'overdue' && <span className="mr-1">!</span>}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                        {formatPrice(o.total_quoted ?? o.quoted_price)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                        {formatPrice(o.paid_amount)}
                      </td>
                      <td
                        className="px-3 py-3 whitespace-nowrap font-medium"
                        style={{ color: o.remaining > 0 ? '#d97706' : '#16a34a' }}
                      >
                        {formatPrice(o.remaining)}
                      </td>
                      <td className="px-3 py-3">
                        <select
                          value={o.status}
                          onChange={(e) => handleStatusQuick(o, e.target.value)}
                          className="text-xs font-medium rounded-lg px-2 py-1.5 border-0 cursor-pointer"
                          style={{ backgroundColor: sc.bg, color: sc.color }}
                          aria-label="وضعیت سفارش"
                        >
                          {statuses.map((s) => (
                            <option key={s.value} value={s.value}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1 justify-end">
                          {o.is_active === false ? (
                            <button
                              type="button"
                              onClick={() => handleRestore(o)}
                              className="p-2 rounded-lg"
                              style={{ color: '#16a34a', backgroundColor: 'rgba(34,197,94,0.12)' }}
                              title={`بازیابی سفارش ${o.customer_name}`}
                              aria-label={`بازیابی سفارش ${o.customer_name}`}
                            >
                              <RotateCcw size={14} />
                            </button>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => openEdit(o)}
                                className="p-2 rounded-lg"
                                style={{ color: 'var(--text-secondary)', backgroundColor: 'var(--bg-tertiary)' }}
                                title="ویرایش"
                              >
                                <Edit2 size={14} />
                              </button>
                              <button
                                type="button"
                                onClick={() => handleArchive(o)}
                                className="p-2 rounded-lg"
                                style={{ color: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)' }}
                                title="بایگانی"
                              >
                                <Archive size={14} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              {orders.length > 0 && (
                <tfoot>
                  <tr style={{ backgroundColor: 'var(--bg-tertiary)', borderTop: '2px solid var(--border-color)', fontWeight: 600 }}>
                    <td colSpan={5} className="px-3 py-3 text-right" style={{ color: 'var(--text-primary)' }}>
                      جمع ({orders.length} سفارش)
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                      {formatPrice(totals.quoted)}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap" style={{ color: '#16a34a' }}>
                      {formatPrice(totals.paid)}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap" style={{ color: totals.remaining > 0 ? '#d97706' : '#16a34a' }}>
                      {formatPrice(totals.remaining)}
                    </td>
                    <td colSpan={2}></td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      <Modal
        isOpen={showModal}
        onClose={handleCloseModal}
        title={editing ? 'ویرایش سفارش' : 'سفارش جدید'}
        size="lg"
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                نام مشتری *
              </label>
              <input
                className="input-field"
                value={form.customer_name}
                onChange={(e) => setForm((f) => ({ ...f, customer_name: e.target.value }))}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                تماس (تلفن / تلگرام)
              </label>
              <input
                className="input-field"
                value={form.contact}
                onChange={(e) => setForm((f) => ({ ...f, contact: e.target.value }))}
              />
            </div>
          </div>

          {/* ── Line items ── */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
                آیتم‌های سفارش
              </label>
              <button
                type="button"
                onClick={addItem}
                className="text-xs font-medium flex items-center gap-1 px-2 py-1 rounded-lg transition-colors"
                style={{ color: 'var(--accent)', backgroundColor: 'var(--accent-light)' }}
              >
                <Plus size={12} /> افزودن آیتم
              </button>
            </div>
            <div className="space-y-2">
              {items.map((it, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border p-2"
                  style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
                >
                  <div className="flex gap-2 items-start">
                    <ProductCombobox
                      products={products}
                      item={it}
                      onSelect={(patch) => updateItem(idx, patch)}
                    />
                    <input
                      type="number"
                      min="1"
                      className="input-field w-16 text-xs text-center"
                      placeholder="تعداد"
                      value={it.qty}
                      onChange={(e) => updateItem(idx, { qty: e.target.value })}
                      title="تعداد"
                    />
                    <input
                      type="number"
                      min="0"
                      className="input-field w-28 text-xs"
                      placeholder="قیمت واحد"
                      value={it.unit_price}
                      onChange={(e) => updateItem(idx, { unit_price: e.target.value })}
                      title="قیمت واحد (تومان)"
                    />
                    {items.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeItem(idx)}
                        className="p-1.5 rounded-lg flex-shrink-0"
                        style={{ color: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)' }}
                        title="حذف آیتم"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                  {(it.product_label || it.unit_price) && (
                    <div className="flex items-center justify-between mt-1 px-1">
                      <span className="text-xs truncate max-w-[60%]" style={{ color: 'var(--text-muted)' }}>
                        {it.product_label}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        {formatPrice((Number(it.qty) || 1) * (Number(it.unit_price) || 0))}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ── Totals + paid ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                پرداخت‌شده (تومان)
              </label>
              <input
                type="number"
                min="0"
                className="input-field"
                value={form.paid_amount}
                onChange={(e) => setForm((f) => ({ ...f, paid_amount: e.target.value }))}
              />
            </div>
            <div className="flex flex-col justify-center">
              <div className="rounded-lg px-3 py-2" style={{ backgroundColor: 'var(--bg-secondary)' }}>
                <div className="flex justify-between text-xs mb-1">
                  <span style={{ color: 'var(--text-muted)' }}>جمع کل:</span>
                  <span className="font-medium" style={{ color: 'var(--text-primary)' }}>{formatPrice(itemsTotal)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span style={{ color: 'var(--text-muted)' }}>مانده:</span>
                  <span className="font-medium" style={{ color: remaining > 0 ? '#d97706' : '#16a34a' }}>
                    {formatPrice(remaining)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Dates ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                تاریخ شروع (شمسی)
              </label>
              <ShamsiDateField
                value={form.started_at}
                onChange={(v) => setForm((f) => ({ ...f, started_at: v }))}
                placeholder="۱۴۰۵/۰۴/۲۸"
                aria-label="تاریخ شروع شمسی"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                موعد آماده ارسال (شمسی)
              </label>
              <ShamsiDateField
                value={form.ready_by}
                onChange={(v) => setForm((f) => ({ ...f, ready_by: v }))}
                placeholder="۱۴۰۵/۰۵/۰۵"
                aria-label="موعد آماده ارسال شمسی"
              />
            </div>
          </div>
          <p className="text-[11px] -mt-2" style={{ color: 'var(--text-muted)' }}>
            تقویم شمسی — خالی = بدون تاریخ
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                وضعیت
              </label>
              <select
                className="select-field w-full"
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
              >
                {statusOptions.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
                یادداشت
              </label>
              <input
                className="input-field"
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              />
            </div>
          </div>

          {error && (
            <p className="text-xs" style={{ color: '#ef4444' }}>
              {error}
            </p>
          )}
          <div className="flex gap-2 pt-1">
            <button type="button" className="btn-secondary flex-1 justify-center" onClick={handleCloseModal} disabled={saving}>
              انصراف
            </button>
            <button type="submit" className="btn-primary flex-1 justify-center" disabled={saving}>
              {saving ? '...' : 'ذخیره'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
