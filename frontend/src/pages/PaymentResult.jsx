import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock, HelpCircle, XCircle } from 'lucide-react';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';

/**
 * Generic, token-free payment result page (Task 3, frontend only).
 *
 * The backend DigiPay callback always 303-redirects the browser here as
 * ``/pay/result?payment=success|failed|pending``. Crucially, the query string
 * is a PRESENTATION HINT ONLY: the gateway POST is untrusted and the invoice is
 * settled exclusively by a server-to-server verification. This page therefore
 * never asserts that a payment succeeded — ``success`` means "the gateway
 * handed the customer back", not "the money is confirmed".
 *
 * It also never reads, stores, logs or echoes a bearer token, so a leaked or
 * forged result URL cannot be used to learn or claim anything about an invoice.
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

  const Icon = hint.icon;

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-10"
      dir="rtl"
      style={{ backgroundColor: 'var(--bg-primary, #0f172a)', color: 'var(--text-primary)' }}
    >
      <main className="w-full max-w-xl">
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

        <div
          className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          <div
            className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
            style={{ background: 'var(--accent-light, rgba(99,102,241,0.15))' }}
          >
            <Icon size={26} style={{ color: hint.color }} />
          </div>

          <h1 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            {hint.title}
          </h1>
          <p className="text-sm leading-relaxed mb-6" style={{ color: 'var(--text-secondary)' }}>
            {hint.body}
          </p>

          <div
            className="flex items-start gap-2 text-[11px] leading-relaxed text-right rounded-xl border p-3 mb-6"
            style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)', color: 'var(--text-muted)' }}
            role="note"
          >
            <AlertTriangle size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
            <span>
              وضعیت قطعی این تراکنش فقط توسط سرور اسپاگتی پرینت و پس از تأیید درگاه مشخص می‌شود؛ این صفحه به‌تنهایی
              اثبات‌کننده پرداخت نیست.
            </span>
          </div>

          <Link to="/" className="btn-primary inline-flex items-center gap-2">
            <ArrowRight size={16} />
            بازگشت به کاتالوگ
          </Link>
        </div>
      </main>
    </div>
  );
}
