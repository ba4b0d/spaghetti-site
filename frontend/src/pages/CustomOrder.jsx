import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Image,
  MessageCircle,
  BadgeCheck,
  Wallet,
  PenTool,
  PackageCheck,
  Send,
  Phone,
} from 'lucide-react';
import { getContact } from '../lib/api';
import { useSEO, buildWebSiteJsonLd } from '../lib/seo';

const STEPS = [
  {
    n: 1,
    icon: Image,
    title: 'پیدا کردن عکس طرح مورد نظر',
    body: 'نزدیک‌ترین تصویر از طرحی که در ذهنتان دارید را پیدا کنید.',
  },
  {
    n: 2,
    icon: MessageCircle,
    title: 'ارسال پیام',
    body: 'برای استعلام قیمت، اطلاعات زیر را از طریق تلگرام، اینستاگرام و یا بله برای ما ارسال کنید:\n• توصیف طرح ذهنی\n• ارائه توضیحات (برای مثال اگر طرح دلخواهتان مربوط به شخصیت یک فیلم است، نام شخصیت و فیلم را برایمان بفرستید)\n• تصویر/ تصاویر مشابه\n• ابعاد حدودی',
  },
  {
    n: 3,
    icon: BadgeCheck,
    title: 'استعلام قیمت',
    body: 'پس از بررسی تا حداکثر ۴۸ ساعت، موارد زیر برایتان ارسال می‌شود:\n• رنگ‌بندی موجود\n• قیمت نهایی\n• زمان تقریبی طراحی\n• زمان تقریبی پرینت محصول پس از نهایی شدن طرح',
  },
  {
    n: 4,
    icon: Wallet,
    title: 'ثبت سفارش',
    body: 'پس از تایید جزئیات سفارش، راهنمای پرداخت برایتان ارسال خواهد شد. سفارش با تایید واریز، ثبت می‌شود.',
  },
  {
    n: 5,
    icon: PenTool,
    title: 'طراحی',
    body: 'برای نهایی کردن طرح با شما در تماس خواهیم بود. پس از قطعی شدن طرح، سفارش در صف پرینت قرار می‌گیرد.',
  },
  {
    n: 6,
    icon: PackageCheck,
    title: 'تحویل',
    body: 'پس از آماده شدن سفارش، برای هماهنگی تحویل سفارش به‌صورت حضوری و یا ارسال آن، با شما تماس می‌گیریم.',
  },
];

function formatPhoneHref(phone) {
  const clean = (phone || '').replace(/\s+/g, '');
  const rawDigits = clean.replace(/[^0-9]/g, '');
  if (!rawDigits) return 'tel:+989981923856';
  const intl = rawDigits.startsWith('98')
    ? `+${rawDigits}`
    : rawDigits.startsWith('0')
    ? `+98${rawDigits.slice(1)}`
    : `+98${rawDigits}`;
  return `tel:${clean.startsWith('+') ? clean : intl}`;
}

function formatTelegramHref(handle) {
  const clean = (handle || '').replace(/^@/, '').trim();
  return clean ? `https://t.me/${clean}` : 'https://t.me/spaghetti_print';
}

function formatBaleHref(handle) {
  const clean = (handle || '').replace(/^@/, '').trim();
  return clean ? `https://ble.ir/${clean}` : 'https://ble.ir/spaghetti_print';
}

export default function CustomOrder() {
  useSEO({
    title: 'سفارش قطعه و طرح دلخواه | پرینت سه‌بعدی سفارشی',
    description: 'راهنمای سفارش چاپ سه‌بعدی سفارشی، ارسال فایل STL یا عکس قطعه شکسته و استعلام قیمت پرینت سه‌بعدی در اسپاگتی پرینت',
    url: '/custom-order',
    jsonLd: buildWebSiteJsonLd(),
  });

  const [contact, setContact] = useState({
    telegram: 'spaghetti_print',
    bale: 'spaghetti_print',
    phone: '0998 192 3856',
  });

  useEffect(() => {
    getContact()
      .then((res) => {
        const api = res.data || {};
        const tg = (api.contact_telegram || '').replace(/^@/, '').trim();
        const bl = (api.contact_bale || '').replace(/^@/, '').trim();
        const ph = (api.contact_phone || '').trim();
        setContact((prev) => ({
          telegram: tg || prev.telegram,
          bale: bl || prev.bale,
          phone: ph || prev.phone,
        }));
      })
      .catch(() => {});
  }, []);

  const telegramHref = formatTelegramHref(contact.telegram);
  const baleHref = formatBaleHref(contact.bale);
  const phoneHref = formatPhoneHref(contact.phone);

  return (
    <div className="public-page" dir="rtl">
      <header className="public-page-hero public-page-hero--dark">
        <p className="public-page-kicker">راهنما</p>
        <h1 className="public-page-title public-page-title--white">نحوه سفارش</h1>
        <p className="public-page-lead">
          سفارش طرح دلخواه از طریق پیام‌رسان‌ها انجام می‌شود.
        </p>
      </header>

      <ol className="order-steps">
        {STEPS.map((s) => {
          const Icon = s.icon;
          return (
            <li key={s.n} className="order-step">
              <div className="order-step-badge" aria-hidden="true">
                <span className="order-step-num">{s.n}</span>
                <Icon size={18} className="order-step-icon" />
              </div>
              <div className="order-step-body">
                <h2 className="order-step-title">{s.title}</h2>
                <p className="order-step-text" style={{ whiteSpace: 'pre-line' }}>{s.body}</p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="public-page-actions">
        <a
          href={telegramHref}
          target="_blank"
          rel="noopener noreferrer"
          className="public-btn public-btn-telegram"
        >
          <Send size={18} />
          <span>ارسال پیام در تلگرام</span>
        </a>

        <a
          href={baleHref}
          target="_blank"
          rel="noopener noreferrer"
          className="public-btn public-btn-bale"
        >
          <MessageCircle size={18} />
          <span>ارسال پیام در بله</span>
        </a>

        <a
          href={phoneHref}
          className="public-btn public-btn-phone"
        >
          <Phone size={18} />
          <span>تماس تلفنی</span>
        </a>
      </div>

      <div className="text-center mt-6">
        <Link
          to="/contact"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-orange-400 transition-colors"
        >
          مشاهده سایر اطلاعات در صفحه تماس با ما ←
        </Link>
      </div>
    </div>
  );
}
