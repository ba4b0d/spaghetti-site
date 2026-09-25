import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { MessageCircle, Send, Camera, Phone, ExternalLink, ClipboardList } from 'lucide-react';
import { CONTACT, CHANNELS, displayChannels } from '../lib/contact';
import { getContact } from '../lib/api';
import { useSEO, buildOrganizationJsonLd } from '../lib/seo';

const ICONS = {
  phone: Phone,
  telegram: Send,
  instagram: Camera,
  bale: MessageCircle,
};

/** Merge API contact settings into the static CHANNELS array. */
function mergeChannels(api) {
  return CHANNELS.map((ch) => {
    const apiKey = `contact_${ch.id}`;
    const value = api[apiKey] || '';
    if (!value) return ch; // keep static default

    // Build href and handle based on channel type
    let href = ch.href;
    let handle = ch.handle;
    if (ch.id === 'phone') {
      const clean = value.replace(/\s+/g, '');
      const rawDigits = value.replace(/[^0-9]/g, '');
      handle = value;
      const intl = rawDigits.startsWith('98') ? `+${rawDigits}` : rawDigits.startsWith('0') ? `+98${rawDigits.slice(1)}` : `+98${rawDigits}`;
      href = `tel:${clean.startsWith('+') ? clean : intl}`;
    } else if (ch.id === 'telegram') {
      const clean = value.replace(/^@/, '');
      handle = `@${clean}`;
      href = `https://t.me/${clean}`;
    } else if (ch.id === 'instagram') {
      const clean = value.replace(/^@/, '');
      handle = `@${clean}`;
      href = `https://instagram.com/${clean}`;
    } else if (ch.id === 'bale') {
      const clean = value.replace(/^@/, '');
      handle = `@${clean}`;
      href = `https://ble.ir/${clean}`;
    }
    return { ...ch, handle, href };
  });
}

export default function Contact() {
  useSEO({
    title: 'تماس با ما',
    description: 'راههای ارتباط با اسپاگتی پرینت — تماس تلفنی، تلگرام، اینستاگرام، بله',
    url: '/contact',
    jsonLd: buildOrganizationJsonLd(),
  });

  const [channels, setChannels] = useState(displayChannels());
  const [contact, setContact] = useState(CONTACT);

  useEffect(() => {
    getContact()
      .then((res) => {
        const api = res.data || {};
        // Merge channel data
        setChannels(mergeChannels(api));
        // Merge top-level contact info (brand, hours, city, note)
        setContact({
          ...CONTACT,
          brand: api.contact_brand || CONTACT.brand,
          hours: api.contact_hours || CONTACT.hours,
          city: api.contact_city || CONTACT.city,
          note: api.contact_note || CONTACT.note,
        });
      })
      .catch((err) => {
        console.warn('Failed to load contact info from API, using static defaults:', err);
      });
  }, []);

  return (
    <div className="public-page" dir="rtl">
      <header className="public-page-hero public-page-hero--dark">
        <p className="public-page-kicker">ارتباط با ما</p>
        <h1 className="public-page-title public-page-title--white">تماس با {contact.brand}</h1>
        <p className="public-page-lead">{contact.note}</p>
        <p className="public-page-meta">
          {contact.hours}
          {contact.city ? ` · ${contact.city}` : ''}
        </p>
      </header>

      <div className="contact-grid">
        {channels.map((ch) => {
          const Icon = ICONS[ch.id] || MessageCircle;
          const isPlaceholder = ch.href.includes('YOUR_') || ch.href.includes('XXXX');
          const isPhone = ch.id === 'phone';
          return (
            <a
              key={ch.id}
              href={isPlaceholder ? undefined : ch.href}
              target={isPlaceholder || isPhone ? undefined : '_blank'}
              rel={isPlaceholder || isPhone ? undefined : 'noopener noreferrer'}
              className={`contact-card${isPlaceholder ? ' contact-card--soon' : ''}`}
              style={{ '--ch-color': ch.color }}
              aria-disabled={isPlaceholder || undefined}
              onClick={isPlaceholder ? (e) => e.preventDefault() : undefined}
            >
              <div className="contact-card-icon" aria-hidden="true">
                <Icon size={22} />
              </div>
              <div className="contact-card-body min-w-0">
                <div className="contact-card-label">{ch.label}</div>
                <div className="contact-card-handle truncate" dir="ltr">
                  {ch.handle}
                </div>
                <p className="contact-card-hint">{ch.hint}</p>
                {isPlaceholder ? (
                  <span className="contact-card-cta">بهزودی — لینک را در تنظیمات پر کنید</span>
                ) : (
                  <span className="contact-card-cta">
                    {isPhone ? 'برقراری تماس' : 'باز کردن'}
                    {isPhone ? <Phone size={12} /> : <ExternalLink size={12} />}
                  </span>
                )}
              </div>
            </a>
          );
        })}
      </div>

      <div className="public-page-actions">
        <Link to="/how-to-order" className="public-btn public-btn-primary">
          <ClipboardList size={16} />
          نحوه سفارش
        </Link>
        <Link to="/" className="public-btn public-btn-ghost">
          بازگشت به کاتالوگ
        </Link>
      </div>
    </div>
  );
}
