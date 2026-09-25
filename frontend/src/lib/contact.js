/**
 * Public contact channels — edit handles/links here once (or later via settings).
 * Leave a value empty to hide that channel on the Contact page.
 */
export const CONTACT = {
  brand: 'اسپاگتی پرینت',
  tagline: 'چاپ سه‌بعدی FDM · سفارش و استعلام',
  hours: 'پاسخ‌گویی معمولاً در ساعات کاری (۹ تا ۲۱)',
  city: 'ایران',
  note: 'برای سفارش و استعلام قیمت، یکی از کانال‌های زیر را انتخاب کنید.',
};

/** @type {{ id: string, label: string, hint: string, href: string, handle: string, color: string }[]} */
export const CHANNELS = [
  {
    id: 'telegram',
    label: 'تلگرام',
    hint: 'سریع‌ترین راه برای استعلام و ارسال فایل',
    handle: '@YOUR_TELEGRAM',
    href: 'https://t.me/YOUR_TELEGRAM',
    color: '#2AABEE',
  },
  {
    id: 'whatsapp',
    label: 'واتس‌اپ',
    hint: 'پیام و عکس محصول / فایل',
    handle: '09XXXXXXXXX',
    href: 'https://wa.me/989XXXXXXXXX',
    color: '#25D366',
  },
  {
    id: 'instagram',
    label: 'اینستاگرام',
    hint: 'نمونه‌کارها و دایرکت',
    handle: '@YOUR_INSTAGRAM',
    href: 'https://instagram.com/YOUR_INSTAGRAM',
    color: '#E4405F',
  },
  {
    id: 'bale',
    label: 'بله',
    hint: 'پیام در پیام‌رسان بله',
    handle: '@YOUR_BALE',
    href: 'https://ble.ir/YOUR_BALE',
    color: '#00A3E0',
  },
];

export function activeChannels() {
  return CHANNELS.filter((c) => c.href && !c.href.includes('YOUR_') && !c.href.includes('XXXX'));
}

/** Prefer real links; if still placeholders, still show cards so you can edit. */
export function displayChannels() {
  return CHANNELS;
}
