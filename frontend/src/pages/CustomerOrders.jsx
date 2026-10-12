import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Clock,
  FileText,
  Inbox,
  Loader2,
  LogOut,
  Package,
  Receipt,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { formatPrice } from '../lib/utils';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';
import {
  getCustomerHistory,
  requestHistoryOtp,
  signOutHistory,
  verifyHistoryOtp,
} from '../lib/commerceHistoryApi';
import {
  clearHistorySession,
  readHistorySession,
  writeHistorySession,
} from '../lib/commerceHistorySession';

/**
 * Public one-visit «سفارش‌های من» page.
 *
 * A customer proves ownership of a mobile number with an SMS code and sees the
 * website requests and staff-created invoices tied to *that exact number* — no
 * account, no password, no persistent login. The verified bearer lives only in
 * this tab's ``sessionStorage`` (see ``commerceHistorySession``); it is never
 * put in a URL, a cookie, ``localStorage`` or a service-worker cache, and a
 * sign-out or an invalid session wipes it *and* the in-memory history before
 * anything else.
 *
 * The page is read-only. It never reconstructs or issues a payment link: an
 * approved invoice whose raw (hashed-at-rest) link cannot be recovered shows a
 * «تماس با پشتیبانی» note instead of a pay button, and paid/revoked entries
 * have no action at all. Statuses come from the server; nothing is inferred
 * from a redirect query parameter.
 */

const MOBILE_RE = /^09\d{9}$/;
const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
const PAGE_SIZE = 20;

/** Server-owned states → customer-safe Persian labels. */
export const HISTORY_STATE_LABELS = Object.freeze({
  pending_review: 'در حال بررسی',
  converted: 'تبدیل‌شده به فاکتور',
  draft: 'پیش‌نویس',
  approved: 'تأییدشده',
  paid: 'پرداخت‌شده',
  revoked: 'لغو‌شده',
});

/** Neutral fallback for any state the client does not recognise. */
export const UNKNOWN_STATE_LABEL = 'وضعیت نامشخص';

/** Shown for an approved invoice — its raw payment link is not recoverable. */
export const PAYMENT_SUPPORT_MESSAGE =
  'برای دریافت لینک پرداخت با پشتیبانی تماس بگیرید.';

export const RATE_LIMIT_MESSAGE =
  'تعداد درخواست‌ها بیش از حد مجاز است؛ لطفاً کمی بعد دوباره تلاش کنید.';

const KIND_LABELS = { request: 'درخواست از سایت', invoice: 'فاکتور' };
const KIND_ICONS = { request: Package, invoice: Receipt };

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

const cleanMobile = (value) => normalizeDigits(value).replace(/\s+/g, '');

/** Human-readable message from an Axios/FastAPI error. */
function extractError(err, fallback) {
  const data = err?.response?.data;
  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'string' && first.trim()) return first;
    if (first?.msg) return String(first.msg);
  }
  if (typeof data?.message === 'string' && data.message.trim()) return data.message;
  return fallback;
}

const isCancel = (err) => err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED';

const stateLabel = (state) => HISTORY_STATE_LABELS[state] || UNKNOWN_STATE_LABEL;

const STATE_TONES = {
  pending_review: { color: '#d97706', bg: 'rgba(245,158,11,0.15)' },
  converted: { color: '#16a34a', bg: 'rgba(34,197,94,0.15)' },
  draft: { color: '#64748b', bg: 'rgba(100,116,139,0.15)' },
  approved: { color: '#16a34a', bg: 'rgba(34,197,94,0.15)' },
  paid: { color: '#0ea5e9', bg: 'rgba(14,165,233,0.15)' },
  revoked: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
};
const NEUTRAL_TONE = { color: '#64748b', bg: 'rgba(100,116,139,0.15)' };

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('fa-IR');
}

function ErrorBox({ children }) {
  return (
    <div
      role="alert"
      className="p-3 rounded-xl text-xs leading-relaxed border"
      style={{
        backgroundColor: 'rgba(239, 68, 68, 0.08)',
        borderColor: 'rgba(239, 68, 68, 0.35)',
        color: '#ef4444',
      }}
    >
      {children}
    </div>
  );
}

