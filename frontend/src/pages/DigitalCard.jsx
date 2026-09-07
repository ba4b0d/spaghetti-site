import { useState, useEffect, useCallback } from 'react';
import { useSEO, buildOrganizationJsonLd } from '../lib/seo';
import { getContact, getPublicBrand } from '../lib/api';
import { QR_VIEWBOX, QR_MODULE, QR_DOTS } from '../lib/cardQr';

const PHONE = '09981923856';
const PHONE_DISPLAY = '0998 192 3856';
const CARD_URL = 'https://spaghettiprints.ir/card';

export default function DigitalCard() {
  useSEO({
    title: 'کارت ویزیت دیجیتال اسپاگتی پرینت',
    description: 'کارت ویزیت دیجیتال اسپاگتی پرینت — ارتباط مستقیم از تلگرام، اینستاگرام، بله و تماس تلفنی برای خدمات پرینت سه بعدی',
    url: '/card',
    jsonLd: buildOrganizationJsonLd(),
  });

  const [contact, setContact] = useState({ telegram: 'spaghetti_prints', instagram: 'spaghetti.prints', bale: 'spaghetti_prints', brand: 'اسپاگتی پرینت', city: 'تهران', logo: '/icon-512.png' });
  const [qrOpen, setQrOpen] = useState(false);
  const [toast, setToast] = useState('');

  useEffect(() => {
    getContact()
      .then((res) => {
        const api = res.data || {};
        setContact((prev) => ({
          ...prev,
          brand: api.contact_brand || prev.brand,
          telegram: (api.contact_telegram || prev.telegram).replace(/^@/, ''),
          instagram: (api.contact_instagram || prev.instagram).replace(/^@/, ''),
          bale: (api.contact_bale || prev.bale).replace(/^@/, ''),
          city: api.contact_city || prev.city,
        }));
      })
      .catch(() => {});
    getPublicBrand()
      .then((res) => {
        const logo = res.data?.logo_url;
        if (logo) setContact((prev) => ({ ...prev, logo }));
      })
      .catch(() => {});
  }, []);

  const showToast = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }, []);

  const downloadVCard = () => {
    const lines = [
      'BEGIN:VCARD',
      'VERSION:3.0',
      `FN;CHARSET=UTF-8:${contact.brand}`,
      `N;CHARSET=UTF-8:${contact.brand};;;;`,
      'ORG;CHARSET=UTF-8:استودیو چاپ سه بعدی اسپاگتی (Spaghetti Print)',
      'TITLE;CHARSET=UTF-8:خدمات تخصصی پرینت سه بعدی FDM و نمونهسازی',
      `TEL;TYPE=CELL,VOICE,PREF:${PHONE}`,
      'URL;CHARSET=UTF-8:https://spaghettiprints.ir',
      `NOTE;CHARSET=UTF-8:خدمات تخصصی پرینت سه بعدی FDM\\nتلگرام: @${contact.telegram}\\nاینستاگرام: @${contact.instagram}\\nبله: @${contact.bale}\\nوبسایت: spaghettiprints.ir`,
      `X-SOCIALPROFILE;type=telegram:https://t.me/${contact.telegram}`,
      `X-SOCIALPROFILE;type=instagram:https://instagram.com/${contact.instagram}`,
      `X-SOCIALPROFILE;type=bale:https://ble.ir/${contact.bale}`,
      'END:VCARD',
    ];
    const blob = new Blob([lines.join('\r\n')], { type: 'text/vcard;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'Spaghetti_Print.vcf');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast('مخاطب آماده ذخیره در تلفن همراه است');
  };

  const shareCard = () => {
    if (navigator.share) {
      navigator.share({
        title: 'کارت ویزیت دیجیتال اسپاگتی پرینت',
        text: 'خدمات تخصصی پرینت سه بعدی و نمونهسازی سریع اسپاگتی پرینت',
        url: CARD_URL,
      }).catch(() => {});
    } else {
      navigator.clipboard.writeText(CARD_URL).then(() => {
        showToast('لینک کارت ویزیت در کلیپبورد کپی شد');
      }).catch(() => {});
    }
  };

  return (
    <div className="dcard-page">
      <div className="dcard-container">

        {/* TOP PROFILE SECTION */}
        <div className="dcard-profile">
          <div className="dcard-avatar-wrap">
            <img src={contact.logo} alt="Spaghetti Print Logo" className="dcard-avatar" />
            <div className="dcard-online-badge" title="آماده پذیرش سفارش" />
          </div>

          <h1 className="dcard-brand-name">
            {contact.brand}
            <svg className="dcard-verify-badge" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" /></svg>
          </h1>
          <div className="dcard-brand-sub">SPAGHETTI PRINT · 3D STUDIO</div>
          <p className="dcard-brand-desc">
            خدمات تخصصی پرینت سه بعدی FDM · نمونهسازی سریع قطعات صنعتی و دکوراتیو · از ایده تا واقعیت، لایه به لایه
          </p>

          <div className="dcard-meta-pills">
            <span className="dcard-meta-pill">📍 {contact.city} · ارسال سراسر کشور</span>
            <span className="dcard-meta-pill">💎 دقت ۰.۰۸ تا ۰.۲۸ میلیمتر</span>
            <span className="dcard-meta-pill">🛠️ فیلامنت PLA · PETG · ABS</span>
          </div>
        </div>

        {/* PRIMARY ACTION: VCARD & SHARE */}
        <div className="dcard-primary-actions">
          <button type="button" className="dcard-btn-save" onClick={downloadVCard}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></svg>
            افزودن به مخاطبین تلفن (vCard)
          </button>

          <button type="button" className="dcard-btn-icon" onClick={() => setQrOpen(true)} title="نمایش بارکد اختصاصی" aria-label="نمایش بارکد">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></svg>
          </button>

          <button type="button" className="dcard-btn-icon" onClick={shareCard} title="کپی لینک کارت" aria-label="اشتراک گذاری کارت">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" /></svg>
          </button>
        </div>

        {/* DIRECT COMMUNICATION TILES */}
        <div className="dcard-channels">

          <a href={`https://t.me/${contact.telegram}`} target="_blank" rel="noopener noreferrer" className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #2AABEE, #229ED9)' }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">ارسال فایل و پیام در تلگرام</div>
                <div className="dcard-channel-sub">@{contact.telegram} · استعلام قیمت و ارسال فایل سه بعدی</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

          <a href={`https://instagram.com/${contact.instagram}`} target="_blank" rel="noopener noreferrer" className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #833AB4, #FD1D1D, #FCB045)' }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">پیج رسمی اینستاگرام</div>
                <div className="dcard-channel-sub">@{contact.instagram} · نمونه کارها و ویدیوهای چاپ</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

          <a href={`https://ble.ir/${contact.bale}`} target="_blank" rel="noopener noreferrer" className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #00A3E0, #0077A8)' }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">ارتباط در پیامرسان بله</div>
                <div className="dcard-channel-sub">@{contact.bale} · پشتیبانی و سفارش مستقیم</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

          <a href={`tel:${PHONE}`} className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">تماس تلفنی مستقیم</div>
                <div className="dcard-channel-sub" dir="ltr">{PHONE_DISPLAY} · مشاوره و سفارش</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

          <a href="https://spaghettiprints.ir/custom-order" target="_blank" rel="noopener noreferrer" className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="12" y1="18" x2="12" y2="12" /><line x1="9" y1="15" x2="15" y2="15" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">سفارش قطعه اختصاصی / فایل دلخواه</div>
                <div className="dcard-channel-sub">آپلود مدل سه بعدی و استعلام مستقیم قیمت</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

          <a href="https://spaghettiprints.ir" target="_blank" rel="noopener noreferrer" className="dcard-channel-tile">
            <div className="dcard-channel-left">
              <div className="dcard-channel-icon" style={{ background: 'linear-gradient(135deg, #6366f1, #4f46e5)' }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /><path d="M16 10a4 4 0 0 1-8 0" /></svg>
              </div>
              <div className="dcard-channel-text">
                <div className="dcard-channel-title">مشاهده کاتالوگ محصولات</div>
                <div className="dcard-channel-sub">spaghettiprints.ir · فیگورها، اکسسوری و قطعات آماده</div>
              </div>
            </div>
            <div className="dcard-channel-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </div>
          </a>

        </div>

        {/* FOOTER */}
        <div className="dcard-footer">
          <div>تمامی حقوق محفوظ است © ۱۴۰۳</div>
          <a href="https://spaghettiprints.ir" className="dcard-footer-brand" target="_blank" rel="noopener noreferrer">اسپاگتی پرینت · استودیو تولید دیجیتال</a>
        </div>

      </div>

      {/* QR MODAL */}
      {qrOpen && (
        <div className="dcard-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setQrOpen(false); }}>
          <div className="dcard-modal-content">
            <h3 className="dcard-modal-title">بارکد کارت ویزیت اسپاگتی پرینت</h3>
            <p className="dcard-modal-sub">دوربین گوشی را مقابل بارکد بگیرید تا این صفحه باز شود</p>

            <div className="dcard-modal-qr-box">
              <svg width="180" height="180" viewBox={QR_VIEWBOX} role="img" aria-label="بارکد صفحه کارت ویزیت">
                <rect width="100%" height="100%" fill="#ffffff" />
                {QR_DOTS.map(([x, y]) => (
                  <rect key={`${x}-${y}`} x={x} y={y} width={QR_MODULE} height={QR_MODULE} rx="1.6" fill="#111420" />
                ))}
              </svg>
            </div>

            <div className="dcard-modal-url">spaghettiprints.ir/card</div>

            <button type="button" className="dcard-btn-close" onClick={() => setQrOpen(false)}>بستن پنجره</button>
          </div>
        </div>
      )}

      {/* TOAST */}
      <div className={`dcard-toast${toast ? ' show' : ''}`}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
        <span>{toast || 'لینک کارت ویزیت در کلیپبورد کپی شد'}</span>
      </div>
    </div>
  );
}
