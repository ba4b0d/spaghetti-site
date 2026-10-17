import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Loader2, ShieldCheck } from 'lucide-react';
import { validateGatewayUrl } from '../lib/gatewayValidation';
import {
  clearGatewayHandoff,
  navigateWithOriginReferrer,
  readGatewayHandoff,
} from '../lib/paymentHandoff';
import { useOriginReferrerPolicy } from '../hooks/useOriginReferrerPolicy';
import PaymentShell from '../components/PaymentShell';

/**
 * Token-free same-origin gateway hand-off page (``/pay/redirect``).
 *
 * The private ``/pay/<token>`` document is served ``Referrer-Policy:
 * no-referrer`` (the path segment is a bearer credential), so navigating to the
 * BitPay portal straight from it sends NO ``Referer`` and BitPay rejects the
 * hand-off with «آدرس ارجاعی نامعتبر» (invalid referer address).
 *
 * This page is the fix: it carries no token, is served with an origin-only
 * referrer policy, and on mount reads the parked *validated* portal URL from
 * sessionStorage, re-validates it against the provider allowlist, clears it,
 * and navigates on with ``Referer: https://spaghettiprints.ir/``.
 *
 * SAFETY
 *  - The parked URL is re-validated here (never an open redirect) and the
 *    provider name must match the URL, so a tampered entry cannot be followed.
 *  - The URL is never rendered into the DOM — only a neutral status.
 *  - The hand-off is cleared even when it is refused, so a refresh cannot
 *    replay it.
 */
export default function PaymentHandoff({ navigate = navigateWithOriginReferrer }) {
  useOriginReferrerPolicy();

  const [state, setState] = useState('redirecting'); // redirecting | invalid
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => {
    // Read-then-clear: the entry is consumed exactly once, whatever happens.
    const handoff = readGatewayHandoff();
    clearGatewayHandoff();

    const target = handoff ? validateGatewayUrl(handoff.url, handoff.provider) : null;
    if (!target) {
      setState('invalid');
      return;
    }
    navigateRef.current(target);
  }, []);

  if (state === 'invalid') {
    return (
      <PaymentShell>
        <div
          className="card p-6 sm:p-8 rounded-2xl border text-center animate-fade-in shadow-sm"
          style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
        >
          <div
            className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
            style={{ background: 'var(--accent-light, rgba(255, 154, 61, 0.12))' }}
          >
            <AlertTriangle size={28} style={{ color: '#ef4444' }} />
          </div>
          <h1 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            انتقال به درگاه انجام نشد
          </h1>
          <div
            role="alert"
            className="text-sm leading-relaxed space-y-3"
            style={{ color: 'var(--text-secondary)' }}
          >
            <p>
              به دلایل امنیتی امکان انتقال به درگاه پرداخت فراهم نشد. لطفاً از لینک پرداخت فاکتور دوباره
              تلاش کنید یا با پشتیبانی در تماس باشید.
            </p>
          </div>
          <div className="pt-4">
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white"
              style={{ background: 'var(--brand-orange, #ff9a3d)' }}
            >
              <ArrowRight size={14} />
              بازگشت به سایت
            </Link>
          </div>
        </div>
      </PaymentShell>
    );
  }

  return (
    <PaymentShell>
      <div
        className="card p-8 rounded-2xl border text-center shadow-sm"
        style={{ backgroundColor: 'var(--bg-card, #ffffff)', borderColor: 'var(--border-color)' }}
      >
        <Loader2
          size={32}
          className="animate-spin mx-auto mb-3"
          style={{ color: 'var(--brand-orange, #ff9a3d)' }}
        />
        <p role="status" className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
          در حال انتقال به درگاه پرداخت…
        </p>
        <p
          className="mt-4 text-[11px] leading-relaxed flex items-center justify-center gap-1.5"
          style={{ color: 'var(--text-muted)' }}
        >
          <ShieldCheck size={13} className="text-[var(--brand-orange)]" />
          انتقال امن از طریق درگاه رسمی شاپرک
        </p>
      </div>
    </PaymentShell>
  );
}