function HistoryEntryCard({ entry }) {
  const kind = entry?.kind === 'invoice' ? 'invoice' : 'request';
  const state = entry?.state;
  const label = stateLabel(state);
  const tone = STATE_TONES[state] || NEUTRAL_TONE;
  const items = Array.isArray(entry?.items) ? entry.items : [];
  const KindIcon = KIND_ICONS[kind];
  // Only an approved/paid invoice exposes frozen money; everything else shows
  // names and quantities as a snapshot, never as a final price.
  const showTotals = state === 'approved' || state === 'paid';
  const created = formatDate(entry?.created_at);

  return (
    <article
      data-testid={`entry-${kind}-${entry?.id}`}
      className="card p-4 rounded-2xl border space-y-3"
      style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          <span
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{ backgroundColor: 'var(--bg-secondary)', color: 'var(--brand-orange, #ff9a3d)' }}
            aria-hidden="true"
          >
            <KindIcon size={16} />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              {KIND_LABELS[kind]}
            </p>
            {created ? (
              <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {created}
              </p>
            ) : null}
          </div>
        </div>
        <span
          className="text-[11px] px-2 py-0.5 rounded-full font-bold shrink-0"
          style={{ backgroundColor: tone.bg, color: tone.color }}
        >
          {label}
        </span>
      </header>

      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li
            key={`${item?.name}-${index}`}
            className="flex items-center justify-between gap-2 text-xs"
            style={{ color: 'var(--text-secondary)' }}
          >
            <span className="min-w-0 leading-snug">
              <span className="font-semibold tabular-nums">{item?.qty}×</span>{' '}
              {item?.name || '—'}
            </span>
            {showTotals && item?.line_total_toman != null ? (
              <span className="tabular-nums shrink-0" style={{ color: 'var(--text-primary)' }}>
                {formatPrice(item.line_total_toman)}
              </span>
            ) : null}
          </li>
        ))}
        {items.length === 0 ? (
          <li className="text-xs" style={{ color: 'var(--text-muted)' }}>
            اقلامی ثبت نشده است.
          </li>
        ) : null}
      </ul>

      {showTotals && entry?.total_toman != null ? (
        <div
          data-testid={`entry-total-${kind}-${entry?.id}`}
          className="rounded-xl border p-3 space-y-1.5 text-xs"
          style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
        >
          <div className="flex items-center justify-between" style={{ color: 'var(--text-secondary)' }}>
            <span>هزینه بسته‌بندی و ارسال</span>
            <span className="tabular-nums font-semibold">{formatPrice(entry.shipping_toman || 0)}</span>
          </div>
          <div
            className="flex items-center justify-between pt-1.5 border-t"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
          >
            <span className="font-bold">مبلغ کل</span>
            <span className="tabular-nums font-black">{formatPrice(entry.total_toman)}</span>
          </div>
        </div>
      ) : null}

      {state === 'approved' ? (
        <p
          data-testid="pay-support"
          className="text-[11px] leading-relaxed rounded-xl border p-2.5"
          style={{
            borderColor: 'color-mix(in srgb, var(--brand-orange, #ff9a3d) 30%, var(--border-color))',
            backgroundColor: 'rgba(255, 154, 61, 0.05)',
            color: 'var(--text-secondary)',
          }}
        >
          {PAYMENT_SUPPORT_MESSAGE}
        </p>
      ) : null}
    </article>
  );
}

