import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Package,
  Receipt,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { formatPrice } from '../lib/constants';
import { getPublicInvoice, payInvoice } from '../lib/commerceApi';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';
import PaymentShell from '../components/PaymentShell';

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

/* ── Gateway Logos (Vector SVGs) ────────────────────────────────────────── */

function DigiPayLogo({ className = 'w-7 h-7' }) {
  return (
    <svg className={className} viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="36" height="36" rx="9" fill="#0040FF" />
      <path
        d="M10.5 10C10.5 9.17 11.17 8.5 12 8.5H17.5C22.19 8.5 26 12.31 26 17C26 21.69 22.19 25.5 17.5 25.5H12C11.17 25.5 10.5 24.83 10.5 24V10Z"
        fill="white"
        fillOpacity="0.25"
      />
      <path
        d="M13.5 11.5C13.5 10.67 14.17 10 15 10H18C21.31 10 24 12.69 24 16C24 19.31 21.31 22 18 22H15C14.17 22 13.5 21.33 13.5 20.5V11.5Z"
        fill="white"
      />
      <circle cx="18" cy="16" r="2.75" fill="#0040FF" />
    </svg>
  );
}

function SnappPayLogo({ className = 'w-7 h-7' }) {
  return (
    <svg className={className} viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="36" height="36" rx="9" fill="#E6123D" />
      <path
        d="M18 9C19.1 9 20 9.9 19.9 20.5H16.1C16 9.9 16.9 9 18 9Z"
        fill="white"
      />
      <circle cx="18" cy="25" r="2.2" fill="white" />
    </svg>
  );
}

function BitPayLogo({ className = 'w-7 h-7' }) {
  return (
    <svg className={className} viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="36" height="36" rx="9" fill="#0C2340" />
      <path
        d="M13 9.5C13 8.95 13.45 8.5 14 8.5H19.5C22.2 8.5 24.2 10.4 24.2 12.8C24.2 14.3 23.3 15.6 22 16.2C23.6 16.8 24.8 18.3 24.8 20.2C24.8 22.8 22.6 24.9 19.8 24.9H14C13.45 24.9 13 24.45 13 23.9V9.5Z"
        fill="#1976D2"
      />
      <path
        d="M15.5 11H19C20.38 11 21.5 11.9 21.5 13C21.5 14.1 20.38 15 19 15H15.5V11ZM15.5 17H19.5C21 17 22.2 17.9 22.2 19.1C22.2 20.3 21 21.2 19.5 21.2H15.5V17Z"
        fill="white"
      />
    </svg>
  );
}

