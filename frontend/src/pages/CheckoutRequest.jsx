import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShoppingBag, Trash2, Plus, Minus, Loader2, CheckCircle2, ArrowRight, Send, ShieldCheck } from 'lucide-react';
import { getCatalog } from '../lib/api';
import { submitCommerceRequest, requestOtp } from '../lib/commerceApi';
import { readCart, updateQuantity, removeItem, subscribe, clearCart } from '../lib/cart';
import { formatPrice } from '../lib/utils';

/**
 * Public checkout — turns the browser cart into a persisted request.
 *
 * The cart holds only product ids + quantities: the browser is NOT an
 * authoritative price source. The payload sent to the server therefore carries
 * no prices at all, and the cart is cleared only AFTER the request succeeds.
 */

const MOBILE_RE = /^09\d{9}$/;
const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';

const MESSENGER_OPTIONS = [
  { value: 'telegram', label: 'تلگرام' },
  { value: 'bale', label: 'بله' },
];

const EMPTY_FORM = {
  customer_name: '',
  mobile: '',
  messenger: 'telegram',
  messenger_handle: '',
  address: '',
  note: '',
};

/** Normalise Persian/Arabic-Indic digits to ASCII so ۰۹۱۲… validates like 0912…. */
function normalizeDigits(value) {
  return String(value ?? '').replace(/[۰-۹٠-٩]/g, (ch) => {
    const fa = PERSIAN_DIGITS.indexOf(ch);
    if (fa > -1) return String(fa);
    const ar = ARABIC_DIGITS.indexOf(ch);
    if (ar > -1) return String(ar);
    return ch;
  });
}

/** Pull a human-readable message out of an Axios/FastAPI error. */
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
  return 'ثبت درخواست ناموفق بود. لطفاً دوباره تلاش کنید.';
}

