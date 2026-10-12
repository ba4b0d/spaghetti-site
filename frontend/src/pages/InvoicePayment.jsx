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
import { getPaymentMethods, getPublicInvoice, payInvoice, getPublicInvoicePdfUrl } from '../lib/commerceApi';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';
import { GATEWAY_HANDOFF_PATH, isHandoffStorageAvailable, writeGatewayHandoff } from '../lib/paymentHandoff';
import { writePaymentReceipt } from '../lib/paymentReceipt';
import {
  ALLOWED_GATEWAY_HOSTS,
  GATEWAY_ALLOWLIST,
  validateGatewayUrl,
} from '../lib/gatewayValidation';
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
 * state it reads. The set of *selectable* gateways is not hard-coded here: it
 * comes from the backend's non-secret readiness endpoint
 * (``GET …/payment-methods``). BitPay is a selectable choice only when the
 * server reports it configured for a test deployment; DigiPay stays parked and
 * SnappPay is disabled, so a non-payable method can never look payable.
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

// Display catalog (order = presentation order). Whether a card is *selectable*
// is decided at runtime from the backend readiness endpoint, never hard-coded:
// `enabledMethods` below is the single source of truth for that.
const PAYMENT_METHODS = [
  {
    id: 'bitpay',
    label: 'بیت‌پی',
    subtitle: 'درگاه پرداخت مستقیم',
    badge: 'فعال',
    Logo: BitPayLogo,
  },
  {
    id: 'digipay',
    label: 'دیجی‌پی',
    subtitle: 'کارت‌های بانکی عضو شتاب',
    badge: 'غیرفعال',
    Logo: DigiPayLogo,
  },
  {
    id: 'snapppay',
    label: 'اسنپ‌پی',
    subtitle: 'پرداخت اقساطی ۴ ماهه',
    badge: 'به‌زودی',
    Logo: SnappPayLogo,
  },
];

// Per-provider gateway allowlist + validator now live in
// ``../lib/gatewayValidation`` so the pay page AND the token-free hand-off page
// validate against one set of rules. Re-exported here unchanged so existing
// importers (and tests) keep working.
export { ALLOWED_GATEWAY_HOSTS, GATEWAY_ALLOWLIST, validateGatewayUrl };

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

/**
 * Shown when the gateway hand-off cannot be set up safely because the browser
 * gives us no per-tab sessionStorage to park the validated portal URL in.
 *
 * We must NOT fall back to navigating the portal straight from this document:
 * it is served `Referrer-Policy: no-referrer` (the path segment is a bearer
 * token), so the browser sends no Referer and BitPay rejects the hand-off with
 * «آدرس ارجاعی نامعتبر» — a known-broken dead end. Failing here with an
 * actionable message (and leaving the CTA in place so the customer can retry
 * once storage is available) is the safe behaviour.
 */
