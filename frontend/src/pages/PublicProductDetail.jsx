import { useState, useEffect, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useParams, Link } from 'react-router-dom';
import {
  Package,
  Weight,
  Layers,
  ChevronLeft,
  ChevronRight,
  Ruler,
  ArrowRight,
  Send,
  MessageCircle,
  Box,
  Maximize2,
  X,
} from 'lucide-react';
import { getCatalog, getCatalogProductBySlug, getCatalogProduct } from '../lib/api';
import { formatPrice } from '../lib/utils';
import { useSEO, buildProductJsonLd, buildBreadcrumbJsonLd, absoluteUrl } from '../lib/seo';
import { Z_INDEX_MODAL_PORTAL } from '../lib/constants';

function displayName(name) {
  if (!name || /^[?\s]+$/.test(name)) return 'بدون نام';
  return name;
}

function ProductImageGallery({ images, name }) {
  const [current, setCurrent] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [touchStart, setTouchStart] = useState(null);
  const [touchEnd, setTouchEnd] = useState(null);

  const sorted = useMemo(() => {
    if (!images || images.length === 0) return [];
    return [...images].sort((a, b) => {
      if (a.is_primary && !b.is_primary) return -1;
      if (!a.is_primary && b.is_primary) return 1;
      return (a.sort_order || 0) - (b.sort_order || 0);
    });
  }, [images]);

  const next = useCallback(() => setCurrent((c) => (c + 1) % sorted.length), [sorted.length]);
  const prev = useCallback(
    () => setCurrent((c) => (c - 1 + sorted.length) % sorted.length),
    [sorted.length]
  );

  const openFullscreen = useCallback(() => setFullscreen(true), []);
  const closeFullscreen = useCallback(() => setFullscreen(false), []);

  // Escape / arrow-key navigation while fullscreen
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e) => {
      if (e.key === 'Escape') { closeFullscreen(); return; }
      if (e.key === 'ArrowLeft') next();
      if (e.key === 'ArrowRight') prev();
    };
    document.addEventListener('keydown', onKey);
    // Lock body scroll behind the overlay
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [fullscreen, next, prev, closeFullscreen]);

  const onTouchStart = (e) => {
    setTouchEnd(null);
    setTouchStart(e.targetTouches[0].clientX);
  };
  const onTouchMove = (e) => setTouchEnd(e.targetTouches[0].clientX);
  const onTouchEnd = () => {
    if (!touchStart || !touchEnd) return;
    const distance = touchStart - touchEnd;
    if (distance > 50) next();
    if (distance < -50) prev();
  };

  if (sorted.length === 0) {
    return (
      <div className="w-full aspect-square flex flex-col items-center justify-center gap-3 catalog-img-placeholder rounded-[1.25rem]">
        <Package size={48} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
          بدون تصویر
        </span>
      </div>
    );
  }

  if (sorted.length === 1) {
    return (
      <>
        <div className="relative w-full aspect-square overflow-hidden rounded-[1.25rem]">
          <img
            src={sorted[0].image_url}
            alt={name || ''}
            className="w-full h-full object-cover rounded-[1.25rem]"
            loading="eager"
          />
          <button
            type="button"
            onClick={openFullscreen}
            className="absolute bottom-3 left-3 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm transition-opacity"
            aria-label="تمام صفحه"
            title="تمام صفحه"
          >
            <Maximize2 size={18} />
          </button>
        </div>
        <FullscreenView
          open={fullscreen}
          sorted={sorted}
          current={current}
          onClose={closeFullscreen}
          onPrev={prev}
          onNext={next}
        />
      </>
    );
  }

  return (
    <>
      <div className="space-y-3">
        <div
          className="relative w-full aspect-square overflow-hidden rounded-[1.25rem] bg-transparent"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
        >
          <img
            src={sorted[current].image_url}
            alt={name || ''}
            className="w-full h-full object-cover rounded-[1.25rem] transition-transform duration-700"
            loading={current === 0 ? 'eager' : 'lazy'}
          />
          <button
            type="button"
            onClick={prev}
            className="absolute left-3 top-1/2 -translate-y-1/2 p-2.5 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm transition-opacity"
            aria-label="قبلی"
          >
            <ChevronLeft size={20} />
          </button>
          <button
            type="button"
            onClick={next}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm transition-opacity"
            aria-label="بعدی"
          >
            <ChevronRight size={20} />
          </button>
          <button
            type="button"
            onClick={openFullscreen}
            className="absolute bottom-3 left-3 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm transition-opacity"
            aria-label="تمام صفحه"
            title="تمام صفحه"
          >
            <Maximize2 size={18} />
          </button>
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5">
            {sorted.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setCurrent(i)}
                className="rounded-full transition-all"
                style={{
                  width: i === current ? 18 : 7,
                  height: 7,
                  backgroundColor: i === current ? '#fff' : 'rgba(255,255,255,0.45)',
                }}
                aria-label={`تصویر ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Thumbnails */}
        <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
          {sorted.map((img, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setCurrent(i)}
              className={`relative flex-shrink-0 w-16 h-16 sm:w-20 sm:h-20 rounded-xl overflow-hidden border-2 transition-all ${
                i === current ? 'border-accent ring-2 ring-accent/20' : 'border-transparent opacity-75 hover:opacity-100'
              }`}
              style={i === current ? { borderColor: 'var(--accent)' } : undefined}
              aria-label={`تصویر ${i + 1}`}
            >
              <img
                src={img.image_url}
                alt={`${name || ''} ${i + 1}`}
                className="w-full h-full object-cover rounded-lg"
                loading="lazy"
              />
            </button>
          ))}
        </div>
      </div>
      <FullscreenView
        open={fullscreen}
        sorted={sorted}
        current={current}
        onClose={closeFullscreen}
        onPrev={prev}
        onNext={next}
      />
    </>
  );
}

function FullscreenView({ open, sorted, current, onClose, onPrev, onNext }) {
  if (!open) return null;
  const img = sorted[current];
  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: Z_INDEX_MODAL_PORTAL + 5,
        backgroundColor: 'rgba(0, 0, 0, 0.94)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div style={{ position: 'absolute', inset: 0, overflow: 'hidden' }} />
      <img
        src={img.image_url}
        alt={img.alt || ''}
        className="max-w-[94vw] max-h-[92vh] object-contain rounded-lg shadow-2xl"
        style={{ position: 'relative', zIndex: 1 }}
        onClick={(e) => e.stopPropagation()}
      />
      {/* Close */}
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white backdrop-blur-sm transition-colors"
        aria-label="بستن"
        title="بستن (Esc)"
      >
        <X size={22} />
      </button>
      {/* Counter */}
      <span
        className="absolute bottom-4 left-1/2 -translate-x-1/2 text-white/70 text-sm tabular-nums"
        style={{ direction: 'ltr' }}
      >
        {current + 1} / {sorted.length}
      </span>
      {/* Nav */}
      {sorted.length > 1 && (
        <>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onPrev(); }}
            className="absolute left-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 hover:bg-white/20 text-white backdrop-blur-sm transition-colors"
            aria-label="قبلی"
          >
            <ChevronLeft size={26} />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onNext(); }}
            className="absolute right-4 top-1/2 -translate-y-1/2 p-3 rounded-full bg-white/10 hover:bg-white/20 text-white backdrop-blur-sm transition-colors"
            aria-label="بعدی"
          >
            <ChevronRight size={26} />
          </button>
        </>
      )}
    </div>,
    document.body
  );
}

function InfoItem({ icon: Icon, label, value, suffix }) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: 'var(--bg-secondary)' }}>
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ backgroundColor: 'var(--accent-light)' }}
      >
        <Icon size={18} style={{ color: 'var(--accent)' }} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {label}
        </div>
        <div className="text-sm font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
          {value}
          {suffix ? <span className="text-xs font-normal mr-1">{suffix}</span> : null}
        </div>
      </div>
    </div>
  );
}

export default function PublicProductDetail() {
  const { slug } = useParams();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [relatedProducts, setRelatedProducts] = useState([]);

  const productName = product?.name;
  const productImage =
    product?.image_url ||
    product?.images?.find((i) => i.is_primary)?.image_url ||
    product?.images?.[0]?.image_url;

  const productPrice = product?.final_price || product?.suggested_price;
  const priceFormatted = productPrice ? formatPrice(productPrice) : '';

  const categoryOrColl =
    product?.collections?.[0]?.name ||
    product?.categories?.[0]?.name ||
    product?.category ||
    'پرینت سه‌بعدی';

  // High-CTR SEO Title Formula: e.g. "خرید فیگور دناتلو لاکپشتهای نینجا ۳ بعدی + انتخاب رنگ"
  const seoTitle = productName
    ? `خرید ${productName} (${categoryOrColl}) ۳ بعدی + انتخاب رنگ`
    : undefined;

  // High-CTR SEO Description: Preserves your custom notes, with rich fallback
  const seoDims = [product?.dimension_x, product?.dimension_y, product?.dimension_z]
    .filter(Boolean)
    .map((d) => (d / 10).toFixed(1));
  const dimsText = seoDims.length === 3 ? `ابعاد ${seoDims[0]}×${seoDims[1]}×${seoDims[2]} سانتی‌متر، ` : '';
  const priceSnippet = priceFormatted ? `قیمت ${priceFormatted}، ` : '';

  const seoDescription =
    (product?.notes && String(product.notes).trim()) ||
    (productName
      ? `خرید آنلاین ${productName} با چاپ سه‌بعدی PLA. ${dimsText}${priceSnippet}با قابلیت شخصی‌سازی رنگ و ارسال سریع در اسپاگتی پرینت.`
      : undefined);

  const jsonLd = useMemo(() => {
    if (!product) return null;
    const productSchema = buildProductJsonLd(product);
    const crumbs = buildBreadcrumbJsonLd([
      { name: 'کاتالوگ', path: '/' },
      { name: product.name, path: product.slug ? `/catalog/${product.slug}` : `/catalog/${product.id}` },
    ]);
    return [productSchema, crumbs].filter(Boolean);
  }, [product]);

  useSEO({
    title: seoTitle,
    description: seoDescription,
    image: productImage ? absoluteUrl(productImage) : undefined,
    url: product?.slug ? absoluteUrl(`/catalog/${product.slug}`) : undefined,
    jsonLd,
  });

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      if (!slug) {
        setError('کد محصول مشخص نشده است');
        setLoading(false);
        return;
      }
      try {
        let res;
        try {
          res = await getCatalogProductBySlug(slug);
        } catch (slugErr) {
          if (/^\d+$/.test(slug)) {
            res = await getCatalogProduct(slug);
          } else {
            throw slugErr;
          }
        }
        setProduct(res.data);
        setError(null);
      } catch (err) {
        if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
          if (err.response?.status === 404) {
            setError('محصول مورد نظر یافت نشد');
          } else {
            console.error('PublicProductDetail load error:', err);
            setError('خطا در بارگذاری محصول');
          }
        }
      } finally {
        setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [slug]);

  // Load related items from same collection/category for SEO internal linking & UX
  useEffect(() => {
    if (!product) return;
    let isMounted = true;
    getCatalog()
      .then((res) => {
        if (!isMounted) return;
        const allItems = Array.isArray(res.data) ? res.data : [];
        const currentId = product.id;
        const currentCollId = product.collections?.[0]?.id;
        const currentCatId = product.categories?.[0]?.id;

        let matches = [];
        if (currentCollId) {
          matches = allItems.filter(
            (p) => p.id !== currentId && p.collections?.some((c) => c.id === currentCollId)
          );
        }
        if (matches.length < 4 && currentCatId) {
          const catMatches = allItems.filter(
            (p) =>
              p.id !== currentId &&
              !matches.some((m) => m.id === p.id) &&
              p.categories?.some((c) => c.id === currentCatId)
          );
          matches = [...matches, ...catMatches];
        }
        if (matches.length < 4) {
          const generalMatches = allItems.filter(
            (p) => p.id !== currentId && !matches.some((m) => m.id === p.id)
          );
          matches = [...matches, ...generalMatches];
        }
        setRelatedProducts(matches.slice(0, 4));
      })
      .catch((err) => console.error('Error loading related products:', err));

    return () => {
      isMounted = false;
    };
  }, [product]);

  const shareUrl = useMemo(() => {
    if (typeof window === 'undefined') return '';
    return window.location.href;
  }, []);

  const shareText = useMemo(() => {
    if (!product) return '';
    const name = displayName(product.name);
    const price = product.final_price || product.suggested_price;
    const priceText = price ? ` — ${formatPrice(price)}` : '';
    return `${name}${priceText}`;
  }, [product]);

  const telegramShareUrl = useMemo(() => {
    const url = encodeURIComponent(shareUrl);
    const text = encodeURIComponent(shareText);
    return `https://t.me/share/url?url=${url}&text=${text}`;
  }, [shareUrl, shareText]);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto animate-fade-in">
        <div className="skeleton-pulse h-5 w-32 rounded mb-6" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="skeleton-pulse aspect-square rounded-[1.25rem]" />
          <div className="space-y-4">
            <div className="skeleton-pulse h-8 w-3/4 rounded" />
            <div className="skeleton-pulse h-4 w-1/3 rounded" />
            <div className="grid grid-cols-2 gap-3">
              <div className="skeleton-pulse h-16 rounded-xl" />
              <div className="skeleton-pulse h-16 rounded-xl" />
              <div className="skeleton-pulse h-16 rounded-xl" />
              <div className="skeleton-pulse h-16 rounded-xl" />
            </div>
            <div className="skeleton-pulse h-12 w-full rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="max-w-xl mx-auto text-center py-16 sm:py-24 animate-fade-in">
        <div
          className="mx-auto mb-5 w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{ background: 'var(--accent-light)' }}
        >
          <Package size={32} style={{ color: 'var(--accent)', opacity: 0.85 }} />
        </div>
        <h2 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
          {error || 'محصول یافت نشد'}
        </h2>
        <p className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>
          ممکن است محصول حذف شده یا لینک نادرست باشد.
        </p>
        <Link to="/" className="btn-primary inline-flex items-center gap-2">
          <ArrowRight size={18} />
          بازگشت به کاتالوگ
        </Link>
      </div>
    );
  }

  const price = product.final_price || product.suggested_price;
  const rawNotes = product.notes?.trim?.() || '';
  const rawPackageInfo = product.package_info?.trim?.() || '';

  // Priority: explicit package_info column, fallback to regex extraction for legacy items
  const isSimpleQuantity = /^\d+\s*عدد(\s*به\s*همراه\s*.+)?$/i.test(rawNotes);
  const packageQuantityNote = rawPackageInfo || (isSimpleQuantity ? rawNotes : null);
  const descriptionText = isSimpleQuantity && !rawPackageInfo ? null : (rawNotes || null);

  const dims = [product.dimension_x, product.dimension_y, product.dimension_z]
    .map((d) => Math.round(d || 0))
    .sort((a, b) => b - a);
  const dimensionText = dims.some((d) => d > 0)
    ? `${dims[0]} × ${dims[1]} × ${dims[2]} میلی‌متر`
    : null;

  return (
    <div className="max-w-5xl mx-auto animate-fade-in">
      {/* Breadcrumb / back */}
      <div className="flex items-center gap-2 mb-5">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium hover:opacity-80 transition-opacity"
          style={{ color: 'var(--text-primary)' }}
        >
          <ArrowRight size={16} />
          بازگشت به کاتالوگ
        </Link>
        <span style={{ color: 'var(--text-muted)' }}>/</span>
        <Link to="/" className="text-sm font-medium hover:underline" style={{ color: 'var(--text-primary)' }}>
          کاتالوگ
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 lg:gap-8 items-stretch">
        {/* Gallery — no card background; image sits on page surface */}
        <div className="h-full flex flex-col justify-center min-h-0">
          <ProductImageGallery images={product.images} name={product.name} />
        </div>

        {/* Details card */}
        <div className="card p-5 sm:p-6 flex flex-col gap-5 h-full min-h-0">
          <div>
            <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
              <h1
                className="text-xl sm:text-2xl font-bold leading-snug"
                style={{ color: 'var(--text-primary)' }}
              >
                {displayName(product.name)}
              </h1>
              {product.category && (
                <span className="catalog-cat-badge shrink-0">{product.category}</span>
              )}
            </div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
              <span>کد محصول:</span>
              <span className="catalog-code-badge font-mono text-xs">{product.product_id}</span>
            </div>
          </div>

          {/* Price */}
          <div
            className="p-4 rounded-xl"
            style={{ backgroundColor: 'var(--accent-light)' }}
          >
            <div>
              <div className="text-xs mb-0.5" style={{ color: 'var(--text-muted)' }}>
                {product.final_price ? 'قیمت نهایی' : 'قیمت'}
              </div>
              <div className="text-2xl font-bold tabular-nums" style={{ color: 'var(--accent)' }}>
                {price ? formatPrice(price) : 'تماس بگیرید'}
              </div>
            </div>
          </div>

          {/* Customization Callout */}
          <div
            className="p-3.5 rounded-xl border flex items-center gap-3 text-xs leading-relaxed"
            style={{
              backgroundColor: 'rgba(99, 102, 241, 0.08)',
              borderColor: 'rgba(99, 102, 241, 0.25)',
              color: 'var(--text-primary)',
            }}
          >
            <span className="text-base select-none">🎨</span>
            <div>
              <strong>امکان شخصی‌سازی سفارش:</strong> این محصول قابلیت تغییر رنگ، ابعاد یا اضافه کردن اسم و متن دلخواه را دارد.
            </div>
          </div>

          {/* Specs grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {product.material_name && (
            <InfoItem
              icon={Layers}
              label="ماده"
              value={
                <span className="inline-flex items-center gap-2">
                  {product.material_color ? (
                    <span
                      className="w-3.5 h-3.5 rounded-full border"
                      style={{
                        backgroundColor: product.material_color,
                        borderColor: 'var(--border-color)',
                      }}
                      title={product.material_color}
                    />
                  ) : null}
                  {product.material_name}
                </span>
              }
            />
            )}
            {product.weight_g > 0 && (
              <InfoItem icon={Weight} label="وزن" value={product.weight_g} suffix="گرم" />
            )}
            {packageQuantityNote && (
              <InfoItem icon={Box} label="محتویات بسته" value={packageQuantityNote} />
            )}
            {dimensionText && (
              <InfoItem icon={Ruler} label="ابعاد (طول × عرض × ارتفاع)" value={dimensionText} />
            )}
          </div>

          {/* Notes / Description */}
          {descriptionText && (
            <div className="space-y-3 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              <div>
                <div className="text-xs font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>
                  توضیحات
                </div>
                <p style={{ whiteSpace: 'pre-line' }}>{descriptionText}</p>
              </div>
            </div>
          )}

          {/* Collection Bundle / Playlist Widget */}
          {product.collections && product.collections.length > 0 && (() => {
            const coll = product.collections[0];
            const collName = coll.name;
            const collSlug = coll.slug;
            const targetLink = `/collection/${encodeURIComponent(collSlug || collName)}`;

            return (
              <div className="p-4 rounded-xl space-y-3" style={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold flex items-center gap-1.5" style={{ color: 'var(--text-primary)' }}>
                    📦 محصولات این کالکشن ({collName})
                  </span>
                  <Link to={targetLink} className="text-accent hover:underline font-medium">
                    مشاهده همه ←
                  </Link>
                </div>
              </div>
            );
          })()}

          {/* CTAs */}
          <div className="pt-4 mt-auto border-t flex flex-col sm:flex-row gap-3" style={{ borderColor: 'var(--border-color)' }}>
            <Link
              to="/contact"
              className="btn-primary flex-1 inline-flex items-center justify-center gap-2"
            >
              <MessageCircle size={18} />
              تماس برای سفارش
            </Link>
            <a
              href={telegramShareUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary inline-flex items-center justify-center gap-2"
              style={{ backgroundColor: '#27a7e7', color: '#ffffff', borderColor: 'transparent' }}
            >
              <Send size={18} />
              اشتراک در تلگرام
            </a>
          </div>
        </div>
      </div>

      {/* Related Products section for SEO Internal Linking & User Discovery */}
      {relatedProducts.length > 0 && (
        <section className="card p-5 sm:p-6 mt-10 sm:mt-14 border rounded-2xl" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-base sm:text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                محصولات مرتبط و پیشنهادی
              </h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                سایر محصولات محبوب و مشابه از این دسته و کالکشن
              </p>
            </div>
            <Link to="/" className="text-xs font-semibold text-accent hover:underline">
              مشاهده همه محصولات ←
            </Link>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
            {relatedProducts.map((rel) => {
              const relPrice = rel.final_price || rel.suggested_price;
              const relImg =
                rel.image_url ||
                rel.images?.find((i) => i.is_primary)?.image_url ||
                rel.images?.[0]?.image_url;

              return (
                <Link
                  key={rel.id}
                  to={`/catalog/${rel.slug || rel.id}`}
                  className="catalog-product-card group flex flex-col overflow-hidden transition-all hover:scale-[1.02]"
                >
                  <div className="relative aspect-square overflow-hidden rounded-[1rem]" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
                    {relImg ? (
                      <img
                        src={relImg}
                        alt={rel.name}
                        width={240}
                        height={240}
                        loading="lazy"
                        decoding="async"
                        className="w-full h-full object-cover rounded-[1rem] transition-transform duration-500 group-hover:scale-105"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Package size={28} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
                      </div>
                    )}
                  </div>
                  <div className="p-3 flex-1 flex flex-col justify-between gap-1.5">
                    <h3 className="font-bold text-xs leading-snug line-clamp-2" style={{ color: 'var(--text-primary)' }}>
                      {displayName(rel.name)}
                    </h3>
                    <div className="text-[11px] font-bold text-accent">
                      {relPrice ? formatPrice(relPrice) : 'قیمت تماس بگیرید'}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
