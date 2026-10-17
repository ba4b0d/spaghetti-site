import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  HelpCircle,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { formatPrice } from '../lib/constants';
import { getPublicInvoice } from '../lib/commerceApi';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';
import { clearPaymentReceipt, readPaymentReceipt } from '../lib/paymentReceipt';
import PaymentShell from '../components/PaymentShell';

/**
 * Payment result page (``/pay/result``).
 *
 * The backend BitPay callback always 303-redirects the browser here as
 * ``/pay/result?payment=success|failed|pending``, with NO bearer token. The
 * query string is a PRESENTATION HINT ONLY: the gateway callback query is
 * untrusted and the invoice is settled exclusively by a server-to-server
 * verification, so this page never asserts a payment succeeded from the hint —
 * ``success`` means "the gateway handed the customer back", not "the money is
 * confirmed".
 *
 * TRUTHFUL CONFIRMATION
 * To show a real confirmation (invoice number + amount) after an ACTUAL settled
 * payment, this page reads the private invoice behind the token the pay page
 * parked for this tab (see ``lib/paymentReceipt``). It shows the confirmed
 * details ONLY when the SERVER reports the invoice ``state === 'paid'`` — i.e.
 * after ``settle_verified_payment`` claimed the ``approved → paid`` transition.
 * With no parked receipt (a direct revisit, a lost mobile tab, a new tab) or
 * any non-paid / failed read, it falls back to the generic, fail-closed copy.
 *
 * PRIVACY
 * It never reads, stores, logs or echoes a bearer token from the URL, and it
 * carries the token only as the path segment of the SAME public invoice GET the
 * pay page makes — never as a query string, Referer or log line. The parked
 * token is dropped once the settled payment has been shown. A forged or leaked
 * result URL therefore still cannot learn or claim anything about an invoice.
 */

const HINTS = {
  success: {
    icon: CheckCircle2,
    color: 'var(--success, #22c55e)',
    title: 'درخواست پرداخت شما دریافت شد',
    body: 'نتیجه نهایی پرداخت پس از تأیید سرور مشخص می‌شود. اگر مبلغی کسر شده باشد، به‌صورت خودکار در فاکتور شما ثبت می‌گردد. تا زمان تأیید، تراکنش را تکمیل‌شده فرض نکنید.',
  },
  failed: {
    icon: XCircle,
    color: '#ef4444',
    title: 'پرداخت ناموفق بود یا لغو شد',
    body: 'مبلغی از حساب شما کسر نشده است. می‌توانید از لینک پرداخت فاکتور دوباره تلاش کنید یا موضوع را با پشتیبانی در میان بگذارید.',
  },
  pending: {
    icon: Clock,
    color: '#f59e0b',
    title: 'در حال بررسی نتیجه پرداخت',
    body: 'نتیجه پرداخت هنوز از سوی درگاه تأیید نشده است. وضعیت نهایی پس از تأیید سرور مشخص می‌شود؛ لطفاً تا آن زمان پرداخت را تکراری انجام ندهید.',
  },
};

const UNKNOWN_HINT = {
  icon: HelpCircle,
  color: 'var(--text-muted)',
  title: 'وضعیت پرداخت نامشخص است',
  body: 'نتیجه‌ای برای این صفحه ثبت نشده است. برای پیگیری با پشتیبانی در تماس باشید.',
};

export const RESULT_HINTS = HINTS;

/**
 * Confirmed, server-verified payment slip.
 *
 * Rendered ONLY from an invoice the server reported as ``paid``. It shows the
 * customer-visible invoice number and the settled amount, and nothing else —
 * no contact/PII, no token.
 */
function ConfirmedCard({ invoice }) {
  const items = Array.isArray(invoice.items) ? invoice.items : [];

  return (
    <div
      className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in shadow-md"
      style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
    >
      <div
        className="mx-auto mb-4 w-16 h-16 rounded-2xl flex items-center justify-center shadow-sm"
        style={{ background: 'rgba(34, 197, 94, 0.12)' }}
      >
        <CheckCircle2 size={32} style={{ color: 'var(--success, #16a34a)' }} />
      </div>

      <span
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold mb-3"
        style={{
          backgroundColor: 'rgba(34, 197, 94, 0.12)',
          color: 'var(--success, #16a34a)',
          border: '1px solid rgba(34, 197, 94, 0.3)',
        }}
      >
        <CheckCircle2 size={13} />
        پرداخت تأییدشده
      </span>

      <h1 className="text-lg sm:text-xl font-bold mb-2.5" style={{ color: 'var(--text-primary)' }}>
        پرداخت شما تأیید شد
      </h1>
      <p
        className="text-sm leading-relaxed mb-6 max-w-md mx-auto"
        style={{ color: 'var(--text-secondary)' }}
      >
        پرداخت این صورت‌حساب توسط درگاه تأیید و در سیستم اسپاگتی پرینت ثبت شد.
      </p>

      <dl
        className="rounded-xl border mb-6 text-right overflow-hidden"
        style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary, #eef1f9)' }}
      >
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <dt className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            شماره فاکتور
          </dt>
          <dd
            className="text-sm font-bold tabular-nums"
            data-testid="invoice-number"
            style={{ color: 'var(--text-primary)' }}
          >
            #{invoice.id}
          </dd>
        </div>
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <dt className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            مبلغ پرداخت‌شده
          </dt>
          <dd
            className="text-sm font-bold tabular-nums"
            data-testid="invoice-paid-amount"
            style={{ color: 'var(--brand-orange-deep, #e07b2c)' }}
          >
            {formatPrice(invoice.total_toman)}
          </dd>
        </div>
        {items.length > 0 ? (
          <div className="flex items-center justify-between px-4 py-3">
            <dt className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              تعداد اقلام
            </dt>
            <dd
              className="text-sm font-semibold tabular-nums"
              data-testid="invoice-item-count"
              style={{ color: 'var(--text-primary)' }}
            >
              {items.length}
            </dd>
          </div>
        ) : null}
      </dl>

      <div
        className="flex items-start gap-2.5 text-[11px] leading-relaxed text-right rounded-xl border p-3.5 mb-6"
        style={{
          borderColor: 'var(--border-color)',
          backgroundColor: 'var(--bg-secondary, #eef1f9)',
          color: 'var(--text-muted)',
        }}
        role="note"
      >
        <ShieldCheck size={15} className="shrink-0 mt-0.5 text-[var(--brand-orange)]" aria-hidden="true" />
        <span>این نتیجه مستقیماً از سرور اسپاگتی پرینت خوانده شده و تأیید قطعی پرداخت است.</span>
      </div>

      <Link
        to="/"
        className="inline-flex items-center justify-center gap-2 py-3 px-6 rounded-xl font-bold text-sm text-white shadow-md transition-all hover:brightness-105 active:scale-95"
        style={{
          background: 'linear-gradient(135deg, var(--brand-orange, #ff9a3d) 0%, var(--brand-orange-deep, #e07b2c) 100%)',
          boxShadow: '0 4px 14px rgba(224, 123, 44, 0.3)',
        }}
      >
        <ArrowRight size={16} />
        بازگشت به کاتالوگ
      </Link>
    </div>
  );
}