// DigiPay is the sole enabled method. The disabled entries are display-only cards.
const PAYMENT_METHODS = [
  {
    id: 'digipay',
    label: 'دیجی‌پی',
    subtitle: 'کارت‌های بانکی عضو شتاب',
    badge: 'فعال',
    enabled: true,
    Logo: DigiPayLogo,
  },
  {
    id: 'snapppay',
    label: 'اسنپ‌پی',
    subtitle: 'پرداخت اقساطی ۴ ماهه',
    badge: 'به‌زودی',
    enabled: false,
    Logo: SnappPayLogo,
  },
  {
    id: 'bitpay',
    label: 'بیت‌پی',
    subtitle: 'درگاه پرداخت مستقیم',
    badge: 'به‌زودی',
    enabled: false,
    Logo: BitPayLogo,
  },
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

function StateCard({ icon, title, children }) {
  return (
    <div
      className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in shadow-sm"
      style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
    >
      <div
        className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: 'var(--accent-light, rgba(255, 154, 61, 0.12))' }}
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
      <PaymentShell>
        <div
          className="card p-8 rounded-2xl border text-center shadow-sm"
          style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
        >
          <Loader2 size={32} className="animate-spin mx-auto mb-3" style={{ color: 'var(--brand-orange, #ff9a3d)' }} />
          <p role="status" className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
            در حال بارگذاری صورت‌حساب…
          </p>
        </div>
      </PaymentShell>
    );
  }

  // ── Expired (server answered 410) ───────────────────────────────────
  if (status === 'error' && httpStatus === 410) {
    return (
      <PaymentShell>
        <StateCard
          icon={<Clock size={28} style={{ color: 'var(--brand-orange, #ff9a3d)' }} />}
          title="لینک پرداخت منقضی شده است"
        >
          <p>اعتبار زمانی این فاکتور به پایان رسیده است. جهت دریافت لینک پرداخت جدید با پشتیبانی در تماس باشید.</p>
          <div className="pt-2">
            <Link
              to="/contact"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white"
              style={{ background: 'var(--brand-orange, #ff9a3d)' }}
            >
              تماس با پشتیبانی
            </Link>
          </div>
        </StateCard>
      </PaymentShell>
    );
  }

  // ── Inaccessible token (unknown / revoked) ──────────────────────────
  if (status === 'error' && httpStatus === 404) {
    return (
      <PaymentShell>
        <StateCard icon={<Ban size={28} style={{ color: '#ef4444' }} />} title="این لینک پرداخت در دسترس نیست">
          <p>لینک نامعتبر است یا قبلاً لغو شده است. لطفاً از پشتیبانی بخواهید لینک به‌روز را برایتان ارسال کند.</p>
          <div className="pt-2">
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white"
              style={{ background: 'var(--brand-orange, #ff9a3d)' }}
            >
              بازگشت به سایت
            </Link>
          </div>
        </StateCard>
      </PaymentShell>
    );
  }

  // ── Any other load failure ──────────────────────────────────────────
  if (status === 'error') {
    return (
      <PaymentShell>
        <StateCard icon={<AlertTriangle size={28} style={{ color: '#f59e0b' }} />} title="بارگذاری فاکتور ناموفق بود">
          <p role="alert">{loadError}</p>
          <button
            type="button"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white mt-2 cursor-pointer transition-transform active:scale-95"
            style={{ background: 'var(--brand-orange, #ff9a3d)' }}
            onClick={() => load()}
          >
            <RotateCcw size={15} />
            تلاش دوباره
          </button>
        </StateCard>
      </PaymentShell>
    );
  }

  const state = invoice?.state;

  // ── Already paid ────────────────────────────────────────────────────
  if (state === 'paid') {
    return (
      <PaymentShell>
        <StateCard
          icon={<CheckCircle2 size={28} style={{ color: 'var(--success, #16a34a)' }} />}
          title="این فاکتور پرداخت شده است"
        >
          <p>پرداخت این صورت‌حساب پیش‌تر ثبت شده و مبلغ قابل پرداخت دیگری وجود ندارد.</p>
          <div className="pt-2">
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white"
              style={{ background: 'var(--brand-orange, #ff9a3d)' }}
            >
              مشاهده محصولات دیگر
            </Link>
          </div>
        </StateCard>
      </PaymentShell>
    );
  }

  // ── Revoked (defensive: server normally answers 404 for a revoked link) ──
  if (state === 'revoked') {
    return (
      <PaymentShell>
        <StateCard icon={<Ban size={28} style={{ color: '#ef4444' }} />} title="این لینک لغو شده است">
          <p>این لینک پرداخت توسط پشتیبانی لغو شده است. برای دریافت لینک تازه با ما در تماس باشید.</p>
        </StateCard>
      </PaymentShell>
    );
  }

  // ── Not payable (any non-approved state) ────────────────────────────
  if (state !== 'approved') {
    return (
      <PaymentShell>
        <StateCard icon={<XCircle size={28} style={{ color: '#f59e0b' }} />} title="این فاکتور آماده پرداخت نیست">
          <p>امکان پرداخت برای این فاکتور فعال نیست. برای بررسی با پشتیبانی در تماس باشید.</p>
        </StateCard>
      </PaymentShell>
    );
  }

  const submitting = payState === 'submitting';

  return (
    <PaymentShell>
      <div
        className="card rounded-2xl border overflow-hidden animate-fade-in shadow-md"
        style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
      >
        {/* Invoice Header */}
        <div
          className="p-5 sm:p-6 border-b flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
          style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary, #eef1f9)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm"
              style={{
                background: 'linear-gradient(135deg, var(--brand-orange, #ff9a3d) 0%, var(--brand-orange-deep, #e07b2c) 100%)',
                color: '#ffffff',
              }}
            >
              <Receipt size={20} />
            </div>
            <div>
              <h1 className="text-base sm:text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                صورت‌حساب سفارش
              </h1>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                مبالغ نهایی‌شده با هماهنگی در پیام‌رسان
              </p>
            </div>
          </div>

          <span
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold"
            style={{
              backgroundColor: 'rgba(34, 197, 94, 0.12)',
              color: 'var(--success, #16a34a)',
              border: '1px solid rgba(34, 197, 94, 0.3)',
            }}
          >
            <CheckCircle2 size={13} />
            تأیید شده برای پرداخت
          </span>
        </div>

        {/* Items List */}
        <section className="p-5 sm:p-6 space-y-3" aria-label="اقلام فاکتور">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-bold" style={{ color: 'var(--text-secondary)' }}>
              اقلام سفارش ({items.length})
            </span>
          </div>

          {items.map((item, index) => (
            <div
              key={`${item.description}-${index}`}
              className="flex items-start justify-between gap-3 rounded-xl border p-3.5 transition-colors hover:border-[var(--brand-orange)]"
              style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-card, #ffffff)' }}
            >
              <div className="min-w-0 flex items-start gap-2.5">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                  style={{ backgroundColor: 'var(--bg-secondary, #eef1f9)', color: 'var(--brand-orange, #ff9a3d)' }}
                >
                  <Package size={16} />
                </div>
                <div>
                  <p className="text-sm font-semibold leading-snug" style={{ color: 'var(--text-primary)' }}>
                    {item.description}
                  </p>
                  <p className="text-xs mt-1 tabular-nums" style={{ color: 'var(--text-muted)' }}>
                    <span className="font-bold">{item.qty}</span> عدد × {formatPrice(item.unit_toman)} تومان
                  </p>
                </div>
              </div>
              <div className="text-left shrink-0">
                <span className="text-sm font-bold tabular-nums block" style={{ color: 'var(--text-primary)' }}>
                  {formatPrice(item.line_total_toman)}
                </span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>تومان</span>
              </div>
            </div>
          ))}

          {/* Finalized Specifications Callout */}
          {invoice?.specification ? (
            <div
              className="rounded-xl border p-3.5 mt-2"
              style={{
                borderColor: 'color-mix(in srgb, var(--brand-orange, #ff9a3d) 30%, var(--border-color))',
                backgroundColor: 'rgba(255, 154, 61, 0.04)',
              }}
            >
              <div className="flex items-center gap-1.5 mb-1.5">
                <FileText size={14} style={{ color: 'var(--brand-orange, #ff9a3d)' }} />
                <span className="text-xs font-bold" style={{ color: 'var(--brand-orange-deep, #e07b2c)' }}>
                  مشخصات توافق‌شده سفارش
                </span>
              </div>
              <p className="text-xs leading-relaxed whitespace-pre-line" style={{ color: 'var(--text-primary)' }}>
                {invoice.specification}
              </p>
            </div>
          ) : null}
        </section>

        {/* Totals Breakdown */}
        <section
          className="mx-5 sm:mx-6 p-4 rounded-xl border space-y-2.5"
          style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary, #eef1f9)' }}
          aria-label="جمع فاکتور"
        >
          <div className="flex items-center justify-between text-xs sm:text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span>جمع اقلام</span>
            <span className="tabular-nums font-semibold" data-testid="invoice-subtotal">
              {formatPrice(subtotal)} تومان
            </span>
          </div>
          <div className="flex items-center justify-between text-xs sm:text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span>هزینه بسته‌بندی و ارسال</span>
            <span className="tabular-nums font-semibold" data-testid="invoice-shipping">
              {formatPrice(invoice.shipping_toman || 0)} تومان
            </span>
          </div>
          <div
            className="flex items-center justify-between pt-3 border-t"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              مبلغ قابل پرداخت:
            </span>
            <div className="text-left">
              <span
                className="text-xl sm:text-2xl font-black tabular-nums"
                style={{ color: 'var(--brand-orange-deep, #e07b2c)' }}
                data-testid="invoice-total"
              >
                {formatPrice(invoice.total_toman)}
              </span>
              <span className="text-xs font-semibold mr-1.5" style={{ color: 'var(--brand-orange-deep, #e07b2c)' }}>
                تومان
              </span>
            </div>
          </div>
        </section>

        {/* Payment Methods (Box Button Style) */}
        <fieldset className="p-5 sm:p-6" aria-label="روش پرداخت">
          <div className="flex items-center justify-between mb-3">
            <legend className="text-xs sm:text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              انتخاب روش پرداخت
            </legend>
            <span className="text-[11px] font-medium" style={{ color: 'var(--text-muted)' }}>
              اتصال رسمی شاپرک
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {PAYMENT_METHODS.map((method) => {
              const LogoComp = method.Logo;
              const isSelected = method.enabled;
              return (
                <label
                  key={method.id}
                  className="relative flex flex-col justify-between p-3.5 rounded-2xl border transition-all text-right select-none"
                  style={{
                    borderColor: isSelected ? 'var(--brand-orange, #ff9a3d)' : 'var(--border-color)',
                    backgroundColor: isSelected ? 'rgba(255, 154, 61, 0.06)' : 'var(--bg-secondary, #eef1f9)',
                    boxShadow: isSelected
                      ? '0 4px 14px rgba(255, 154, 61, 0.2), 0 0 0 1px var(--brand-orange, #ff9a3d)'
                      : 'none',
                    opacity: method.enabled ? 1 : 0.6,
                    cursor: method.enabled ? 'pointer' : 'not-allowed',
                  }}
                >
                  {/* Semantic Radio Input for accessibility and test suites */}
                  <input
                    type="radio"
                    name="payment-method"
                    value={method.id}
                    checked={method.enabled}
                    disabled={!method.enabled}
                    readOnly
                    className="sr-only"
                    aria-label={method.label}
                  />

                  {/* Card Top: Logo & Status Badge */}
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <div className="p-0.5 rounded-xl bg-white shadow-sm border border-black/5 shrink-0 flex items-center justify-center">
                      <LogoComp className="w-8 h-8" />
                    </div>
                    {method.enabled ? (
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
                        style={{
                          backgroundColor: 'rgba(34, 197, 94, 0.12)',
                          color: 'var(--success, #16a34a)',
                          border: '1px solid rgba(34, 197, 94, 0.25)',
                        }}
                      >
                        <CheckCircle2 size={11} />
                        {method.badge}
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium"
                        style={{
                          backgroundColor: 'rgba(100, 116, 139, 0.12)',
                          color: 'var(--text-muted)',
                          border: '1px solid var(--border-color)',
                        }}
                      >
                        {method.badge}
                      </span>
                    )}
                  </div>

                  {/* Card Body: Title & Subtitle */}
                  <div>
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                        {method.label}
                      </span>
                      {isSelected ? (
                        <div
                          className="w-4 h-4 rounded-full flex items-center justify-center shrink-0"
                          style={{ backgroundColor: 'var(--brand-orange, #ff9a3d)' }}
                          aria-hidden="true"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-white" />
                        </div>
                      ) : null}
                    </div>
                    <p className="text-[11px] mt-1 leading-snug line-clamp-1" style={{ color: 'var(--text-muted)' }}>
                      {method.subtitle}
                    </p>
                  </div>
                </label>
              );
            })}
          </div>
        </fieldset>

        {payError ? (
          <div className="px-5 sm:px-6">
            <div
              role="alert"
              className="p-3.5 rounded-xl text-xs leading-relaxed border flex items-start gap-2"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                borderColor: 'rgba(239, 68, 68, 0.35)',
                color: '#ef4444',
              }}
            >
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <span>{payError}</span>
            </div>
          </div>
        ) : null}

        {/* Action Button & Security Notes */}
        <div className="p-5 sm:p-6 pt-3 space-y-3.5">
          <button
            type="button"
            className="w-full inline-flex items-center justify-center gap-2.5 py-3.5 px-6 rounded-xl font-bold text-sm text-white shadow-md cursor-pointer transition-all hover:brightness-105 active:scale-[0.99] disabled:cursor-not-allowed"
            onClick={handlePay}
            disabled={submitting}
            style={{
              background: 'linear-gradient(135deg, var(--brand-orange, #ff9a3d) 0%, var(--brand-orange-deep, #e07b2c) 100%)',
              boxShadow: '0 4px 16px rgba(224, 123, 44, 0.35)',
              opacity: submitting ? 0.75 : 1,
            }}
          >
            {submitting ? (
              <Loader2 size={19} className="animate-spin" />
            ) : (
              <ShieldCheck size={19} />
            )}
            {submitting ? 'در حال انتقال به درگاه…' : 'پرداخت با دیجی‌پی'}
          </button>

          {invoice?.expires_at ? (
            <p className="text-[11px] text-center flex items-center justify-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <Clock size={13} className="text-[var(--brand-orange)]" />
              اعتبار این لینک تا {new Date(invoice.expires_at).toLocaleDateString('fa-IR')}
            </p>
          ) : null}

          <div
            className="flex items-start gap-2 p-3 rounded-xl border text-[11px] leading-relaxed text-right"
            style={{
              backgroundColor: 'var(--bg-secondary, #eef1f9)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-muted)',
            }}
          >
            <ShieldCheck size={16} className="shrink-0 mt-0.5 text-[var(--brand-orange)]" />
            <span>
              پرداخت در بستر امن درگاه دیجی‌پی (شاپرک) انجام می‌شود. پس از واریز، نتیجه به‌طور مستقیم به سیستم فروشگاه مخابره خواهد شد.
            </span>
          </div>
        </div>
      </div>
    </PaymentShell>
  );
}
