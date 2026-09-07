import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ShoppingBag, Box, Phone, RotateCcw, AlertTriangle, Sparkles } from 'lucide-react';
import { useSEO } from '../lib/seo';

const SPAGHETTI_TIPS = [
  'نکته پرینت: به نظر میرسه چسبندگی لایه اول (First Layer Adhesion) از دست رفته و قطعه ول کرده!',
  'نکته پرینت: شاید کالیبراسیون و تراز صفحه (Bed Leveling) به هم ریخته!',
  'نکته پرینت: دمای هیت بد رو ۵ درجه ببر بالا و قبل چاپ یکم چسب ماتیکی یا اسپری بزن!',
  'نکته پرینت: Z-offset رو چک کن؛ نازل داشت توی هوا برای خودش اسپاگتی میپخت!',
  'نکته پرینت: این قطعه رفت جزو ضایعات، ولی توی کاتالوگ کلی قطعه سالم و آماده داریم!',
  'نکته پرینت: سنسور هوش مصنوعی اسپاگتی فعال شد و چاپ متوقف شد تا فیلامنتت نسوزه!',
];

export default function NotFound() {
  const navigate = useNavigate();
  const [clickCount, setClickCount] = useState(0);

  useSEO({
    title: 'صفحه پیدا نشد (خطای ۴۰۴)',
    description: 'اوپس! پرینت این صفحه اسپاگتی شد! قطعه مورد نظر روی هیت بد پیدا نشد.',
    url: '/404',
  });

  const tipIndex = clickCount % SPAGHETTI_TIPS.length;
  const currentTip = SPAGHETTI_TIPS[tipIndex];

  return (
    <div className="p404-page" dir="rtl">
      <div className="p404-container">

        {/* TOP BRAND PILL */}
        <Link to="/" className="p404-brand-pill">
          <img src="/icon-192.png" alt="Spaghetti Print" className="w-5 h-5 rounded-full" />
          <span className="font-bold text-white">اسپاگتی پرینت</span>
          <span className="text-xs text-orange-400 font-mono" dir="ltr">ERR_404</span>
        </Link>

        {/* MAIN VISUAL CARD */}
        <div className="p404-card">

          {/* 3D PRINTER SPAGHETTI FAILURE SVG */}
          <div className="p404-svg-wrap">
            <svg
              viewBox="0 0 460 210"
              className="w-full h-auto"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              aria-label="تصویر پرینتر سه بعدی با خطای اسپاگتی شدن فیلامنت"
            >
              <defs>
                <linearGradient id="p404-bed-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1e2538" />
                  <stop offset="100%" stopColor="#111624" />
                </linearGradient>
                <linearGradient id="p404-noodle-grad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#ff9a3d" />
                  <stop offset="50%" stopColor="#f59e0b" />
                  <stop offset="100%" stopColor="#ffc66e" />
                </linearGradient>
                <linearGradient id="p404-text-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#334155" />
                  <stop offset="100%" stopColor="#1e293b" />
                </linearGradient>
              </defs>

              {/* BACKGROUND 404 DIGITS */}
              <g opacity="0.35">
                <text x="60" y="145" fontSize="110" fontWeight="900" fontFamily="sans-serif" fill="url(#p404-text-grad)" stroke="#475569" strokeWidth="2" textAnchor="middle">۴</text>
                <text x="400" y="145" fontSize="110" fontWeight="900" fontFamily="sans-serif" fill="url(#p404-text-grad)" stroke="#475569" strokeWidth="2" textAnchor="middle">۴</text>
              </g>

              {/* HEATED PRINT BED (PEI SHEET) */}
              <g>
                <rect x="50" y="170" width="360" height="26" rx="8" fill="url(#p404-bed-grad)" stroke="#2a354f" strokeWidth="1.5" />
                {/* Bed grid texture */}
                <line x1="100" y1="170" x2="100" y2="196" stroke="#2a354f" strokeWidth="1" strokeDasharray="3 3" />
                <line x1="160" y1="170" x2="160" y2="196" stroke="#2a354f" strokeWidth="1" strokeDasharray="3 3" />
                <line x1="230" y1="170" x2="230" y2="196" stroke="#ff9a3d" strokeWidth="1.5" opacity="0.5" />
                <line x1="300" y1="170" x2="300" y2="196" stroke="#2a354f" strokeWidth="1" strokeDasharray="3 3" />
                <line x1="360" y1="170" x2="360" y2="196" stroke="#2a354f" strokeWidth="1" strokeDasharray="3 3" />
                {/* Heated bed clip */}
                <rect x="65" y="167" width="18" height="6" rx="2" fill="#64748b" />
                <rect x="377" y="167" width="18" height="6" rx="2" fill="#64748b" />
              </g>

              {/* TILTED 3D BENCHY (FAILED PRINT MASCOT) */}
              <g className="p404-benchy">
                {/* Benchy Hull */}
                <path d="M190 170 C190 156 205 146 230 146 C255 146 270 156 270 170 Z" fill="#3b82f6" stroke="#1d4ed8" strokeWidth="2" />
                {/* Cabin */}
                <rect x="210" y="124" width="38" height="24" rx="4" fill="#60a5fa" stroke="#1d4ed8" strokeWidth="1.5" />
                {/* Window */}
                <circle cx="222" cy="134" r="4" fill="#1e293b" />
                <circle cx="236" cy="134" r="4" fill="#1e293b" />
                {/* Chimney / Smoke stack */}
                <rect x="238" y="112" width="8" height="13" rx="2" fill="#93c5fd" stroke="#1d4ed8" strokeWidth="1.5" />
                {/* Cute dizzy face on hull */}
                <text x="218" y="163" fontSize="9" fontWeight="900" fill="#ffffff" opacity="0.9">X _ X</text>
              </g>

              {/* X-AXIS GANTRY RAIL */}
              <rect x="40" y="24" width="380" height="8" rx="4" fill="#1e293b" stroke="#334155" strokeWidth="1" />
              <line x1="45" y1="28" x2="415" y2="28" stroke="#475569" strokeWidth="1.5" />

              {/* EXTRUDER CARRIAGE */}
              <g>
                <rect x="200" y="14" width="60" height="34" rx="6" fill="#131b2e" stroke="#ff9a3d" strokeWidth="1.5" />
                {/* Cooling fan circle */}
                <circle cx="230" cy="30" r="11" fill="#0b101d" stroke="#38bdf8" strokeWidth="1.5" />
                <circle cx="230" cy="30" r="4" fill="#38bdf8" />
                {/* Heatsink block */}
                <rect x="222" y="48" width="16" height="12" rx="2" fill="#cbd5e1" stroke="#64748b" strokeWidth="1" />
                {/* Brass Nozzle */}
                <polygon points="224,60 236,60 232,70 228,70" fill="#f59e0b" stroke="#b45309" strokeWidth="1" />
                {/* Hot glowing tip */}
                <circle cx="230" cy="71" r="2.5" fill="#ef4444">
                  <animate attributeName="opacity" values="0.7;1;0.7" dur="1s" repeatCount="indefinite" />
                </circle>
              </g>

              {/* SPAGHETTI FILAMENT STRANDS (CHAOTIC CURLY PATHS) */}
              <g>
                {/* Stream 1 - from nozzle curling down right */}
                <path
                  d="M230 72 Q245 85 220 100 T260 120 T210 140 T275 160 T220 174"
                  fill="none"
                  stroke="url(#p404-noodle-grad)"
                  strokeWidth="3.2"
                  strokeLinecap="round"
                  strokeDasharray="14 6"
                  className="p404-noodle-flow"
                />

                {/* Stream 2 - loop-de-loop left */}
                <path
                  d="M230 72 C210 85 185 95 200 115 C215 135 170 145 190 162 C205 175 235 172 250 176"
                  fill="none"
                  stroke="#ff9a3d"
                  strokeWidth="2.8"
                  strokeLinecap="round"
                  strokeDasharray="10 4"
                  className="p404-noodle-flow"
                />

                {/* Stream 3 - wild tangle loop */}
                <path
                  d="M230 72 Q215 90 240 105 Q265 120 235 135 Q205 150 255 168 Q290 178 310 174"
                  fill="none"
                  stroke="#fbbf24"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />

                {/* Stream 4 - spaghetti pooling over the bed */}
                <path
                  d="M175 173 C190 165 210 178 230 168 C250 160 270 175 295 170 C320 165 335 174 350 174"
                  fill="none"
                  stroke="#f97316"
                  strokeWidth="3"
                  strokeLinecap="round"
                />

                {/* Stream 5 - wrapping around the Benchy */}
                <path
                  d="M205 145 C220 138 235 152 250 142 C260 135 245 120 232 125 C215 130 200 148 215 166"
                  fill="none"
                  stroke="#ffc66e"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                />

                {/* Extra dynamic noodles added when user clicks easter egg button */}
                {clickCount > 0 && (
                  <path
                    d="M230 72 C255 90 280 110 260 135 C240 160 280 170 300 174"
                    fill="none"
                    stroke="#ef4444"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeDasharray="8 4"
                    className="p404-noodle-flow"
                  />
                )}
                {clickCount > 1 && (
                  <path
                    d="M230 72 C190 80 170 110 185 130 C200 150 160 165 170 174"
                    fill="none"
                    stroke="#fb923c"
                    strokeWidth="3.2"
                    strokeLinecap="round"
                  />
                )}
                {clickCount > 2 && (
                  <path
                    d="M230 72 Q270 100 240 125 Q210 150 250 174"
                    fill="none"
                    stroke="#fde047"
                    strokeWidth="2.8"
                    strokeLinecap="round"
                  />
                )}
              </g>
            </svg>
          </div>

          {/* HEADLINE & EXPLANATION */}
          <h1 className="p404-title">
            اوپس! پرینت این صفحه اسپاگتی شد! 🍝
          </h1>
          <p className="p404-desc">
            قطعه های که دنبالش بودید روی هیت بد پیدا نشد؛ ظاهراً چسبندگی لایه اول از دست رفته و کل پرینتر پر از رشته های سرگردان فیلامنت شده!
          </p>

          {/* 3D PRINTER STATUS CONSOLE */}
          <div className="p404-terminal">
            <div className="p404-terminal-header">
              <span className="flex items-center gap-2">
                <span className="p404-terminal-led"></span>
                <span>PRINT_HALTED: SPAGHETTI_DETECTED</span>
              </span>
              <span className="text-gray-400 font-mono" dir="ltr">CODE 404</span>
            </div>

            <div className="p404-grid-stats">
              <div className="p404-stat-box">
                <span className="p404-stat-label">دمای نازل</span>
                <span className="p404-stat-val text-orange-400">۲۱۵°C</span>
              </div>
              <div className="p404-stat-box">
                <span className="p404-stat-label">دمای هیت بد</span>
                <span className="p404-stat-val text-blue-400">۶۰°C</span>
              </div>
              <div className="p404-stat-box">
                <span className="p404-stat-label">فیلامنت مصرفی</span>
                <span className="p404-stat-val text-amber-400">۴۰۴ متر</span>
              </div>
              <div className="p404-stat-box">
                <span className="p404-stat-label">وضعیت لایه ها</span>
                <span className="p404-stat-val text-red-400">ناموفق ❌</span>
              </div>
            </div>
          </div>

          {/* DYNAMIC SPAGHETTI TIP BOX */}
          <div className="p404-tip">
            💡 {currentTip}
          </div>

          {/* EASTER EGG BUTTON */}
          <button
            type="button"
            className="p404-easter-btn"
            onClick={() => setClickCount((prev) => prev + 1)}
            title="اکسترود فیلامنت بیشتر روی صفحه"
          >
            <Sparkles size={16} />
            <span>اکسترود یکم اسپاگتی بیشتر!</span>
            {clickCount > 0 && (
              <span className="bg-orange-500/20 text-orange-300 text-xs px-2 py-0.5 rounded-full font-mono">
                +{clickCount}
              </span>
            )}
          </button>

          {/* MAIN ACTION BUTTONS */}
          <div className="p404-actions">
            <Link to="/" className="p404-btn-primary">
              <ShoppingBag size={18} />
              <span>مشاهده کاتالوگ محصولات</span>
            </Link>

            <Link to="/custom-order" className="p404-btn-secondary">
              <Box size={18} />
              <span>سفارش فایل اختصاصی</span>
            </Link>

            <button
              type="button"
              onClick={() => navigate(-1)}
              className="p404-btn-secondary"
              title="بازگشت به صفحه قبلی"
            >
              <RotateCcw size={17} />
              <span>صفحه قبل</span>
            </button>
          </div>

        </div>

        {/* BOTTOM HELPFUL LINKS */}
        <div className="p404-footer-links">
          <Link to="/contact" className="p404-footer-link">ارتباط و پشتیبانی</Link>
          <span>·</span>
          <Link to="/card" className="p404-footer-link">کارت ویزیت دیجیتال</Link>
          <span>·</span>
          <Link to="/how-to-order" className="p404-footer-link">راهنمای سفارش</Link>
        </div>

      </div>
    </div>
  );
}
