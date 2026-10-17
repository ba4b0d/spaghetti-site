import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Search,
  Hash,
  MessageCircle,
  Palette,
  BadgeCheck,
  PackageCheck,
  ShoppingBag,
  FileText,
  Smartphone,
  CreditCard,
  Send,
  Globe,
  Columns,
} from 'lucide-react';
import { useSEO, buildWebSiteJsonLd } from '../lib/seo';
import { getContact } from '../lib/api';

const SITE_STEPS = [
  {
    n: 1,
    icon: ShoppingBag,
    title: 'انتخاب محصول و افزودن به سبد',
    body: 'محصولات دلخواه را در کاتالوگ بررسی کرده و با زدن دکمه «افزودن به سبد»، تعداد مورد نظر را مشخص کنید.',
  },
  {
    n: 2,
    icon: FileText,
    title: 'تکمیل مشخصات و انتخاب پیام‌رسان',
    body: 'در سبد خرید، اطلاعات ارسال، آدرس و پیام‌رسان دلخواه خود (تلگرام یا بله) را جهت هماهنگی ثبت کنید.',
  },
  {
    n: 3,
    icon: Smartphone,
    title: 'تأیید سریع با پیامک (SMS)',
    body: 'کد یک‌بارمصرف ارسالی به شماره موبایل را وارد کنید تا درخواست شما بدون نیاز به کلمه عبور ثبت شود.',
  },
  {
    n: 4,
    icon: MessageCircle,
    title: 'بررسی پشتیبانی و هماهنگی مشخصات',
    body: 'پشتیبانی اسپاگتی پرینت درخواست را بررسی کرده و برای تأیید رنگ‌بندی و زمان تحویل در پیام‌رسان با شما هماهنگ می‌کند.',
  },
  {
    n: 5,
    icon: CreditCard,
    title: 'پرداخت امن آنلاین',
    body: 'پس از نهایی‌شدن مشخصات، لینک پرداخت اختصاصی (درگاه بانکی / دیجی‌پی) برایتان ارسال شده و سفارش تسویه می‌گردد.',
  },
  {
    n: 6,
    icon: PackageCheck,
    title: 'تولید باکیفیت و ارسال',
    body: 'سفارش شما با تجهیزات دقیق چاپ سه‌بعدی تولید شده و با بسته‌بندی ایمن از طریق پست، تیپاکس یا پیک ارسال می‌شود.',
  },
];

const MESSENGER_STEPS = [
  {
    n: 1,
    icon: Search,
    title: 'انتخاب محصول',
    body: 'محصول مورد نظر را در کاتالوگ پیشنهادی پیدا کنید.',
  },
  {
    n: 2,
    icon: Hash,
    title: 'کد محصول',
    body: 'کد محصول را یادداشت نمایید.',
  },
  {
    n: 3,
    icon: MessageCircle,
    title: 'ارسال پیام',
    body: 'برای انتخاب رنگ و سفارش هر محصول، کد آن را از طریق تلگرام، اینستاگرام و یا بله برای ما ارسال کنید.',
  },
  {
    n: 4,
    icon: Palette,
    title: 'انتخاب رنگ',
    body: 'رنگ‌بندی موجود و زمان تقریبی تحویل سفارش برایتان ارسال خواهد شد.',
  },
  {
    n: 5,
    icon: BadgeCheck,
    title: 'ثبت سفارش',
    body: 'پس از تایید رنگ‌، راهنمای پرداخت برایتان ارسال خواهد شد. سفارش با تایید واریز، ثبت می‌شود.',
  },
  {
    n: 6,
    icon: PackageCheck,
    title: 'تحویل',
    body: 'پس از آماده شدن سفارش، برای هماهنگی تحویل سفارش به‌صورت حضوری و یا ارسال آن، با شما تماس می‌گیریم.',
  },
];

function formatTelegramHref(handle) {
  const clean = (handle || '').replace(/^@/, '').trim();
  return clean ? `https://t.me/${clean}` : 'https://t.me/spaghetti_print';
}

function formatBaleHref(handle) {
  const clean = (handle || '').replace(/^@/, '').trim();
  return clean ? `https://ble.ir/${clean}` : 'https://ble.ir/spaghetti_print';
}

