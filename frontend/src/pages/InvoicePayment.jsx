import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Clock,
  CreditCard,
  Loader2,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { formatPrice } from '../lib/constants';
import { getPublicInvoice, payInvoice } from '../lib/commerceApi';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';

/**
 * Public invoice payment page (Task 3, frontend only).
 *
 * ``/pay/:token`` renders ONLY customer-visible invoice data (final items,
 * finalized specification, shipping and the payable total, all in integer
 * Toman) and lets the customer start a payment. There is no customer account,
 * OTP or login: the private bearer token in the URL *is* the credential.
 *
 * Payment is possible only for an approved, unexpired, unpaid invoice — the
 * server is authoritative, so this page mirrors (never overrides) the invoice
 * state it reads. DigiPay is the only enabled gateway in v1; BitPay and
 * SnappPay are shown as explicitly unavailable so a disabled method can never
 * look payable.
 */

// DigiPay is the sole enabled method. The disabled entries are display-only.
const PAYMENT_METHODS = [
  { id: 'digipay', label: 'دیجی‌پی', enabled: true },
  { id: 'bitpay', label: 'بیت‌پی', enabled: false },
  { id: 'snapppay', label: 'اسنپ‌پی', enabled: false },
];

/**
 * DigiPay web-pay hosts allowed to receive the browser redirect. Mirrors the
 * backend allowlist (live + UAT) as defence in depth: the browser is never
 * handed an arbitrary or plaintext URL even if a response is tampered with.
 */
export const ALLOWED_GATEWAY_HOSTS = Object.freeze([
  'web.mydigipay.com',
  'uatweb.mydigipay.info',
]);

/**
 * Return the validated absolute HTTPS gateway URL, or ``null`` when the server
 * URL is not an allowed DigiPay host.
 */
export function validateGatewayUrl(url) {
  if (typeof url !== 'string' || !url.trim()) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:') return null;
  if (parsed.username || parsed.password) return null;
  if (!ALLOWED_GATEWAY_HOSTS.includes(parsed.hostname.toLowerCase())) return null;
  return parsed.href;
}

/** Pull a human-readable message out of an Axios/FastAPI error. */
export function extractPaymentError(err) {
  const data = err?.response?.data;
  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'string' && first.trim()) return first;
    if (first?.msg) return String(first.msg);
  }
  if (typeof data?.message === 'string' && data.message.trim()) return data.message;
  return 'خطا در ارتباط با سرور. لطفاً دوباره تلاش کنید.';
}

const isCancel = (err) => err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED';

function Shell({ children }) {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-10"
      dir="rtl"
      style={{ backgroundColor: 'var(--bg-primary, #0f172a)', color: 'var(--text-primary)' }}
    >
      <main className="w-full max-w-2xl">
        <div className="flex items-center justify-center gap-2 mb-6">
          <span
            className="w-9 h-9 rounded-xl flex items-center justify-center font-bold"
            style={{ backgroundColor: 'var(--accent)', color: '#fff' }}
            aria-hidden="true"
          >
            S
          </span>
          <span className="text-sm font-bold">اسپاگتی پرینت</span>
        </div>
        {children}
      </main>
    </div>
  );
}

function StateCard({ icon, title, children }) {
  return (
    <div
      className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in"
      style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
    >
      <div
        className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: 'var(--accent-light, rgba(99,102,241,0.15))' }}
      >
        {icon}
      </div>
      <h1 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
        {title}
      </h1>
      <div className="text-sm leading-relaxed space-y-3" style={{ color: 'var(--text-secondary)' }}>
        {children}
      </div>
    </div>
  );
}

