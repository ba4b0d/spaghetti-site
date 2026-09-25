import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Image,
  MessageCircle,
  BadgeCheck,
  Wallet,
  PenTool,
  PackageCheck,
  Send,
  CheckCircle2,
} from 'lucide-react';
import { submitCustomOrder } from '../lib/api';
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

function CustomOrderForm() {
  const [form, setForm] = useState({ name: '', contact: '', channel: 'telegram', description: '', reference_product: '' });
  const [status, setStatus] = useState('idle'); // idle | submitting | success | error
  const [error, setError] = useState('');

  const handleChange = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.contact.trim() || form.contact.trim().length < 3) {
      setError('لطفاً حداقل یک راه ارتباطی (شماره یا آیدی) وارد کنید.');
      return;
    }
    setStatus('submitting');
    setError('');
    try {
      await submitCustomOrder(form);
      setStatus('success');
    } catch (err) {
      setStatus('error');
      setError(err?.response?.data?.detail || 'خطا در ثبت درخواست. لطفاً دوباره تلاش کنید.');
    }
  };

  if (status === 'success') {
    return (
      <div className="p-8 rounded-2xl text-center space-y-3" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <CheckCircle2 size={40} className="mx-auto" style={{ color: '#16a34a' }} />
        <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>درخواست شما ثبت شد!</h3>
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          به‌زودی برای استعلام قیمت با شما تماس می‌گیریم. همچنین می‌توانید از طریق پیام‌رسان‌ها سریع‌تر پاسخ بگیرید.
        </p>
        <Link to="/contact" className="public-btn public-btn-primary inline-flex items-center gap-2 mt-2">
          <MessageCircle size={16} />
          ارتباط مستقیم
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="p-6 rounded-2xl space-y-4" style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <h3 className="font-bold text-lg" style={{ color: 'var(--text-primary)' }}>درخواست سریع سفارش</h3>
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        فرم را پر کنید؛ ما در سریع‌ترین زمان استعلام قیمت می‌فرستیم.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-primary)' }}>نام شما</label>
          <input name="name" value={form.name} onChange={handleChange} className="input-field" placeholder="نام و نام خانوادگی" />
        </div>
        <div>
          <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-primary)' }}>
            راه ارتباطی <span style={{ color: 'var(--danger)' }}>*</span>
          </label>
          <input name="contact" value={form.contact} onChange={handleChange} className="input-field" placeholder="شماره موبایل یا آیدی تلگرام" required />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-primary)' }}>کانال ارتباطی</label>
        <select name="channel" value={form.channel} onChange={handleChange} className="select-field">
          <option value="telegram">تلگرام</option>
          <option value="instagram">اینستاگرام</option>
          <option value="bale">بله</option>
          <option value="phone">تماس تلفنی</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-primary)' }}>توضیح طرح / قطعه</label>
        <textarea name="description" value={form.description} onChange={handleChange} className="input-field" rows={4} placeholder="چه چیزی می‌خواهید؟ ابعاد حدودی، جنس، رنگ، یا اگر فایل STL/عکس دارید توضیح دهید..." />
      </div>

      <div>
        <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-primary)' }}>کد محصول (اختیاری)</label>
        <input name="reference_product" value={form.reference_product} onChange={handleChange} className="input-field" placeholder="مثلاً KE015 — اگر از کاتالوگ انتخاب کرده‌اید" />
      </div>

      {error && (
        <div className="p-3 rounded-lg text-sm" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
          {error}
        </div>
      )}

      <button type="submit" disabled={status === 'submitting'} className="btn-primary w-full inline-flex items-center justify-center gap-2">
        {status === 'submitting' ? (
          <>
            <span className="w-4 h-4 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: '#fff', borderTopColor: 'transparent' }} />
            در حال ثبت...
          </>
        ) : (
          <>
            <Send size={16} />
            ثبت درخواست استعلام قیمت
          </>
        )}
      </button>
    </form>
  );
}

export default function CustomOrder() {
  useSEO({
    title: 'سفارش قطعه و طرح دلخواه | پرینت سه‌بعدی سفارشی',
    description: 'راهنمای سفارش چاپ سه‌بعدی سفارشی، ارسال فایل STL یا عکس قطعه شکسته و استعلام قیمت پرینت سه‌بعدی در اسپاگتی پرینت',
    url: '/custom-order',
    jsonLd: buildWebSiteJsonLd(),
  });

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
        <Link to="/contact" className="public-btn public-btn-primary">
          تماس با ما
        </Link>
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 mt-16">
        <CustomOrderForm />
      </div>
    </div>
  );
}