export default function CheckoutRequest() {
  const [cartItems, setCartItems] = useState(() => readCart());
  const [catalog, setCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [receipt, setReceipt] = useState(null);

  // ── Cart OTP gate ───────────────────────────────────────────────────
  // `otp` is null until the one-time code has been requested; once set the
  // guest must enter the SMS code before the request is accepted.
  const [otp, setOtp] = useState(null);
  const [otpCode, setOtpCode] = useState('');
  const [otpError, setOtpError] = useState(null);
  const [otpSubmitting, setOtpSubmitting] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  // Keep the local list in sync with the shared cart store.
  useEffect(() => subscribe(() => setCartItems(readCart())), []);

  // Resolve display names from the public catalogue (never as price authority).
  useEffect(() => {
    let active = true;
    getCatalog()
      .then((res) => {
        if (active) setCatalog(Array.isArray(res?.data) ? res.data : []);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const byId = useMemo(() => {
    const map = new Map();
    for (const product of catalog) map.set(Number(product.id), product);
    return map;
  }, [catalog]);

  const lines = useMemo(
    () => cartItems.map((item) => ({ ...item, product: byId.get(Number(item.id)) || null })),
    [cartItems, byId]
  );

  // Indicative estimated total (qty × catalogue display price). Purely local —
  // never sent to the server, which prices the request after staff review.
  const estimate = useMemo(() => {
    let sum = 0;
    let unpricedCount = 0;
    for (const line of lines) {
      const unit = Number(line.product?.final_price || line.product?.suggested_price || 0);
      if (unit > 0) sum += unit * line.qty;
      else unpricedCount += 1;
    }
    return { sum, unpricedCount, lineCount: lines.length };
  }, [lines]);

  const setField = useCallback(
    (key) => (event) => {
      const { value } = event.target;
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const changeQty = useCallback((id, qty) => {
    setCartItems(updateQuantity(id, qty));
  }, []);

  const drop = useCallback((id) => {
    setCartItems(removeItem(id));
  }, []);

  /** The exact public request payload — no prices, no surplus keys. */
  const buildPayload = useCallback(() => {
    const customerName = form.customer_name.trim();
    const mobile = normalizeDigits(form.mobile).replace(/\s+/g, '');
    const items = cartItems.map((item) => ({ product_id: item.id, qty: item.qty }));
    const payload = { customer_name: customerName, mobile, messenger: form.messenger, items };
    const handle = form.messenger_handle.trim();
    const address = form.address.trim();
    const note = form.note.trim();
    if (handle) payload.messenger_handle = handle;
    if (address) payload.address = address;
    if (note) payload.note = note;
    return payload;
  }, [form, cartItems]);

  // Reset the OTP step whenever the mobile changes: a code is bound to the
  // number it was sent to, so a new number starts a fresh challenge.
  useEffect(() => {
    setOtp(null);
    setOtpCode('');
    setOtpError(null);
  }, [form.mobile]);

  // Resend countdown; only ticks while an OTP step is active and is cleaned up
  // on unmount (or when the challenge is replaced).
  useEffect(() => {
    if (!otp) return undefined;
    setResendIn(otp.resendAfter > 0 ? otp.resendAfter : 0);
    if (!otp.resendAfter) return undefined;
    const timer = setInterval(() => {
      setResendIn((seconds) => (seconds > 0 ? seconds - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [otp]);

  const startOtp = async (mobile) => {
    const res = await requestOtp({ mobile });
    const data = res?.data || {};
    const resendAfter = Number(data.resend_after) || 0;
    // Seed the countdown in the same commit that reveals the OTP step, so the
    // resend button is never briefly enabled before the interval kicks in.
    setResendIn(resendAfter);
    setOtp({
      challengeId: data.challenge_id,
      maskedMobile: data.masked_mobile || mobile,
      resendAfter,
    });
    setOtpCode('');
    setOtpError(null);
  };

  const confirmOtp = async () => {
    if (otpSubmitting || !otp) return;
    const code = otpCode.trim();
    if (!/^\d{5}$/.test(code)) {
      setOtpError('کد تأیید ۵ رقمی را وارد کنید.');
      return;
    }
    setOtpError(null);
    setOtpSubmitting(true);
    try {
      // Re-POST the same request payload PLUS the OTP proof. Still no prices.
      const payload = {
        ...buildPayload(),
        otp_challenge_id: otp.challengeId,
        otp_code: code,
      };
      const res = await submitCommerceRequest(payload);
      const data = res?.data || {};
      setReceipt({ receipt_id: data.receipt_id, state: data.state });
      clearCart();
    } catch (err) {
      if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
        setOtpError(extractError(err));
      }
    } finally {
      setOtpSubmitting(false);
    }
  };

  const resendOtp = async () => {
    if (!otp || resendIn > 0 || submitting) return;
    setOtpError(null);
    setSubmitting(true);
    try {
      await startOtp(normalizeDigits(form.mobile).replace(/\s+/g, ''));
    } catch (err) {
      setOtpError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const editMobile = () => {
    setOtp(null);
    setOtpCode('');
    setOtpError(null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    // Once the OTP step is open, a form submit (Enter / the primary button)
    // means "confirm the code", never a fresh request.
    if (otp) {
      await confirmOtp();
      return;
    }
    if (submitting) return;
    setError(null);

    const payload = buildPayload();
    if (!payload.customer_name) {
      setError('نام و نام خانوادگی را وارد کنید.');
      return;
    }
    if (!MOBILE_RE.test(payload.mobile)) {
      setError('شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.');
      return;
    }
    if (payload.items.length === 0) {
      setError('سبد خرید شما خالی است.');
      return;
    }

    // Validated: request the SMS one-time code instead of submitting. A 503 /
    // delivery error keeps the guest on the form with the Persian message.
    setSubmitting(true);
    try {
      await startOtp(payload.mobile);
    } catch (err) {
      if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
        setError(extractError(err));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ── Confirmation ────────────────────────────────────────────────────
  if (receipt) {
    return (
      <div className="max-w-xl mx-auto text-center py-12 sm:py-20 animate-fade-in">
        <div
          className="mx-auto mb-5 w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{ background: 'var(--accent-light)' }}
        >
          <CheckCircle2 size={32} style={{ color: 'var(--accent)' }} />
        </div>
        <h1 className="text-lg sm:text-xl font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
          درخواست شما ثبت شد
        </h1>
        <p className="text-sm mb-4" style={{ color: 'var(--text-secondary)' }}>
          درخواست شما برای بررسی کارشناسان ثبت شد. مبلغ نهایی و نحوه پرداخت پس از تأیید موجودی از
          طریق پیامرسان اعلام میشود.
        </p>
        <div
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border mb-6"
          style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
        >
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>کد پیگیری:</span>
          <span className="font-mono text-sm font-bold" style={{ color: 'var(--text-primary)', direction: 'ltr' }}>
            {receipt.receipt_id}
          </span>
        </div>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link to="/" className="btn-primary inline-flex items-center justify-center gap-2">
            <ArrowRight size={18} />
            بازگشت به کاتالوگ
          </Link>
        </div>
      </div>
    );
  }

  // ── Empty cart ──────────────────────────────────────────────────────
  if (cartItems.length === 0) {
    return (
      <div className="max-w-xl mx-auto text-center py-16 sm:py-24 animate-fade-in">
        <div
          className="mx-auto mb-5 w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{ background: 'var(--accent-light)' }}
        >
          <ShoppingBag size={32} style={{ color: 'var(--accent)', opacity: 0.85 }} />
        </div>
        <h1 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
          سبد خرید خالی است
        </h1>
        <p className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>
          برای ثبت درخواست، ابتدا از کاتالوگ محصول مورد نظرتان را به سبد اضافه کنید.
        </p>
        <Link to="/" className="btn-primary inline-flex items-center gap-2">
          <ArrowRight size={18} />
          بازگشت به کاتالوگ
        </Link>
      </div>
    );
  }

  const totalQty = cartItems.reduce((sum, item) => sum + item.qty, 0);

  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      {/* Page header on the shared brand band (navy→orange) — white foreground. */}
      <div
        className="rounded-2xl border p-5 sm:p-6 mb-6"
        data-testid="checkout-header-band"
        style={{
          background: 'var(--brand-header-gradient)',
          borderColor: 'var(--brand-header-border)',
          boxShadow: 'var(--brand-header-shadow)',
          color: 'var(--brand-header-fg)',
        }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium hover:opacity-80 transition-opacity"
            style={{ color: 'var(--brand-header-fg)' }}
          >
            <ArrowRight size={16} />
            بازگشت به کاتالوگ
          </Link>
        </div>

        <h1 className="text-xl sm:text-2xl font-bold mb-1" style={{ color: 'var(--brand-header-fg)' }}>
          ثبت درخواست سفارش
        </h1>
        <p className="text-xs sm:text-sm" style={{ color: 'color-mix(in srgb, #fff 82%, transparent)' }}>
          {totalQty} عدد کالا در سبد شما — اطلاعات تماس را وارد کنید تا کارشناسان ما سفارش را بررسی و
          مبلغ نهایی را اعلام کنند.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cart summary */}
        <section
          className="card p-5 sm:p-6 rounded-2xl border space-y-3 h-fit"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            اقلام سبد خرید
          </h2>
          {lines.map((line) => {
            const name = line.product?.name || `کد ${line.id}`;
            return (
              <div
                key={line.id}
                className="rounded-2xl border p-3 flex flex-col gap-2"
                style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: 'var(--text-primary)' }}>
                    {catalogLoading && !line.product ? 'در حال بارگذاری...' : name}
                  </span>
                  <button
                    type="button"
                    className="p-1.5 rounded-lg shrink-0"
                    style={{ color: '#ef4444' }}
                    aria-label={`حذف ${name} از سبد خرید`}
                    onClick={() => drop(line.id)}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                <div className="inline-flex items-center gap-1 rounded-xl border w-fit" style={{ borderColor: 'var(--border-color)' }}>
                  <button
                    type="button"
                    className="w-7 h-7 inline-flex items-center justify-center"
                    aria-label={`کاهش تعداد ${name}`}
                    onClick={() => changeQty(line.id, line.qty - 1)}
                  >
                    <Minus size={13} />
                  </button>
                  <span className="text-xs font-bold tabular-nums w-7 text-center" style={{ color: 'var(--text-primary)' }}>
                    {line.qty}
                  </span>
                  <button
                    type="button"
                    className="w-7 h-7 inline-flex items-center justify-center"
                    aria-label={`افزایش تعداد ${name}`}
                    onClick={() => changeQty(line.id, line.qty + 1)}
                  >
                    <Plus size={13} />
                  </button>
                </div>
              </div>
            );
          })}
          {lines.length > 0 ? (
            <div
              className="flex items-center justify-between gap-2 text-sm pt-3 border-t"
              style={{ borderColor: 'var(--border-color)' }}
            >
              <span style={{ color: 'var(--text-muted)' }}>تخمین قیمت</span>
              <span
                className="font-bold tabular-nums"
                style={{ color: 'var(--text-primary)' }}
                data-testid="checkout-estimated-total"
              >
                {estimate.unpricedCount === estimate.lineCount
                  ? 'قیمت تماس بگیرید'
                  : formatPrice(estimate.sum)}
              </span>
            </div>
          ) : null}
          {lines.length > 0 && estimate.unpricedCount > 0 && estimate.unpricedCount < estimate.lineCount ? (
            <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              قیمت {estimate.unpricedCount} قلم از اقلام شما پس از بررسی اعلام می‌شود.
            </p>
          ) : null}
          <p className="text-[11px] leading-relaxed pt-1" style={{ color: 'var(--text-muted)' }}>
            سبد خرید فقط شناسه و تعداد کالا را نگه میدارد؛ قیمتها پس از بررسی توسط کارشناسان محاسبه
            و اعلام میشوند.
          </p>
        </section>

        {/* Contact form */}
        <form
          onSubmit={handleSubmit}
          className="card p-5 sm:p-6 rounded-2xl border space-y-4"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
          noValidate
        >
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            اطلاعات تماس
          </h2>

          <div>
            <label
              htmlFor="checkout-name"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              نام و نام خانوادگی
            </label>
            <input
              id="checkout-name"
              name="customer_name"
              type="text"
              className="input-field w-full text-sm"
              value={form.customer_name}
              onChange={setField('customer_name')}
              maxLength={120}
              required
              autoComplete="name"
            />
          </div>

          <div>
            <label
              htmlFor="checkout-mobile"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              شماره موبایل
            </label>
            <input
              id="checkout-mobile"
              name="mobile"
              type="tel"
              inputMode="numeric"
              className="input-field w-full text-sm"
              style={{ direction: 'ltr' }}
              value={form.mobile}
              onChange={setField('mobile')}
              placeholder="09xxxxxxxxx"
              maxLength={11}
              required
              autoComplete="tel"
            />
          </div>

          <div>
            <label
              htmlFor="checkout-messenger"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              پیامرسان
            </label>
            <select
              id="checkout-messenger"
              name="messenger"
              className="select-field w-full text-sm"
              value={form.messenger}
              onChange={setField('messenger')}
              required
            >
              {MESSENGER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              htmlFor="checkout-handle"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              شناسه پیامرسان (اختیاری)
            </label>
            <input
              id="checkout-handle"
              name="messenger_handle"
              type="text"
              className="input-field w-full text-sm"
              style={{ direction: 'ltr' }}
              value={form.messenger_handle}
              onChange={setField('messenger_handle')}
              maxLength={100}
            />
          </div>

          <div>
            <label
              htmlFor="checkout-address"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              آدرس (اختیاری)
            </label>
            <input
              id="checkout-address"
              name="address"
              type="text"
              className="input-field w-full text-sm"
              value={form.address}
              onChange={setField('address')}
              maxLength={500}
            />
          </div>

          <div>
            <label
              htmlFor="checkout-note"
              className="block text-xs font-semibold mb-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              توضیحات (اختیاری)
            </label>
            <textarea
              id="checkout-note"
              name="note"
              rows={3}
              className="input-field w-full text-sm"
              value={form.note}
              onChange={setField('note')}
              maxLength={2000}
            />
          </div>

          {error ? (
            <div
              role="alert"
              className="p-3 rounded-xl text-xs leading-relaxed border"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                borderColor: 'rgba(239, 68, 68, 0.35)',
                color: '#ef4444',
              }}
            >
              {error}
            </div>
          ) : null}

          {otp ? (
            <div
              className="rounded-2xl border p-4 space-y-3"
              data-testid="checkout-otp-step"
              style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
            >
              <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                کد تأیید را وارد کنید
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                کد ۵ رقمی ارسال‌شده به شماره{' '}
                <span style={{ direction: 'ltr', fontFamily: 'monospace' }}>{otp.maskedMobile}</span>{' '}
                را وارد کنید.
              </p>
              <input
                id="checkout-otp-code"
                name="otp_code"
                data-testid="checkout-otp-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                className="input-field w-full text-sm"
                style={{ direction: 'ltr', textAlign: 'center', letterSpacing: '0.4em' }}
                value={otpCode}
                onChange={(event) =>
                  setOtpCode(normalizeDigits(event.target.value).replace(/\D/g, '').slice(0, 5))
                }
                maxLength={5}
                autoFocus
                aria-label="کد تأیید"
                required
              />
              {otpError ? (
                <div
                  role="alert"
                  className="p-3 rounded-xl text-xs leading-relaxed border"
                  style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.08)',
                    borderColor: 'rgba(239, 68, 68, 0.35)',
                    color: '#ef4444',
                  }}
                >
                  {otpError}
                </div>
              ) : null}
              <button
                type="button"
                data-testid="checkout-otp-confirm"
                className="btn-primary w-full inline-flex items-center justify-center gap-2"
                onClick={confirmOtp}
                disabled={otpSubmitting || otpCode.trim().length < 5}
                style={otpSubmitting || otpCode.trim().length < 5 ? { opacity: 0.7 } : undefined}
              >
                {otpSubmitting ? <Loader2 size={17} className="animate-spin" /> : <ShieldCheck size={17} />}
                {otpSubmitting ? 'در حال ثبت...' : 'تأیید و ثبت درخواست'}
              </button>
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  data-testid="checkout-otp-resend"
                  onClick={resendOtp}
                  disabled={resendIn > 0 || submitting}
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
            </div>
          ) : (
            <button
              type="submit"
              className="btn-primary w-full inline-flex items-center justify-center gap-2"
              disabled={submitting}
              style={submitting ? { opacity: 0.7, pointerEvents: 'none' } : undefined}
            >
              {submitting ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
              {submitting ? 'در حال ثبت...' : 'ثبت درخواست'}
            </button>
          )}

          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            با ثبت درخواست، هیچ مبلغی بهصورت خودکار پرداخت نمیشود. کارشناسان ما پس از بررسی موجودی،
            مبلغ نهایی را اعلام میکنند.
          </p>
        </form>
      </div>
    </div>
  );
}