export default function CustomerOrders() {
  // The page renders a customer's own data; never let a referrer leak it.
  useNoReferrerPolicy();

  const [phase, setPhase] = useState('verify'); // verify | otp | list
  const [token, setToken] = useState(null);
  const [mobile, setMobile] = useState('');
  const [maskedMobile, setMaskedMobile] = useState('');
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [otp, setOtp] = useState(null);
  const [code, setCode] = useState('');
  const [otpError, setOtpError] = useState(null);
  const [resendIn, setResendIn] = useState(0);

  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [listStatus, setListStatus] = useState('idle'); // idle | loading | ready | error
  const [listError, setListError] = useState(null);

  const mountedRef = useRef(true);
  const abortRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  /** Drop everything sensitive and go back to the verification screen. */
  const resetToVerify = useCallback((message = null) => {
    abortRef.current?.abort();
    clearHistorySession();
    setToken(null);
    setItems([]);
    setHasMore(false);
    setListStatus('idle');
    setListError(null);
    setOtp(null);
    setCode('');
    setMaskedMobile('');
    setPhase('verify');
    setFormError(message);
  }, []);

  const handleSessionLost = useCallback(() => {
    resetToVerify('نشست شما معتبر نیست؛ لطفاً دوباره شمارهٔ خود را تأیید کنید.');
  }, [resetToVerify]);

  const loadFirstPage = useCallback(
    (bearer) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setListStatus('loading');
      setListError(null);
      return getCustomerHistory(bearer, { limit: PAGE_SIZE, offset: 0 }, { signal: controller.signal })
        .then((res) => {
          if (!mountedRef.current || controller.signal.aborted) return;
          const data = res?.data || {};
          setItems(Array.isArray(data.items) ? data.items : []);
          setHasMore(Boolean(data.has_more));
          setListStatus('ready');
        })
        .catch((err) => {
          if (controller.signal.aborted || isCancel(err) || !mountedRef.current) return;
          if (err?.response?.status === 401) {
            handleSessionLost();
            return;
          }
          setListError(extractError(err, 'بارگذاری سفارش‌ها ناموفق بود؛ لطفاً دوباره تلاش کنید.'));
          setListStatus('error');
        });
    },
    [handleSessionLost]
  );

  // On mount: a live tab session jumps straight to the list; anything else
  // (absent, malformed or expired) falls back to the OTP screen.
  useEffect(() => {
    const session = readHistorySession();
    if (session) {
      setToken(session.token);
      setPhase('list');
      loadFirstPage(session.token);
    }
  }, [loadFirstPage]);

  // Resend countdown, cleaned up on unmount or when the challenge changes.
  useEffect(() => {
    if (phase !== 'otp') return undefined;
    setResendIn(otp?.resendAfter > 0 ? otp.resendAfter : 0);
    if (!otp?.resendAfter) return undefined;
    const timer = setInterval(() => setResendIn((seconds) => (seconds > 0 ? seconds - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [phase, otp]);

  const startOtp = useCallback(async (clean) => {
    setBusy(true);
    try {
      const res = await requestHistoryOtp({ mobile: clean });
      if (!mountedRef.current) return;
      const data = res?.data || {};
      setOtp({
        challengeId: data.challenge_id,
        maskedMobile: data.masked_mobile || clean,
        resendAfter: Number(data.resend_after) || 0,
      });
      setMaskedMobile(data.masked_mobile || clean);
      setResendIn(Number(data.resend_after) || 0);
      setCode('');
      setOtpError(null);
      setFormError(null);
      setPhase('otp');
    } catch (err) {
      if (isCancel(err) || !mountedRef.current) return;
      const fallback = 'ارسال کد تأیید ناموفق بود؛ لطفاً دوباره تلاش کنید.';
      setFormError(
        err?.response?.status === 429 ? RATE_LIMIT_MESSAGE : extractError(err, fallback)
      );
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, []);

  const submitMobile = (event) => {
    event?.preventDefault?.();
    if (busy) return;
    setFormError(null);
    const clean = cleanMobile(mobile);
    if (!MOBILE_RE.test(clean)) {
      setFormError('شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.');
      return;
    }
    startOtp(clean);
  };

  const resendCode = () => {
    if (busy || resendIn > 0) return;
    setOtpError(null);
    setFormError(null);
    startOtp(cleanMobile(mobile));
  };

  const editMobile = () => {
    setOtp(null);
    setCode('');
    setOtpError(null);
    setFormError(null);
    setPhase('verify');
  };

  const confirmCode = async () => {
    if (busy || !otp) return;
    const cleanCode = normalizeDigits(code).replace(/\D/g, '');
    if (!/^\d{5}$/.test(cleanCode)) {
      setOtpError('کد تأیید ۵ رقمی را وارد کنید.');
      return;
    }
    setOtpError(null);
    setBusy(true);
    try {
      const res = await verifyHistoryOtp({
        mobile: cleanMobile(mobile),
        challenge_id: otp.challengeId,
        code: cleanCode,
      });
      const data = res?.data || {};
      const bearer = typeof data.token === 'string' ? data.token : '';
      if (!bearer) {
        if (mountedRef.current) setOtpError('تأیید کد ناموفق بود؛ لطفاً دوباره تلاش کنید.');
        return;
      }
      // Best effort: keep the bearer in this tab only. If storage is blocked the
      // visit still works in memory and simply does not survive a reload.
      writeHistorySession(bearer, data.expires_at);
      if (!mountedRef.current) return;
      setToken(bearer);
      setOtp(null);
      setCode('');
      setPhase('list');
      loadFirstPage(bearer);
    } catch (err) {
      if (isCancel(err) || !mountedRef.current) return;
      setOtpError(extractError(err, 'کد تأیید نادرست است؛ لطفاً دوباره تلاش کنید.'));
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  const loadMore = () => {
    if (!token || listStatus === 'loading' || !hasMore) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setListStatus('loading');
    setListError(null);
    getCustomerHistory(
      token,
      { limit: PAGE_SIZE, offset: items.length },
      { signal: controller.signal }
    )
      .then((res) => {
        if (!mountedRef.current || controller.signal.aborted) return;
        const data = res?.data || {};
        const next = Array.isArray(data.items) ? data.items : [];
        setItems((prev) => [...prev, ...next]);
        setHasMore(Boolean(data.has_more));
        setListStatus('ready');
      })
      .catch((err) => {
        if (controller.signal.aborted || isCancel(err) || !mountedRef.current) return;
        if (err?.response?.status === 401) {
          handleSessionLost();
          return;
        }
        setListError(extractError(err, 'بارگذاری ادامهٔ سفارش‌ها ناموفق بود.'));
        setListStatus('error');
      });
  };

  const handleSignOut = () => {
    const bearer = token;
    // Wipe locally FIRST: no personal data may survive even if the revoke call
    // never reaches the server.
    resetToVerify(null);
    if (bearer) {
      signOutHistory(bearer).catch(() => {});
    }
  };

  // ── Verification / OTP ──────────────────────────────────────────────
  if (phase !== 'list') {
    const onOtp = phase === 'otp';
    return (
      <div dir="rtl" className="max-w-xl mx-auto animate-fade-in">
        <div
          className="rounded-2xl border p-5 sm:p-6 mb-6"
          style={{
            background: 'var(--brand-header-gradient)',
            borderColor: 'var(--brand-header-border)',
            boxShadow: 'var(--brand-header-shadow)',
            color: 'var(--brand-header-fg)',
          }}
        >
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium mb-3 hover:opacity-80 transition-opacity"
            style={{ color: 'var(--brand-header-fg)' }}
          >
            <ArrowRight size={16} />
            بازگشت به کاتالوگ
          </Link>
          <h1 className="text-xl sm:text-2xl font-bold mb-1">سفارش‌های من</h1>
          <p className="text-xs sm:text-sm" style={{ color: 'color-mix(in srgb, #fff 82%, transparent)' }}>
            برای مشاهدهٔ سفارش‌های ثبت‌شده با شمارهٔ موبایل خود، شماره را وارد و کد پیامکی را تأیید کنید.
          </p>
        </div>

        <form
          data-testid={onOtp ? 'my-orders-otp-step' : 'my-orders-verify'}
          onSubmit={(event) => {
            event.preventDefault();
            if (onOtp) {
              confirmCode();
            } else {
              submitMobile();
            }
          }}
          className="card p-5 sm:p-6 rounded-2xl border space-y-4"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
          noValidate
        >
          {!onOtp ? (
            <>
              <div>
                <label
                  htmlFor="history-mobile"
                  className="block text-xs font-semibold mb-1.5"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  شماره موبایل
                </label>
                <input
                  id="history-mobile"
                  name="mobile"
                  type="tel"
                  inputMode="numeric"
                  className="input-field w-full text-sm"
                  style={{ direction: 'ltr' }}
                  value={mobile}
                  onChange={(event) => setMobile(event.target.value)}
                  placeholder="09xxxxxxxxx"
                  maxLength={11}
                  autoComplete="tel"
                  required
                />
              </div>

              {formError ? <ErrorBox>{formError}</ErrorBox> : null}

              <button
                type="submit"
                className="btn-primary w-full inline-flex items-center justify-center gap-2"
                disabled={busy}
                style={busy ? { opacity: 0.7, pointerEvents: 'none' } : undefined}
              >
                {busy ? <Loader2 size={17} className="animate-spin" /> : <ShieldCheck size={17} />}
                {busy ? 'در حال ارسال...' : 'دریافت کد تأیید'}
              </button>
            </>
          ) : (
            <>
              <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                کد تأیید را وارد کنید
              </h2>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                کد ۵ رقمی ارسال‌شده به شماره{' '}
                <span style={{ direction: 'ltr', fontFamily: 'monospace' }}>{maskedMobile}</span>{' '}
                را وارد کنید.
              </p>
              <input
                id="history-otp-code"
                name="otp_code"
                data-testid="my-orders-otp-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                className="input-field w-full text-sm"
                style={{ direction: 'ltr', textAlign: 'center', letterSpacing: '0.4em' }}
                value={code}
                onChange={(event) =>
                  setCode(normalizeDigits(event.target.value).replace(/\D/g, '').slice(0, 5))
                }
                maxLength={5}
                autoFocus
                aria-label="کد تأیید"
                required
              />

              {otpError ? <ErrorBox>{otpError}</ErrorBox> : null}
              {formError ? <ErrorBox>{formError}</ErrorBox> : null}

              <button
                type="submit"
                className="btn-primary w-full inline-flex items-center justify-center gap-2"
                disabled={busy || code.trim().length < 5}
                style={busy || code.trim().length < 5 ? { opacity: 0.7 } : undefined}
              >
                {busy ? <Loader2 size={17} className="animate-spin" /> : <ShieldCheck size={17} />}
                {busy ? 'در حال بررسی...' : 'تأیید و مشاهده سفارش‌ها'}
              </button>

              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={resendCode}
                  disabled={resendIn > 0 || busy}
                  className="text-xs font-medium disabled:cursor-not-allowed"
                  style={{ color: resendIn > 0 ? 'var(--text-muted)' : 'var(--accent)' }}
                >
                  {resendIn > 0 ? `ارسال مجدد کد تا ${resendIn} ثانیه` : 'ارسال مجدد کد'}
                </button>
                <button
                  type="button"
                  onClick={editMobile}
                  className="text-xs font-medium"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  ویرایش شماره موبایل
                </button>
              </div>
            </>
          )}

          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            این صفحه فقط برای همین تب است؛ با بستن تب، دسترسی شما پایان می‌یابد. شمارهٔ شما در آدرس
            صفحه یا حافظهٔ دائمی مرورگر ذخیره نمی‌شود.
          </p>
        </form>
      </div>
    );
  }

  // ── List ────────────────────────────────────────────────────────────
  const loading = listStatus === 'loading';
  const showEmpty = listStatus === 'ready' && items.length === 0;

  return (
    <div dir="rtl" className="max-w-3xl mx-auto animate-fade-in" data-testid="my-orders-list">
      <div
        className="rounded-2xl border p-5 sm:p-6 mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
        style={{
          background: 'var(--brand-header-gradient)',
          borderColor: 'var(--brand-header-border)',
          boxShadow: 'var(--brand-header-shadow)',
          color: 'var(--brand-header-fg)',
        }}
      >
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold mb-1">سفارش‌های من</h1>
          {maskedMobile ? (
            <p className="text-xs sm:text-sm" style={{ color: 'color-mix(in srgb, #fff 82%, transparent)' }}>
              سفارش‌های ثبت‌شده با شمارهٔ{' '}
              <span style={{ direction: 'ltr', fontFamily: 'monospace' }}>{maskedMobile}</span>
            </p>
          ) : null}
        </div>
        <button
          type="button"
          data-testid="sign-out"
          onClick={handleSignOut}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold shrink-0 self-start sm:self-auto"
          style={{
            border: '1px solid color-mix(in srgb, #fff 40%, transparent)',
            background: 'color-mix(in srgb, #fff 16%, transparent)',
            color: '#ffffff',
            cursor: 'pointer',
          }}
        >
          <LogOut size={15} />
          خروج
        </button>
      </div>

      {loading && items.length === 0 ? (
        <div className="text-center py-16" role="status" aria-busy="true">
          <Loader2
            size={30}
            className="animate-spin mx-auto mb-3"
            style={{ color: 'var(--brand-orange, #ff9a3d)' }}
          />
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            در حال بارگذاری سفارش‌ها…
          </p>
        </div>
      ) : null}

      {listStatus === 'error' ? (
        <div data-testid="my-orders-error" className="card p-5 rounded-2xl border space-y-3 text-center">
          <AlertTriangle size={26} className="mx-auto" style={{ color: '#f59e0b' }} />
          <ErrorBox>{listError}</ErrorBox>
          <button
            type="button"
            onClick={() => loadFirstPage(token)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white"
            style={{ background: 'var(--brand-orange, #ff9a3d)' }}
          >
            <RotateCcw size={15} />
            تلاش دوباره
          </button>
        </div>
      ) : null}

      {showEmpty ? (
        <div data-testid="my-orders-empty" className="card p-8 rounded-2xl border text-center space-y-3">
          <Inbox size={30} className="mx-auto" style={{ color: 'var(--brand-orange, #ff9a3d)' }} />
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            هنوز سفارشی ثبت نشده است
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            برای این شماره هیچ درخواست یا فاکتوری ثبت نشده است.
          </p>
        </div>
      ) : null}

      {items.length > 0 ? (
        <div className="space-y-3">
          {items.map((entry) => (
            <HistoryEntryCard key={`${entry?.kind}-${entry?.id}`} entry={entry} />
          ))}
        </div>
      ) : null}

      {listStatus === 'error' && listError && items.length > 0 ? (
        <div className="mt-3">
          <ErrorBox>{listError}</ErrorBox>
        </div>
      ) : null}

      {hasMore ? (
        <div className="mt-4 text-center">
          <button
            type="button"
            data-testid="load-more"
            onClick={loadMore}
            disabled={loading}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold border"
            style={{
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
              backgroundColor: 'var(--bg-card)',
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Clock size={15} />}
            نمایش سفارش‌های بیشتر
          </button>
        </div>
      ) : null}

      <div
        className="mt-6 flex items-start gap-2 p-3 rounded-xl border text-[11px] leading-relaxed"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}
      >
        <FileText size={15} className="shrink-0 mt-0.5 text-[var(--brand-orange)]" />
        <span>
          این صفحه فقط وضعیت ثبت‌شده روی سرور را نشان می‌دهد و به‌تنهایی امکان پرداخت ایجاد نمی‌کند.
          برای پرداخت فاکتور، لینک اختصاصی صادرشده توسط پشتیبانی را از طریق پیام‌رسان دریافت کنید.
        </span>
      </div>

      <div className="mt-3 flex items-center justify-center">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-xs font-medium"
          style={{ color: 'var(--text-secondary)' }}
        >
          <ArrowRight size={14} />
          بازگشت به کاتالوگ
        </Link>
      </div>
    </div>
  );
}
