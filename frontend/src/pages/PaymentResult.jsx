import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock, HelpCircle, XCircle } from 'lucide-react';
import { useNoReferrerPolicy } from '../hooks/useNoReferrerPolicy';
import PaymentShell from '../components/PaymentShell';

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
