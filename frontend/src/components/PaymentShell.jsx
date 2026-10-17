import { Link } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Lock } from 'lucide-react';
import BrandLogo from './BrandLogo';

/**
 * Branded shell for checkout and payment pages (/pay/:token, /pay/result).
 *
 * Provides the official Spaghetti Prints header and footer while keeping the
 * page focused and distraction-free (no mega-menu or cart collisions).
 */
export default function PaymentShell({ children }) {
  return (
    <div
      className="catalog-shell min-h-screen flex flex-col relative"
      dir="rtl"
      style={{ backgroundColor: 'transparent', color: 'var(--text-primary)' }}
    >
      <div className="catalog-ambient" aria-hidden="true" />

      {/* Top Header Bar with Brand Identity */}
      <header className="catalog-topbar" style={{ zIndex: 10 }}>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-2.5 flex items-center justify-between">
          <Link to="/" className="catalog-brand-link flex items-center gap-2.5 sm:gap-3.5 min-w-0">
            <BrandLogo height={64} className="catalog-logo-img shrink-0">
              <div className="catalog-logo-mark shrink-0" aria-hidden="true">
                S
              </div>
            </BrandLogo>
            <div className="min-w-0 catalog-brand-text">
              <span className="catalog-brand-title block truncate">اسپاگتی پرینت</span>
              <span className="catalog-brand-sub block truncate">صورت‌حساب و پرداخت آنلاین</span>
            </div>
          </Link>

          <Link
            to="/"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-white/95 hover:text-white transition-all hover:bg-white/10"
            style={{
              border: '1px solid color-mix(in srgb, #fff 25%, transparent)',
              background: 'color-mix(in srgb, #fff 10%, transparent)',
            }}
          >
            <ArrowRight size={14} />
            <span>بازگشت به کاتالوگ</span>
          </Link>
        </div>
      </header>

      {/* Main Payment Slip Content */}
      <main className="relative flex-1 max-w-2xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {children}
      </main>

      {/* Trust & Security Footer */}
      <footer
        className="relative border-t py-6 catalog-footer mt-auto"
        style={{ borderColor: 'var(--border-color)' }}
      >
        <div className="max-w-4xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-5 text-xs">
          <div className="text-center sm:text-right space-y-1">
            <div className="font-medium text-white/90 flex items-center justify-center sm:justify-start gap-2">
              <span>© Spaghettiprints · اسپاگتی پرینت</span>
              <span className="opacity-40">·</span>
              <span className="inline-flex items-center gap-1 text-white/80">
                <Lock size={12} className="text-[var(--brand-orange)]" />
                پرداخت امن شاپرک
              </span>
            </div>
            <p className="text-white/60 text-[11px]">
              تأیید آنی تراکنش تحت نظارت شبکه پرداخت الکترونیک کشور
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            <nav className="flex flex-wrap items-center justify-center gap-3 text-white/80" aria-label="راهنما">
              <Link to="/how-to-order" className="catalog-footer-link">
                راهنمای سفارش
              </Link>
              <Link to="/contact" className="catalog-footer-link">
                تماس با ما
              </Link>
              <Link to="/terms" className="catalog-footer-link">
                قوانین
              </Link>
            </nav>

            {/* Enamad Trust Badge */}
            <div className="shrink-0 flex items-center justify-center p-1.5 bg-white/95 rounded-xl border border-white/20 shadow-sm hover:shadow-md transition-all">
              <a
                referrerPolicy="origin"
                target="_blank"
                rel="noreferrer"
                href="https://trustseal.enamad.ir/?id=8105853&Code=IdFwUsVT9E4CUh6JfYYzMmF1pN7Sf18z"
                className="block"
                title="نماد اعتماد الکترونیکی"
              >
                <img
                  referrerPolicy="origin"
                  src="https://trustseal.enamad.ir/logo.aspx?id=8105853&Code=IdFwUsVT9E4CUh6JfYYzMmF1pN7Sf18z"
                  alt="نماد اعتماد الکترونیکی"
                  style={{ cursor: 'pointer', width: '56px', height: '56px', objectFit: 'contain' }}
                />
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