export default function InvoicePayment({ redirect = (url) => window.location.assign(url) }) {
  const { token } = useParams();
  useNoReferrerPolicy();

  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [invoice, setInvoice] = useState(null);
  const [httpStatus, setHttpStatus] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const [payState, setPayState] = useState('idle'); // idle | submitting | error
  const [payError, setPayError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(
    (signal) => {
      setStatus('loading');
      setLoadError(null);
      setHttpStatus(null);
      return getPublicInvoice(token, signal ? { signal } : undefined)
        .then((res) => {
          if (!mountedRef.current) return;
          setInvoice(res?.data || null);
          setStatus('ready');
        })
        .catch((err) => {
          if (isCancel(err) || !mountedRef.current) return;
          setHttpStatus(err?.response?.status ?? null);
          setLoadError(extractPaymentError(err));
          setStatus('error');
        });
    },
    [token]
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const handlePay = useCallback(async () => {
    if (payState === 'submitting') return;
    setPayError(null);
    setPayState('submitting');
    try {
      const res = await payInvoice(token);
      const data = res?.data || {};
      const target = validateGatewayUrl(data.redirect_url);
      if (!target) {
        // Never follow an unvalidated URL: refuse and let the customer retry.
        setPayState('error');
        setPayError('آدرس درگاه پرداخت معتبر نیست؛ به دلایل امنیتی انتقال انجام نشد.');
        return;
      }
      redirect(target);
      if (mountedRef.current) setPayState('idle');
    } catch (err) {
      if (isCancel(err) || !mountedRef.current) return;
      setPayState('error');
      setPayError(extractPaymentError(err));
    }
  }, [payState, token, redirect]);

  const items = useMemo(() => (Array.isArray(invoice?.items) ? invoice.items : []), [invoice]);
  const subtotal = useMemo(
    () => items.reduce((sum, i) => sum + (Number(i.line_total_toman) || 0), 0),
    [items]
  );

  // ── Loading ─────────────────────────────────────────────────────────
  if (status === 'loading') {
    return (
      <Shell>
        <div
          className="card p-8 rounded-2xl border text-center"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          <Loader2 size={28} className="animate-spin mx-auto mb-3" style={{ color: 'var(--accent)' }} />
          <p role="status" className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            در حال بارگذاری فاکتور…
          </p>
        </div>
      </Shell>
    );
  }

  // ── Expired (server answered 410) ───────────────────────────────────
  if (status === 'error' && httpStatus === 410) {
    return (
      <Shell>
        <StateCard icon={<Clock size={26} style={{ color: 'var(--accent)' }} />} title="لینک پرداخت منقضی شده است">
          <p>اعتبار این لینک پرداخت به پایان رسیده است. برای دریافت لینک تازه با پشتیبانی در تماس باشید.</p>
        </StateCard>
      </Shell>
    );
  }

  // ── Inaccessible token (unknown / revoked) ──────────────────────────
  if (status === 'error' && httpStatus === 404) {
    return (
      <Shell>
        <StateCard icon={<Ban size={26} style={{ color: '#ef4444' }} />} title="این لینک پرداخت در دسترس نیست">
          <p>لینک نامعتبر است یا دیگر فعال نیست. لطفاً از پشتیبانی بخواهید لینک به‌روز را برایتان بفرستد.</p>
        </StateCard>
      </Shell>
    );
  }

  // ── Any other load failure ──────────────────────────────────────────
  if (status === 'error') {
    return (
      <Shell>
        <StateCard icon={<AlertTriangle size={26} style={{ color: '#f59e0b' }} />} title="بارگذاری فاکتور ناموفق بود">
          <p role="alert">{loadError}</p>
          <button type="button" className="btn-primary inline-flex items-center gap-2" onClick={() => load()}>
            <ArrowRight size={16} />
            تلاش دوباره
          </button>
        </StateCard>
      </Shell>
    );
  }

  const state = invoice?.state;

  // ── Already paid ────────────────────────────────────────────────────
  if (state === 'paid') {
    return (
      <Shell>
        <StateCard icon={<CheckCircle2 size={26} style={{ color: 'var(--success, #22c55e)' }} />} title="این فاکتور پرداخت شده است">
          <p>پرداخت این فاکتور پیش‌تر ثبت شده و مبلغ قابل پرداخت دیگری وجود ندارد.</p>
        </StateCard>
      </Shell>
    );
  }

  // ── Revoked (defensive: server normally answers 404 for a revoked link) ──
  if (state === 'revoked') {
    return (
      <Shell>
        <StateCard icon={<Ban size={26} style={{ color: '#ef4444' }} />} title="این لینک لغو شده است">
          <p>این لینک پرداخت توسط پشتیبانی لغو شده است. برای دریافت لینک تازه با ما در تماس باشید.</p>
        </StateCard>
      </Shell>
    );
  }

  // ── Not payable (any non-approved state) ────────────────────────────
  if (state !== 'approved') {
    return (
      <Shell>
        <StateCard icon={<XCircle size={26} style={{ color: '#f59e0b' }} />} title="این فاکتور آماده پرداخت نیست">
          <p>امکان پرداخت برای این فاکتور فعال نیست. برای بررسی با پشتیبانی در تماس باشید.</p>
        </StateCard>
      </Shell>
    );
  }

  const submitting = payState === 'submitting';

  return (
    <Shell>
      <div
        className="card rounded-2xl border overflow-hidden animate-fade-in"
        style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
      >
        <div className="p-5 sm:p-6 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h1 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            پرداخت فاکتور
          </h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            مبالغ نهایی‌شده توسط کارشناسان ما — فقط پرداخت دیجی‌پی در دسترس است.
          </p>
        </div>

        {/* Items */}
        <section className="p-5 sm:p-6 space-y-3" aria-label="اقلام فاکتور">
          {items.map((item, index) => (
            <div
              key={`${item.description}-${index}`}
              className="flex items-start justify-between gap-3 rounded-xl border p-3"
              style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text-primary)' }}>
                  {item.description}
                </p>
                <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {item.qty} × {formatPrice(item.unit_toman)}
                </p>
              </div>
              <span className="text-sm font-bold tabular-nums shrink-0" style={{ color: 'var(--text-primary)' }}>
                {formatPrice(item.line_total_toman)}
              </span>
            </div>
          ))}

          {invoice?.specification ? (
            <div
              className="rounded-xl border p-3"
              style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
            >
              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text-secondary)' }}>
                مشخصات نهایی
              </p>
              <p className="text-xs leading-relaxed whitespace-pre-line" style={{ color: 'var(--text-primary)' }}>
                {invoice.specification}
              </p>
            </div>
          ) : null}
        </section>

        {/* Totals */}
        <section className="px-5 sm:px-6 pb-2 space-y-2" aria-label="جمع فاکتور">
          <div className="flex items-center justify-between text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span>جمع اقلام</span>
            <span className="tabular-nums" data-testid="invoice-subtotal">
              {formatPrice(subtotal)}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span>هزینه ارسال</span>
            <span className="tabular-nums" data-testid="invoice-shipping">
              {formatPrice(invoice.shipping_toman || 0)}
            </span>
          </div>
          <div
            className="flex items-center justify-between pt-3 mt-1 border-t"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              مبلغ قابل پرداخت
            </span>
            <span
              className="text-lg font-extrabold tabular-nums"
              style={{ color: 'var(--accent)' }}
              data-testid="invoice-total"
            >
              {formatPrice(invoice.total_toman)}
            </span>
          </div>
        </section>

        {/* Payment methods */}
        <fieldset className="p-5 sm:p-6" aria-label="روش پرداخت">
          <legend className="text-xs font-semibold mb-2" style={{ color: 'var(--text-secondary)' }}>
            روش پرداخت
          </legend>
          <div className="space-y-2">
            {PAYMENT_METHODS.map((method) => (
              <label
                key={method.id}
                className="flex items-center justify-between gap-3 rounded-xl border p-3"
                style={{
                  borderColor: method.enabled ? 'var(--accent)' : 'var(--border-color)',
                  backgroundColor: method.enabled ? 'var(--accent-light, rgba(99,102,241,0.12))' : 'var(--bg-secondary)',
                  opacity: method.enabled ? 1 : 0.55,
                  cursor: method.enabled ? 'pointer' : 'not-allowed',
                }}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="payment-method"
                    value={method.id}
                    checked={method.enabled}
                    disabled={!method.enabled}
                    readOnly
                  />
                  <CreditCard size={16} style={{ color: method.enabled ? 'var(--accent)' : 'var(--text-muted)' }} />
                  <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {method.label}
                  </span>
                </span>
                {!method.enabled ? (
                  <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                    به‌زودی · غیرفعال
                  </span>
                ) : null}
              </label>
            ))}
          </div>
        </fieldset>

        {payError ? (
          <div className="px-5 sm:px-6">
            <div
              role="alert"
              className="p-3 rounded-xl text-xs leading-relaxed border"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                borderColor: 'rgba(239, 68, 68, 0.35)',
                color: '#ef4444',
              }}
            >
              {payError}
            </div>
          </div>
        ) : null}

        <div className="p-5 sm:p-6 pt-4 space-y-3">
          <button
            type="button"
            className="btn-primary w-full inline-flex items-center justify-center gap-2"
            onClick={handlePay}
            disabled={submitting}
            style={submitting ? { opacity: 0.7, pointerEvents: 'none' } : undefined}
          >
            {submitting ? <Loader2 size={18} className="animate-spin" /> : <ShieldCheck size={18} />}
            {submitting ? 'در حال انتقال به درگاه…' : 'پرداخت با دیجی‌پی'}
          </button>

          {invoice?.expires_at ? (
            <p className="text-[11px] text-center" style={{ color: 'var(--text-muted)' }}>
              اعتبار این لینک تا {new Date(invoice.expires_at).toLocaleDateString('fa-IR')}
            </p>
          ) : null}

          <p className="text-[11px] leading-relaxed text-center" style={{ color: 'var(--text-muted)' }}>
            پس از پرداخت، نتیجه توسط سرور تأیید و ثبت می‌شود. در صورت ناموفق بودن، می‌توانید دوباره از همین صفحه
            تلاش کنید.
          </p>

          <div className="text-center">
            <Link to="/how-to-order" className="text-xs underline" style={{ color: 'var(--text-secondary)' }}>
              راهنمای سفارش
            </Link>
          </div>
        </div>
      </div>
    </Shell>
  );
}