export default function PaymentResult() {
  useNoReferrerPolicy();
  const [params] = useSearchParams();

  // Treat the query as an untrusted display hint only; anything unexpected
  // falls back to a neutral, non-committal state. The raw value is never
  // echoed back into the DOM.
  const hint = useMemo(() => {
    const raw = (params.get('payment') || '').trim().toLowerCase();
    return HINTS[raw] || UNKNOWN_HINT;
  }, [params]);

  // The server-confirmed invoice for this tab's parked receipt, or null. Null
  // keeps the page on its generic, non-committal copy — never a payment claim.
  const [invoice, setInvoice] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // The result page holds no credential of its own: it can read the private
  // invoice only when the pay page parked the token for this tab during the
  // hand-off. With no receipt it makes NO call (nothing to authenticate with).
  // The token is used strictly as the path segment of the public invoice GET —
  // never a query, Referer or log.
  const verify = useCallback((signal) => {
    const receipt = readPaymentReceipt();
    if (!receipt) return undefined;
    return getPublicInvoice(receipt.token, signal ? { signal } : undefined)
      .then((res) => {
        if (!mountedRef.current) return;
        const data = res?.data || null;
        if (data && data.state === 'paid') {
          setInvoice(data);
          // Consumed: the payment is settled, so the raw bearer token is dropped
          // rather than left in per-tab storage.
          clearPaymentReceipt();
        } else {
          // The server does NOT confirm a settled payment — stay generic.
          setInvoice(null);
        }
      })
      .catch(() => {
        // Any failure (network, expired/revoked link, …) is fail-closed:
        // never claim payment.
        if (mountedRef.current) setInvoice(null);
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    verify(controller.signal);
    return () => controller.abort();
  }, [verify]);

  const confirmed = Boolean(invoice && invoice.state === 'paid');
  if (confirmed) {
    return (
      <PaymentShell>
        <ConfirmedCard invoice={invoice} />
      </PaymentShell>
    );
  }

  const Icon = hint.icon;

  return (
    <PaymentShell>
      <div
        className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in shadow-md"
        style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
      >
        <div
          className="mx-auto mb-4 w-16 h-16 rounded-2xl flex items-center justify-center shadow-sm"
          style={{ background: 'var(--accent-light, rgba(255, 154, 61, 0.12))' }}
        >
          <Icon size={32} style={{ color: hint.color }} />
        </div>

        <h1 className="text-lg sm:text-xl font-bold mb-2.5" style={{ color: 'var(--text-primary)' }}>
          {hint.title}
        </h1>
        <p className="text-sm leading-relaxed mb-6 max-w-md mx-auto" style={{ color: 'var(--text-secondary)' }}>
          {hint.body}
        </p>

        <div
          className="flex items-start gap-2.5 text-[11px] leading-relaxed text-right rounded-xl border p-3.5 mb-6"
          style={{
            borderColor: 'var(--border-color)',
            backgroundColor: 'var(--bg-secondary, #eef1f9)',
            color: 'var(--text-muted)',
          }}
          role="note"
        >
          <AlertTriangle size={15} className="shrink-0 mt-0.5 text-[var(--brand-orange)]" aria-hidden="true" />
          <span>
            وضعیت قطعی این تراکنش فقط توسط سرور اسپاگتی پرینت و پس از تأیید درگاه مشخص می‌شود؛ این صفحه به‌تنهایی
            اثبات‌کننده پرداخت نیست.
          </span>
        </div>

        <Link
          to="/"
          className="inline-flex items-center justify-center gap-2 py-3 px-6 rounded-xl font-bold text-sm text-white shadow-md transition-all hover:brightness-105 active:scale-95"
          style={{
            background: 'linear-gradient(135deg, var(--brand-orange, #ff9a3d) 0%, var(--brand-orange-deep, #e07b2c) 100%)',
            boxShadow: '0 4px 14px rgba(224, 123, 44, 0.3)',
          }}
        >
          <ArrowRight size={16} />
          بازگشت به کاتالوگ
        </Link>
      </div>
    </PaymentShell>
  );
}