export const PAYMENT_STORAGE_UNAVAILABLE_MESSAGE =
  'برای انتقال امن به درگاه پرداخت، مرورگر شما باید «حافظهٔ موقت نشست» (session storage) را فعال کند. لطفاً حالت ناشناس مرورگر را ببندید یا اجازهٔ ذخیره‌سازی را بدهید و دوباره تلاش کنید.';

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

  // Non-secret gateway readiness from the server. `null` until it resolves, so
  // nothing is selectable while we do not yet know what the server supports.
  const [methods, setMethods] = useState(null);
  const [selectedMethod, setSelectedMethod] = useState(null);

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

  // Read the server's gateway readiness once. A failure is fail-closed: without
  // a positive signal nothing becomes selectable, so the page can never offer a
  // method the backend cannot actually pay through.
  useEffect(() => {
    const controller = new AbortController();
    getPaymentMethods({ signal: controller.signal })
      .then((res) => {
        if (mountedRef.current) setMethods(res?.data || {});
      })
      .catch((err) => {
        if (isCancel(err) || !mountedRef.current) return;
        setMethods({});
      });
    return () => controller.abort();
  }, []);

  const enabledMethods = useMemo(() => {
    const map = {};
    for (const method of PAYMENT_METHODS) {
      map[method.id] = Boolean(methods?.[method.id]?.enabled);
    }
    return map;
  }, [methods]);

  // Keep the selection on the first enabled gateway (BitPay is the only one the
  // server ever enables); never leave a stale selection on a now-disabled one.
  useEffect(() => {
    const firstEnabled = PAYMENT_METHODS.find((m) => enabledMethods[m.id])?.id ?? null;
    setSelectedMethod(firstEnabled);
  }, [enabledMethods]);

  const handlePay = useCallback(async () => {
    if (payState === 'submitting' || !selectedMethod) return;
    setPayError(null);

    // The gateway hand-off REQUIRES per-tab sessionStorage: it is how the
    // validated portal URL is parked for the token-free /pay/redirect page. With
    // no usable storage there is no safe hand-off, and navigating the portal
    // straight from this `no-referrer` document is known-broken (BitPay answers
    // «آدرس ارجاعی نامعتبر»). Detect that HERE — before creating a server-side
    // payment attempt — so the customer gets an actionable error and a clean
    // retry, instead of a dangling attempt and a rejected portal page.
    if (!isHandoffStorageAvailable()) {
      setPayState('error');
      setPayError(PAYMENT_STORAGE_UNAVAILABLE_MESSAGE);
      return;
    }

    setPayState('submitting');
    try {
      const res = await payInvoice(token, selectedMethod);
      const data = res?.data || {};
      const target = validateGatewayUrl(data.redirect_url, selectedMethod);
      if (!target) {
        // Never follow an unvalidated URL: refuse and let the customer retry.
        setPayState('error');
        setPayError('آدرس درگاه پرداخت معتبر نیست؛ به دلایل امنیتی انتقال انجام نشد.');
        return;
      }
      // Do NOT navigate to the portal straight from this document: it is served
      // `Referrer-Policy: no-referrer` (the path segment is a bearer token), so
      // the browser would send no Referer and BitPay would reject the hand-off
      // with «آدرس ارجاعی نامعتبر». Park the validated URL in per-tab
      // sessionStorage and hard-navigate to the token-free /pay/redirect page,
      // which emits an origin-only Referer. If the write fails anyway (storage
      // vanished between the check above and here) fail safe rather than send
      // the customer to a portal page that will reject them.
      if (!writeGatewayHandoff(target, selectedMethod)) {
        setPayState('error');
        setPayError(PAYMENT_STORAGE_UNAVAILABLE_MESSAGE);
        return;
      }
      // Park the private invoice token for the token-free result page, so that
      // after the gateway round-trip it can re-read the SERVER-VERIFIED invoice
      // state and show the customer a TRUTHFUL confirmation (invoice number +
      // amount) instead of a generic "we received your request". Best-effort:
      // the hand-off must not be gated by it — without the receipt the result
      // page just shows its generic, fail-closed copy. It is parked under its
      // OWN key, so the (token-free) hand-off entry above still never carries
      // the bearer token, and it never enters a URL, query or log.
      writePaymentReceipt(token);
      redirect(GATEWAY_HANDOFF_PATH);
      if (mountedRef.current) setPayState('idle');
    } catch (err) {
      if (isCancel(err) || !mountedRef.current) return;
      setPayState('error');
      const status = err?.response?.status;
      if (status === 503) {
        // The gateway is not configured/available right now — say so plainly
        // instead of echoing a raw server string.
        setPayError(
          'درگاه پرداخت در حال حاضر در دسترس نیست؛ لطفاً کمی بعد دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.'
        );
      } else {
        // 409 conflicts (another attempt in flight / already paid) surface the
        // server's own explanation.
        setPayError(extractPaymentError(err));
      }
    }
  }, [payState, selectedMethod, token, redirect]);

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
  const selectedMeta = PAYMENT_METHODS.find((m) => m.id === selectedMethod) || null;

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
                    <span className="font-bold">{item.qty}</span> عدد × {formatPrice(item.unit_toman)}
                  </p>
                </div>
              </div>
              <div className="text-left shrink-0">
                <span className="text-sm font-bold tabular-nums block" style={{ color: 'var(--text-primary)' }}>
                  {formatPrice(item.line_total_toman)}
                </span>
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
              {formatPrice(subtotal)}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs sm:text-sm" style={{ color: 'var(--text-secondary)' }}>
            <span>هزینه بسته‌بندی و ارسال</span>
            <span className="tabular-nums font-semibold" data-testid="invoice-shipping">
              {formatPrice(invoice.shipping_toman || 0)}
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
              const isEnabled = enabledMethods[method.id];
              const isSelected = isEnabled && selectedMethod === method.id;
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
                    opacity: isEnabled ? 1 : 0.6,
                    cursor: isEnabled ? 'pointer' : 'not-allowed',
                  }}
                >
                  {/* Semantic Radio Input for accessibility and test suites */}
                  <input
                    type="radio"
                    name="payment-method"
                    value={method.id}
                    checked={isSelected}
                    disabled={!isEnabled}
                    onChange={() => isEnabled && setSelectedMethod(method.id)}
                    className="sr-only"
                    aria-label={method.label}
                  />

                  {/* Card Top: Logo & Status Badge */}
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <div className="p-0.5 rounded-xl bg-white shadow-sm border border-black/5 shrink-0 flex items-center justify-center">
                      <LogoComp className="w-8 h-8" />
                    </div>
                    {isEnabled ? (
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
          {selectedMeta ? (
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
              {submitting ? 'در حال انتقال به درگاه…' : `پرداخت با ${selectedMeta.label}`}
            </button>
          ) : (
            <div
              role="status"
              data-testid="payment-unavailable"
              className="w-full p-4 rounded-xl border text-center text-xs leading-relaxed"
              style={{
                backgroundColor: 'var(--bg-secondary, #eef1f9)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-secondary)',
              }}
            >
              <AlertTriangle size={18} className="mx-auto mb-2" style={{ color: '#f59e0b' }} />
              پرداخت آنلاین این صورت‌حساب در حال حاضر فعال نیست. لطفاً با پشتیبانی تماس بگیرید تا پرداخت را برای شما هماهنگ کنند.
            </div>
          )}

          <a
            href={getPublicInvoicePdfUrl(token)}
            target="_blank"
            rel="noopener noreferrer"
            download={`spaghetti-invoice-${invoice?.id || 'order'}.pdf`}
            className="w-full inline-flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-bold text-xs border transition-all hover:bg-black/5 dark:hover:bg-white/5 cursor-pointer text-center"
            style={{
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
              backgroundColor: 'var(--bg-secondary, #eef1f9)',
            }}
          >
            <FileText size={16} className="text-[var(--brand-orange)]" />
            دریافت نسخه PDF فاکتور
          </a>

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
              پرداخت در بستر امن درگاه (شاپرک) انجام می‌شود. پس از واریز، نتیجه به‌طور مستقیم به سیستم فروشگاه مخابره خواهد شد.
            </span>
          </div>
        </div>
      </div>
    </PaymentShell>
  );
}