function StepsList({ steps, variant = 'primary' }) {
  return (
    <ol className="order-steps">
      {steps.map((s) => {
        const Icon = s.icon;
        return (
          <li key={s.n} className="order-step">
            <div
              className={`order-step-badge ${variant === 'messenger' ? 'order-step-badge--messenger' : ''}`}
              aria-hidden="true"
            >
              <span className="order-step-num">{s.n}</span>
              <Icon size={18} className="order-step-icon" />
            </div>
            <div className="order-step-body">
              <h2 className="order-step-title">{s.title}</h2>
              <p className="order-step-text">{s.body}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function HowToOrder() {
  useSEO({
    title: 'راهنمای ثبت سفارش',
    description: 'راهنمای گام‌به‌گام ثبت سفارش از سایت اسپاگتی پرینت و سفارش از طریق تلگرام و بله',
    url: '/how-to-order',
    jsonLd: buildWebSiteJsonLd(),
  });

  const [activeTab, setActiveTab] = useState('site'); // 'site' | 'messenger' | 'columns'
  const [contact, setContact] = useState({
    telegram: 'spaghetti_print',
    bale: 'spaghetti_print',
  });

  useEffect(() => {
    getContact()
      .then((res) => {
        const api = res.data || {};
        const tg = (api.contact_telegram || '').replace(/^@/, '').trim();
        const bl = (api.contact_bale || '').replace(/^@/, '').trim();
        setContact((prev) => ({
          telegram: tg || prev.telegram,
          bale: bl || prev.bale,
        }));
      })
      .catch(() => {});
  }, []);

  const telegramHref = formatTelegramHref(contact.telegram);
  const baleHref = formatBaleHref(contact.bale);

  return (
    <div className={`public-page ${activeTab === 'columns' ? 'public-page--wide' : ''}`} dir="rtl">
      <header className="public-page-hero public-page-hero--dark">
        <p className="public-page-kicker">راهنمای مشتریان</p>
        <h1 className="public-page-title public-page-title--white">نحوه ثبت سفارش</h1>
        <p className="public-page-lead">
          شما می‌توانید به دو روش سفارش خود را ثبت فرمایید: سفارش مستقیم و آنلاین از سایت یا هماهنگی در پیام‌رسان‌ها (تلگرام و بله).
        </p>
      </header>

      {/* Mode Switcher */}
      <div className="order-mode-switcher-container" role="tablist" aria-label="انتخاب روش سفارش">
        <button
          type="button"
          role="tab"
          id="tab-site"
          aria-selected={activeTab === 'site'}
          aria-controls="panel-site"
          onClick={() => setActiveTab('site')}
          className={`order-mode-tab ${activeTab === 'site' ? 'active' : ''}`}
        >
          <Globe size={17} />
          <span>سفارش مستقیم از سایت</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-messenger"
          aria-selected={activeTab === 'messenger'}
          aria-controls="panel-messenger"
          onClick={() => setActiveTab('messenger')}
          className={`order-mode-tab ${activeTab === 'messenger' ? 'active' : ''}`}
        >
          <MessageCircle size={17} />
          <span>سفارش در پیام‌رسان‌ها (تلگرام / بله)</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-columns"
          aria-selected={activeTab === 'columns'}
          aria-controls="panel-columns"
          onClick={() => setActiveTab('columns')}
          className={`order-mode-tab ${activeTab === 'columns' ? 'active' : ''}`}
        >
          <Columns size={17} />
          <span>نمایش دو ستونه</span>
        </button>
      </div>

      {/* Tab Panels */}
      {activeTab === 'site' && (
        <div id="panel-site" role="tabpanel" aria-labelledby="tab-site" className="animate-fade-in">
          <div className="order-tab-intro">
            <h2 className="order-tab-intro-title">مراحل ثبت سفارش آنلاین از سایت</h2>
            <p className="order-tab-intro-desc">
              سریع‌ترین روش ثبت سفارش با امکان انتخاب چند محصول، تأیید پیامکی شماره تماس و پرداخت مستقیم.
            </p>
          </div>

          <StepsList steps={SITE_STEPS} variant="primary" />

          <div className="order-note">
            <p className="order-note-title">نکات مهم سفارش از سایت:</p>
            <p>• هنگام انتخاب محصول در کاتالوگ به ابعاد و مشخصات درج‌شده توجه فرمایید.</p>
            <p>• تمامی محصولات در رنگ‌ها و ابعاد دلخواه قابل سفارشی‌سازی هستند.</p>
            <p>• پس از ثبت درخواست در سبد خرید، وضعیت مرحله‌به‌مرحله از طریق پیامک یا پیام‌رسان به اطلاع شما می‌رسد.</p>
          </div>

          <div className="public-page-actions">
            <Link to="/" className="public-btn public-btn-primary">
              <ShoppingBag size={18} />
              <span>مشاهده کاتالوگ و خرید</span>
            </Link>
            <Link to="/checkout" className="public-btn public-btn-secondary">
              <span>مشاهده سبد خرید</span>
            </Link>
          </div>
        </div>
      )}

      {activeTab === 'messenger' && (
        <div id="panel-messenger" role="tabpanel" aria-labelledby="tab-messenger" className="animate-fade-in">
          <div className="order-tab-intro">
            <h2 className="order-tab-intro-title">مراحل سفارش از طریق پیام‌رسان‌ها</h2>
            <p className="order-tab-intro-desc">
              سفارش از کاتالوگ پیشنهادی از طریق پیام‌رسان‌های تلگرام و بله انجام می‌شود.
            </p>
          </div>

          <StepsList steps={MESSENGER_STEPS} variant="messenger" />

          <div className="order-note">
            <p className="order-note-title">نکات مهم:</p>
            <p>هنگام انتخاب محصول به ابعاد توجه فرمایید.</p>
            <p>تمامی محصولات در رنگ‌ها و ابعاد مختلف قابل سفارش هستند.</p>
          </div>

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

            <Link to="/" className="public-btn public-btn-secondary">
              <span>مشاهده کاتالوگ</span>
            </Link>
          </div>
        </div>
      )}

      {activeTab === 'columns' && (
        <div id="panel-columns" role="tabpanel" aria-labelledby="tab-columns" className="animate-fade-in">
          <div className="order-methods-grid">
            {/* Column 1: Site */}
            <div className="order-method-col">
              <div className="order-method-header">
                <div className="order-method-header-icon" aria-hidden="true">
                  <Globe size={22} />
                </div>
                <div>
                  <h2 className="order-method-title">روش اول: سفارش آنلاین از سایت</h2>
                  <p className="order-method-subtitle">افزودن به سبد، تأیید پیامکی و پرداخت امن</p>
                </div>
              </div>

              <StepsList steps={SITE_STEPS} variant="primary" />

              <div className="order-method-actions">
                <Link to="/" className="public-btn public-btn-primary">
                  <ShoppingBag size={17} />
                  <span>مشاهده کاتالوگ</span>
                </Link>
                <Link to="/checkout" className="public-btn public-btn-secondary">
                  <span>سبد خرید</span>
                </Link>
              </div>
            </div>

            {/* Column 2: Messenger */}
            <div className="order-method-col">
              <div className="order-method-header">
                <div className="order-method-header-icon order-method-header-icon--messenger" aria-hidden="true">
                  <Send size={22} />
                </div>
                <div>
                  <h2 className="order-method-title">روش دوم: سفارش در پیام‌رسان‌ها</h2>
                  <p className="order-method-subtitle">هماهنگی و ارسال کد محصول در تلگرام و بله</p>
                </div>
              </div>

              <StepsList steps={MESSENGER_STEPS} variant="messenger" />

              <div className="order-method-actions">
                <a
                  href={telegramHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="public-btn public-btn-telegram"
                >
                  <Send size={17} />
                  <span>ارسال پیام در تلگرام</span>
                </a>
                <a
                  href={baleHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="public-btn public-btn-bale"
                >
                  <MessageCircle size={17} />
                  <span>ارسال پیام در بله</span>
                </a>
              </div>
            </div>
          </div>

          <div className="order-note mt-6">
            <p className="order-note-title">نکات مهم:</p>
            <p>• هنگام انتخاب محصول به ابعاد و مشخصات درج‌شده توجه فرمایید.</p>
            <p>• تمامی محصولات در رنگ‌ها و ابعاد مختلف قابل سفارش هستند.</p>
            <p>• در هر دو روش، پشتیبانی اسپاگتی پرینت در تمامی مراحل تولید و ارسال همراه شماست.</p>
          </div>
        </div>
      )}
    </div>
  );
}
