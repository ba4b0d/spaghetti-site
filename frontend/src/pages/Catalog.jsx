import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Search, Package, Clock, Weight, Layers, ChevronLeft, ChevronRight, Ruler, Send } from 'lucide-react';
import { getCatalog, getCatalogCategories, getCatalogCollections } from '../lib/api';
import { formatPrice, formatMinutes } from '../lib/utils';
import { useSEO, buildWebSiteJsonLd, buildOrganizationJsonLd, buildFaqJsonLd } from '../lib/seo';

const FAQ_ITEMS = [
  {
    question: 'پرینت سه بعدی با چه متریالی انجام میشود و چقدر مقاوم است؟',
    answer: 'محصولات اسپاگتی پرینت با فیلامنت درجه یک PLA (پلیلاکتیک اسید) تولید میشوند که بر پایه نیشکر و نشاسته ذرت بوده و کاملاً بدون بو، زیستسازگار و دارای استحکام مکانیکی بسیار بالا برای استفادههای دکوراتیو، فیگور و قطعات کاربردی است.',
  },
  {
    question: 'چگونه میتوانم فایل سه بعدی اختصاصی یا عکس قطعه شکسته را برای چاپ ارسال کنم؟',
    answer: 'کافیست وارد صفحه «سفارش طرح دلخواه» شوید یا در تلگرام و پیامرسانها فایل مدل خود با فرمتهای STL، 3MF، OBJ یا عکس از زوایای مختلف قطعه را ارسال نمایید تا در کوتاهترین زمان برآورد وزن، زمان و قیمت انجام شود.',
  },
  {
    question: 'زمان آمادهسازی و ارسال سفارشات چقدر است؟',
    answer: 'بسته به ابعاد قطعه و تعداد سفارش، محصولات کاتالوگ ظرف ۲۴ تا ۴۸ ساعت چاپ و آماده ارسال پستی به سراسر ایران میشوند. کلیه بستهها با محافظ ضدضربه ارسال میگردند.',
  },
  {
    question: 'آیا امکان تغییر رنگ یا حک اسم دلخواه روی محصولات وجود دارد؟',
    answer: 'بله؛ تنوع گستردهای از رنگهای جذاب فیلامنت موجود است و در زمان ثبت سفارش میتوانید رنگ مورد نظرتان را انتخاب کنید یا درخواست درج اسم و نوشته دلخواه را ثبت نمایید.',
  },
];

function FaqSection() {
  const [openIndex, setOpenIndex] = useState(null);

  const toggle = (idx) => {
    setOpenIndex((prev) => (prev === idx ? null : idx));
  };

  return (
    <section className="card p-6 sm:p-8 rounded-3xl border space-y-4" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
      <div className="flex items-center justify-between pb-4 border-b" style={{ borderColor: 'var(--border-color)' }}>
        <div>
          <h3 className="text-base sm:text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            سؤالات متداول (FAQ)
          </h3>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            پاسخ به سؤالات پرتکرار درباره چاپ سه بعدی و ثبت سفارش
          </p>
        </div>
        <span className="text-2xl select-none">❓</span>
      </div>

      <div className="space-y-3">
        {FAQ_ITEMS.map((item, i) => {
          const isOpen = openIndex === i;
          return (
            <div
              key={i}
              className="border rounded-2xl p-4 cursor-pointer transition-colors"
              style={{
                borderColor: isOpen ? 'var(--accent)' : 'var(--border-color)',
                backgroundColor: isOpen ? 'var(--bg-secondary)' : 'transparent',
              }}
              onClick={() => toggle(i)}
            >
              <div className="flex items-center justify-between gap-3">
                <h4 className="text-xs sm:text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                  {item.question}
                </h4>
                <span
                  className="text-xs transition-transform duration-200 shrink-0"
                  style={{
                    color: 'var(--text-muted)',
                    transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                  }}
                >
                  ▼
                </span>
              </div>
              {isOpen && (
                <div className="mt-3 text-xs leading-relaxed border-t pt-3" style={{ color: 'var(--text-secondary)', borderColor: 'var(--border-color)' }}>
                  {item.answer}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function OrderProcessSection() {
  return (
    <section className="card p-6 sm:p-8 rounded-3xl border" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
      <div className="text-center max-w-lg mx-auto mb-8">
        <span className="text-xs font-bold px-3 py-1 rounded-full inline-block mb-2" style={{ backgroundColor: 'rgba(255, 154, 61, 0.15)', color: 'var(--brand-orange-deep)' }}>
          روند آسان و سریع
        </span>
        <h3 className="text-base sm:text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          مراحل سفارش چاپ سه بعدی در اسپاگتی پرینت
        </h3>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 sm:gap-6">
        <div className="flex flex-col items-center text-center p-4 rounded-2xl border" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
          <div className="w-12 h-12 rounded-2xl font-black text-lg flex items-center justify-center mb-3 shadow-md text-white" style={{ backgroundColor: 'var(--accent)' }}>
            ۱
          </div>
          <h4 className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>
            انتخاب یا ارسال طرح
          </h4>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            انتخاب از کاتالوگ یا ارسال فایل STL / عکس در صفحه سفارش طرح دلخواه.
          </p>
        </div>

        <div className="flex flex-col items-center text-center p-4 rounded-2xl border" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
          <div className="w-12 h-12 rounded-2xl font-black text-lg flex items-center justify-center mb-3 shadow-md text-white" style={{ backgroundColor: 'var(--brand-orange)' }}>
            ۲
          </div>
          <h4 className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>
            برآورد زمان و هزینه
          </h4>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            بررسی مدل، محاسبه دقیق زمان و وزن فیلامنت و انتخاب رنگ دلخواه.
          </p>
        </div>

        <div className="flex flex-col items-center text-center p-4 rounded-2xl border" style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }}>
          <div className="w-12 h-12 rounded-2xl font-black text-lg flex items-center justify-center mb-3 shadow-md text-white" style={{ backgroundColor: '#16a34a' }}>
            ۳
          </div>
          <h4 className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>
            چاپ دقیق و ارسال ایمن
          </h4>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            پرینت با دقت میکرونی، کنترل کیفیت نهایی و بستهبندی ضدضربه پستی.
          </p>
        </div>
      </div>
    </section>
  );
}

function BottomCtaSection() {
  return (
    <div
      className="rounded-3xl p-6 sm:p-8 text-white flex flex-col sm:flex-row items-center justify-between gap-6 shadow-xl"
      style={{ background: 'linear-gradient(135deg, #1e2540 0%, #9a3412 100%)' }}
    >
      <div className="space-y-1.5 text-center sm:text-right">
        <h4 className="text-base sm:text-lg font-bold">
          طرح خاصی در ذهن دارید که در کاتالوگ نیست؟
        </h4>
        <p className="text-xs opacity-90">
          فایل STL یا عکس مدل دلخواه را بفرستید تا با بالاترین کیفیت برایتان چاپ کنیم.
        </p>
      </div>
      <Link
        to="/custom-order"
        className="px-6 py-3 rounded-2xl text-white font-bold text-xs shadow-lg transition-all shrink-0 hover:opacity-90"
        style={{ backgroundColor: 'var(--brand-orange)' }}
      >
        استعلام قیمت و سفارش طرح دلخواه ←
      </Link>
    </div>
  );
}

function CatalogImageCarousel({ images, imageUrl, name, priority = false }) {
  const [current, setCurrent] = useState(0);
  const [touchStart, setTouchStart] = useState(null);
  const [touchEnd, setTouchEnd] = useState(null);

  const sorted = useMemo(() => {
    if (images && images.length > 0) {
      return [...images].sort((a, b) => {
        if (a.is_primary && !b.is_primary) return -1;
        if (!a.is_primary && b.is_primary) return 1;
        return (a.sort_order || 0) - (b.sort_order || 0);
      });
    }
    if (imageUrl) {
      return [{ image_url: imageUrl, is_primary: true }];
    }
    return [];
  }, [images, imageUrl]);

  const next = useCallback(() => setCurrent((c) => (c + 1) % sorted.length), [sorted.length]);
  const prev = useCallback(
    () => setCurrent((c) => (c - 1 + sorted.length) % sorted.length),
    [sorted.length]
  );

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

  if (sorted.length === 0) return null;

  if (sorted.length === 1) {
    return (
      <div className="w-full aspect-square overflow-hidden bg-[var(--bg-tertiary)] rounded-[1.25rem]">
        <img
          src={sorted[0].image_url}
          alt={name || ''}
          width={320}
          height={320}
          decoding="async"
          className="w-full h-full object-cover rounded-[1.25rem] transition-transform duration-700 ease-out group-hover:scale-110"
          loading={priority ? 'eager' : 'lazy'}
          fetchPriority={priority ? 'high' : 'auto'}
        />
      </div>
    );
  }

  return (
    <div
      className="relative w-full aspect-square overflow-hidden bg-[var(--bg-tertiary)] rounded-[1.25rem]"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      <img
        src={sorted[current].image_url}
        alt={name || ''}
        width={320}
        height={320}
        decoding="async"
        className="w-full h-full object-cover rounded-[1.25rem] transition-transform duration-700"
        loading={priority ? 'eager' : 'lazy'}
        fetchPriority={priority ? 'high' : 'auto'}
      />
      <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                prev();
              }}
              className="absolute left-2 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity z-[2]"
              aria-label="قبلی"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                next();
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity z-[2]"
              aria-label="بعدی"
            >
              <ChevronRight size={16} />
            </button>
            <div className="absolute bottom-2.5 left-1/2 -translate-x-1/2 flex items-center gap-1 z-[2]">
              {sorted.map((_, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setCurrent(i);
                  }}
                  className="p-2 flex items-center justify-center rounded-full transition-all focus:outline-none"
                  aria-label={`تصویر ${i + 1}`}
                >
                  <span
                    className="block rounded-full transition-all"
                    style={{
                      width: i === current ? 14 : 6,
                      height: 6,
                      backgroundColor: i === current ? '#475569' : 'rgba(100,116,139,0.5)',
                    }}
                  />
                </button>
              ))}
            </div>
    </div>
  );
}

function isWithinDays(isoDate, days = 14) {
  if (!isoDate) return false;
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return false;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  cutoff.setHours(0, 0, 0, 0);
  return date >= cutoff;
}

function telegramShareUrl(product) {
  const url = `${window.location.origin}/catalog/${product.slug}`;
  const text = `${displayName(product.name)}${product.product_id ? ` — کد: ${product.product_id}` : ''}`;
  return `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
}

function displayName(name) {
  if (!name || /^[?\s]+$/.test(name)) return 'بدون نام';
  return name;
}

/* ─── Collection/category theme ─── */
// Each collection gets a deterministic unique orange shade (site brand-orange family)
const BANNER_THEMES = [
  { from: '#ffb35c', to: '#b45309', accent: '#ffd9a8' },  // کهربایی
  { from: '#ff9a3d', to: '#9a3412', accent: '#ffcf96' },  // نارنجی برند
  { from: '#f59e0b', to: '#92400e', accent: '#ffe0b8' },  // کهربایی تیره
  { from: '#fb923c', to: '#c2410c', accent: '#ffd5ad' },  // نارنجی
  { from: '#fdba74', to: '#a34a14', accent: '#ffe4c4' },  // نارنجی روشن
  { from: '#f97316', to: '#7c2d12', accent: '#ffcc99' },  // نارنجی سوخته
];

function themeFor(key) {
  let h = 0;
  const s = String(key || '');
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return BANNER_THEMES[h % BANNER_THEMES.length];
}

/* ─── Collection card (one item of the auto-scroll marquee row) ─── */
function CollectionCard({ coll, activeTag, duplicate = false }) {
  const isActive = !duplicate && (activeTag === coll.slug || activeTag === coll.name);
  return (
    <Link
      to={isActive ? '/' : `/collection/${encodeURIComponent(coll.slug || coll.name)}`}
      tabIndex={duplicate ? -1 : undefined}
      aria-hidden={duplicate || undefined}
      inert={duplicate ? '' : undefined}
      className={`group catalog-product-card flex flex-col overflow-hidden transition-all shrink-0 w-40 sm:w-44 ${
        duplicate ? 'collection-card-dup' : ''
      } ${isActive ? 'ring-2 ring-accent border-accent' : ''}`}
    >
      <div className="relative aspect-square overflow-hidden rounded-[1.25rem]" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
        {coll.image_url ? (
          <img
            src={coll.image_url}
            alt={coll.name}
            width={320}
            height={320}
            loading="eager"
            decoding="async"
            className="w-full h-full object-cover rounded-[1.25rem] transition-transform duration-700 ease-out group-hover:scale-110"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center" style={{ backgroundColor: 'var(--bg-tertiary)' }}>
            <Package size={40} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
          </div>
        )}
        <div className="catalog-img-fade pointer-events-none" aria-hidden="true" />
        <div className="absolute top-2.5 inset-x-2.5 flex items-start justify-between gap-2 z-[1]">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ backgroundColor: 'var(--accent)', color: '#fff' }}>
            📦 {coll.product_count} محصول
          </span>
        </div>
      </div>
      <div className="p-3 flex-1 flex flex-col justify-center">
        <h3 className="font-bold text-sm leading-snug line-clamp-2" style={{ color: 'var(--text-primary)' }}>
          {coll.name}
        </h3>
      </div>
    </Link>
  );
}

const INITIAL_BATCH = 24;
const BATCH_SIZE = 24;

export function collectionBundlesForCategory(products) {
  const collectionsMap = new Map();
  const nonCollectionProducts = [];

  for (const product of products) {
    const collection = product.collections?.[0];
    if (!collection) {
      nonCollectionProducts.push(product);
      continue;
    }

    const collectionKey = collection.slug || collection.name;
    if (!collectionsMap.has(collectionKey)) {
      collectionsMap.set(collectionKey, { collection, items: [] });
    }
    collectionsMap.get(collectionKey).items.push(product);
  }

  const collectionCards = Array.from(collectionsMap.values()).map(({ collection, items }) => {
    const representative = items[0];
    return {
      ...representative,
      isCollectionBundle: true,
      collectionTag: collection.slug || collection.name,
      collectionCount: items.length,
      name: `${collection.name} (${items.length} آیتم)`,
      images: items.flatMap((item) => item.images || []),
    };
  });

  return [...collectionCards, ...nonCollectionProducts];
}

export default function Catalog() {
  const { tag: routeTag } = useParams();
  const [products, setProducts] = useState([]);
  const [collections, setCollections] = useState([]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState(() => {
    const cat = searchParams.get('category');
    return cat ? Number(cat) : null;
  });
  const [activeTag, setActiveTag] = useState(() => routeTag || searchParams.get('tag') || null);
  const [sortBy, setSortBy] = useState('name');
  const [visibleCount, setVisibleCount] = useState(INITIAL_BATCH);
  const loadMoreRef = useRef(null);

  // Products section wrapper — scroll target when a collection/category is selected
  const productsSectionRef = useRef(null);

  const clearFilters = useCallback(() => {
    setActiveCategory(null);
    setActiveTag(null);
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  // Reset visibleCount when filters change
  useEffect(() => {
    setVisibleCount(INITIAL_BATCH);
  }, [search, activeCategory, activeTag, sortBy]);

  // Scroll the page so the products start at the top whenever a filter becomes active
  useEffect(() => {
    if (loading) return;
    if (!activeCategory && !activeTag) return;
    const id = window.setTimeout(() => {
      productsSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
    return () => window.clearTimeout(id);
  }, [activeCategory, activeTag, loading]);

  // Sync activeCategory & activeTag when URL params change
  useEffect(() => {
    const cat = searchParams.get('category');
    let num = null;
    if (cat === 'uncategorized') num = 'uncategorized';
    else if (cat) num = Number(cat);
    const tag = routeTag || searchParams.get('tag');
    setActiveCategory((prev) => (prev === num ? prev : num));
    setActiveTag((prev) => (prev === tag ? prev : tag));
  }, [searchParams, routeTag]);

  // Toggle a category filter: clears any active tag and keeps the URL in sync,
  // so category + collection filters never silently stack into an empty result.
  const toggleCategory = useCallback(
    (id) => {
      const next = activeCategory === id ? null : id;
      setActiveCategory(next);
      setActiveTag(null);
      const params = new URLSearchParams(searchParams);
      if (next === null || next === undefined) params.delete('category');
      else params.set('category', String(next));
      params.delete('tag');
      setSearchParams(params, { replace: true });
    },
    [activeCategory, searchParams, setSearchParams]
  );

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [pRes, cRes, collRes] = await Promise.all([getCatalog(), getCatalogCategories(), getCatalogCollections()]);
        const pList = Array.isArray(pRes.data) ? pRes.data : [];
        const collList = Array.isArray(collRes.data) ? collRes.data : [];
        // /catalog/categories returns tree [{id, name, children: [...]}]
        // Flatten tree for filter chips with depth info
        const flattenTree = (nodes, depth = 0) => {
                  let result = [];
                  for (const n of nodes) {
                    result.push({ id: n.id, name: n.name, depth, parent_id: n.parent_id ?? null, description: n.description || '' });
                    if (n.children && n.children.length > 0) {
                      result = result.concat(flattenTree(n.children, depth + 1));
                    }
                  }
                  return result;
                };
                const treeData = Array.isArray(cRes.data) ? cRes.data : [];
                const catsList = flattenTree(treeData).map((c) => ({ id: c.id, name: c.name, depth: c.depth, parent_id: c.parent_id, count: null, description: c.description }));
        setProducts(pList);
        setCategories(catsList);
        setCollections(collList);
        setError(null);
      } catch (err) {
        if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
          console.error('Catalog load error:', err);
          setError('خطا در بارگذاری کاتالوگ');
        }
      } finally {
        setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, []);

  // Collections row: single line, slow auto-scroll loop, manually scrollable.
  // Auto-scroll pauses while hovering / interacting, resumes after idle.
  // Row is duplicated (two groups) so the loop rewinds seamlessly.
  const [collectionsScrollable, setCollectionsScrollable] = useState(false);
  const collectionsScrollerRef = useRef(null);
  useEffect(() => {
    const el = collectionsScrollerRef.current;
    if (!el) return;
    let raf = 0;
    let lastTs = 0;
    let paused = false;
    let idleTimer = null;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const overflows = () => el.scrollWidth > el.clientWidth + 1;

    // RTL scroll convention differs across engines: Chromium uses a NEGATIVE
    // scrollLeft domain for RTL (0 = right/start, -max = left/end), Firefox uses
    // positive. Detect once so the loop advances in the right direction.
    el.scrollLeft = 1000000;
    const negativeDomain = el.scrollLeft <= 0 && overflows();
    el.scrollLeft = 0;
    const advance = (step) => { el.scrollLeft += negativeDomain ? -step : step; };
    const atEnd = (max) => (negativeDomain ? el.scrollLeft <= -max + 1 : el.scrollLeft >= max - 1);
    const rewind = () => { el.scrollLeft += negativeDomain ? el.scrollWidth / 2 : -el.scrollWidth / 2; };

    const tick = (ts) => {
      if (paused) { raf = 0; return; }
      if (lastTs) {
        const dt = Math.min(ts - lastTs, 500); // time-based: consistent speed even if rAF is throttled
        advance((dt / 1000) * 25); // ~25px/s — slow loop
        const max = el.scrollWidth - el.clientWidth;
        if (atEnd(max)) rewind(); // seamless: second copy ≡ first
      }
      lastTs = ts;
      raf = requestAnimationFrame(tick);
    };

    const startLoop = () => {
      if (paused || raf || reducedMotion || !overflows()) return;
      lastTs = 0;
      raf = requestAnimationFrame(tick);
    };
    const stopLoop = () => { paused = true; if (raf) { cancelAnimationFrame(raf); raf = 0; } };
    const resumeSoon = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => { paused = false; startLoop(); }, 2500);
    };
    const pauseForIdle = () => { stopLoop(); resumeSoon(); };

    const update = () => {
      setCollectionsScrollable(overflows());
      if (overflows()) startLoop();
      else { stopLoop(); el.scrollLeft = 0; }
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);

    // Mouse wheel over the row scrolls it horizontally (instead of the page).
    // Chromium RTL scrollLeft is negative — direction handled via negativeDomain.
    const onWheel = (e) => {
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return; // horizontal wheel: let native scroll work
      if (e.deltaY === 0) return;
      const mult = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1;
      const delta = e.deltaY * mult;
      el.scrollLeft += negativeDomain ? -delta : delta;
      e.preventDefault(); // don't page-scroll while hovering the row
      stopLoop();
      resumeSoon();
    };

    el.addEventListener('mouseenter', stopLoop);
    el.addEventListener('mouseleave', resumeSoon);
    el.addEventListener('pointerdown', pauseForIdle);
    el.addEventListener('touchstart', pauseForIdle, { passive: true });
    el.addEventListener('touchend', resumeSoon);
    el.addEventListener('wheel', onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(idleTimer);
      ro.disconnect();
      el.removeEventListener('mouseenter', stopLoop);
      el.removeEventListener('mouseleave', resumeSoon);
      el.removeEventListener('pointerdown', pauseForIdle);
      el.removeEventListener('touchstart', pauseForIdle);
      el.removeEventListener('touchend', resumeSoon);
      el.removeEventListener('wheel', onWheel);
    };
  }, [collections]);

  // Collect all unique tags from products (tags is comma-separated string)
  const allTags = useMemo(() => {
    const tagSet = new Set();
    for (const p of products) {
      const raw = (p.tags || '').trim();
      if (!raw) continue;
      for (const t of raw.split(',').map((s) => s.trim()).filter(Boolean)) {
        tagSet.add(t);
      }
    }
    return Array.from(tagSet).sort((a, b) => a.localeCompare(b, 'fa'));
  }, [products]);

  const filtered = useMemo(() => {
    let list = [...products];

    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.name?.toLowerCase().includes(q) ||
          p.product_id?.toLowerCase().includes(q) ||
          p.category?.toLowerCase().includes(q) ||
          (p.categories || []).some((c) => c.name?.toLowerCase().includes(q)) ||
          p.material_name?.toLowerCase().includes(q) ||
          (p.tags || '').toLowerCase().split(',').map((s) => s.trim()).some((t) => t.includes(q))
      );
    }
    if (activeCategory) {
      if (activeCategory === 'uncategorized') {
        list = list.filter(
          (p) => (!p.categories || p.categories.length === 0) && (!p.category || p.category === '')
        );
      } else {
        // Build set of matching category IDs (selected + all descendants recursively)
        const matchingIds = new Set([activeCategory]);
        // Use the flat list which has parent_id to find all descendants
        let found = true;
        while (found) {
          found = false;
          categories.forEach((c) => {
            if (matchingIds.has(c.parent_id) && !matchingIds.has(c.id)) {
              matchingIds.add(c.id);
              found = true;
            }
          });
        }
        list = list.filter((p) => {
          if (p.categories && p.categories.length > 0) {
            return p.categories.some((c) => matchingIds.has(c.id));
          }
          if (p.category) {
            const matchedCat = categories.find((c) => c.id === activeCategory);
            return matchedCat ? p.category === matchedCat.name : false;
          }
          return false;
        });
      }
    }
    if (activeTag) {
      list = list.filter((p) => {
        const raw = (p.tags || '').trim();
        const tagMatch = raw ? raw.split(',').map((s) => s.trim()).includes(activeTag) : false;
        const collMatch = p.collections?.some((c) => c.name === activeTag || c.slug === activeTag);
        return tagMatch || collMatch;
      });
    }
    // Group after filtering so category/subcategory cards represent only matching products.
    if (!activeTag && !search) {
      list = collectionBundlesForCategory(list);
    }
    switch (sortBy) {
      case 'price_asc':
        list.sort((a, b) => (a.final_price || 0) - (b.final_price || 0));
        break;
      case 'price_desc':
        list.sort((a, b) => (b.final_price || 0) - (a.final_price || 0));
        break;
      case 'weight':
        list.sort((a, b) => (a.weight_g || 0) - (b.weight_g || 0));
        break;
      default:
        list.sort((a, b) => (a.name || '').localeCompare(b.name || '', 'fa'));
    }
    return list;
      }, [products, search, activeCategory, activeTag, sortBy]);

      // Active collection/category info for the themed banner above the products
      const bannerInfo = useMemo(() => {
        if (activeTag) {
          const coll = collections.find((c) => c.slug === activeTag || c.name === activeTag) || null;
          if (coll) {
            return {
              kind: 'کالکشن',
              title: coll.name,
              desc: coll.description || '',
              image: coll.image_url || null,
              themeKey: coll.slug || coll.name,
            };
          }
          return { kind: 'کالکشن', title: activeTag, desc: '', image: null, themeKey: activeTag };
        }
        if (activeCategory === 'uncategorized') {
          return { kind: 'دسته‌بندی', title: 'بدون دسته', desc: 'محصولاتی که در هیچ دسته‌ای قرار نگرفته‌اند', image: null, themeKey: 'uncategorized' };
        }
        if (activeCategory) {
          const cat = categories.find((c) => c.id === activeCategory) || null;
          if (cat) {
            return { kind: 'دسته‌بندی', title: cat.name, desc: cat.description || '', image: null, themeKey: cat.name || String(cat.id) };
          }
          return { kind: 'دسته‌بندی', title: String(activeCategory), desc: '', image: null, themeKey: String(activeCategory) };
        }
        return null;
      }, [activeTag, activeCategory, collections, categories]);

      const bannerTheme = bannerInfo ? themeFor(bannerInfo.themeKey) : null;

  const seoTitle = bannerInfo
    ? `${bannerInfo.title} (${bannerInfo.kind}) — خرید و سفارش آنلاین`
    : 'خدمات پرینت سه بعدی و کاتالوگ محصولات';

  const seoDesc =
    bannerInfo?.desc ||
    (bannerInfo
      ? `مشاهده و خرید آنلاین انواع محصولات ${bannerInfo.title} با تکنولوژی پرینت سه بعدی و قیمت شفاف در اسپاگتی پرینت.`
      : 'اسپاگتی پرینت — خدمات آنلاین پرینت و چاپ سه بعدی سفارشی، ساخت قطعات و نمونه اولیه، کاتالوگ محصولات با قیمت شفاف');

  const jsonLd = useMemo(() => {
    return [
      buildWebSiteJsonLd(),
      buildOrganizationJsonLd(),
      buildFaqJsonLd(FAQ_ITEMS),
    ].filter(Boolean);
  }, []);

  useSEO({
    title: seoTitle,
    description: seoDesc,
    url: routeTag ? `/collection/${encodeURIComponent(routeTag)}` : '/',
    jsonLd,
  });

  return (
    <div className="space-y-7 sm:space-y-9 animate-fade-in">
      {/* Desktop: photo + overlay copy · Mobile: stacked media + panel */}
      <div className="catalog-hero-row">
        <section className="catalog-hero catalog-hero--main overflow-hidden rounded-[1.35rem]">
              <div className="catalog-hero-media">
                <img
                  src="/catalog-hero.webp?v=2"
                  alt=""
                  className="catalog-hero-photo"
                  width={1024}
                  height={572}
                  decoding="async"
                  fetchPriority="high"
                />
                <div className="catalog-hero-scrim" aria-hidden="true" />
              </div>

              <div className="catalog-hero-copy">
                <h1
                  className="catalog-hero-title text-2xl sm:text-3xl lg:text-4xl font-bold mb-2.5 tracking-tight leading-[1.15]"
                  style={{ color: 'var(--text-primary)' }}
                >
                  خدمات پرینت سه بعدی و کاتالوگ محصولات
                </h1>
                <p className="text-xs sm:text-sm opacity-90 mt-1 max-w-xl" style={{ color: 'var(--text-secondary)' }}>
                  سفارش آنلاین قطعات سفارشی با عکس یا STL + شخصیسازی کامل رنگ و ابعاد محصولات کاتالوگ
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="catalog-stat-pill catalog-stat-pill-on-photo">
                    {loading ? 'پرینت آنلاین سه بعدی' : `${products.length} محصول`}
                  </span>
                  {!loading && categories.length > 0 && (
                    <span className="catalog-stat-pill catalog-stat-pill-on-photo">
                      {categories.length} دستهبندی
                    </span>
                  )}
                </div>
              </div>
        </section>

        <Link
          to="/custom-order"
          className="catalog-hero-cta overflow-hidden rounded-[1.35rem]"
        >
          <div className="catalog-hero-cta-inner">
            <span className="catalog-hero-cta-title">طرح دلخواهتو پرینت کن</span>
            <span className="catalog-hero-cta-arrow">←</span>
          </div>
        </Link>
      </div>

      {/* Trust Badges Strip (Hero Benefits) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div className="card p-3 sm:p-3.5 flex items-center gap-3 rounded-2xl border transition-all hover:border-accent" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center text-base sm:text-lg shrink-0" style={{ backgroundColor: 'rgba(255, 154, 61, 0.15)', color: 'var(--brand-orange-deep)' }}>✨</div>
          <div className="min-w-0">
            <h3 className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>متریال درجه یک PLA</h3>
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>زیستسازگار و بدون بو</p>
          </div>
        </div>

        <div className="card p-3 sm:p-3.5 flex items-center gap-3 rounded-2xl border transition-all hover:border-accent" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center text-base sm:text-lg shrink-0" style={{ backgroundColor: 'rgba(99, 102, 241, 0.12)', color: 'var(--accent)' }}>🎨</div>
          <div className="min-w-0">
            <h3 className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>شخصیسازی نامحدود</h3>
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>انتخاب رنگ، ابعاد و متن</p>
          </div>
        </div>

        <div className="card p-3 sm:p-3.5 flex items-center gap-3 rounded-2xl border transition-all hover:border-accent" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center text-base sm:text-lg shrink-0" style={{ backgroundColor: 'rgba(34, 197, 94, 0.15)', color: '#16a34a' }}>⚡</div>
          <div className="min-w-0">
            <h3 className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>قیمت شفاف و فوری</h3>
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>برآورد بر اساس وزن قطعه</p>
          </div>
        </div>

        <div className="card p-3 sm:p-3.5 flex items-center gap-3 rounded-2xl border transition-all hover:border-accent" style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center text-base sm:text-lg shrink-0" style={{ backgroundColor: 'rgba(245, 158, 11, 0.15)', color: '#d97706' }}>📦</div>
          <div className="min-w-0">
            <h3 className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>بستهبندی ضدضربه</h3>
            <p className="text-[11px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>ارسال ایمن به سراسر کشور</p>
          </div>
        </div>
      </div>

      {/* Sticky-ish toolbar */}
      <div className="catalog-toolbar flex flex-col gap-3 sm:gap-4">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1 relative">
            <Search
              size={16}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none"
              style={{ color: 'var(--text-muted)' }}
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="جستجو نام، کد، ماده یا دسته..."
              className="input-field catalog-search pr-10 text-sm"
              aria-label="جستجوی محصولات"
            />
          </div>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="select-field w-full sm:w-auto min-w-[160px]"
            aria-label="مرتبسازی محصولات"
          >
            <option value="name">مرتبسازی: نام</option>
            <option value="price_asc">قیمت ↑</option>
            <option value="price_desc">قیمت ↓</option>
            <option value="weight">وزن</option>
          </select>
        </div>

        {loading ? (
          <div className="flex gap-2 overflow-x-auto pb-0.5 -mx-1 px-1">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-8 w-20 rounded-full skeleton-pulse shrink-0" />
            ))}
          </div>
        ) : categories.length > 0 && (
          <div
            className="flex gap-2 overflow-x-auto pb-0.5 -mx-1 px-1 catalog-filter-row"
            style={{ WebkitOverflowScrolling: 'touch' }}
          >
            <button
              type="button"
              onClick={clearFilters}
              className={`catalog-chip ${!activeCategory && !activeTag ? 'catalog-chip-active' : ''}`}
            >
              همه ({products.length})
            </button>
            {/* All categories incl. subcategories — same bubble style; flat list is in
                tree order (parent first, then its children) so chips read naturally */}
            {categories.map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => toggleCategory(cat.id)}
                className={`catalog-chip ${activeCategory === cat.id ? 'catalog-chip-active' : ''}`}
              >
                {cat.name}
              </button>
            ))}
            {categories.length > 0 && (
              <button
                type="button"
                onClick={() => toggleCategory('uncategorized')}
                className={`catalog-chip ${activeCategory === 'uncategorized' ? 'catalog-chip-active' : ''}`}
              >
                بدون دسته
              </button>
            )}
          </div>
        )}

        {collections.length > 0 && (
          <div className="flex flex-col gap-3">
            <h2 className="text-sm font-bold flex items-center gap-1.5" style={{ color: '#ffffff' }}>
              <span>📦 کالکشنها / مجموعهها</span>
            </h2>
            {/* One row: slow auto-scroll loop, pauses on hover/interaction, and the
                user can always scroll it manually (wheel / drag / scrollbar / touch). */}
            <div
              ref={collectionsScrollerRef}
              className={`catalog-collections-scroller${collectionsScrollable ? ' is-scrollable' : ''}`}
            >
              <div className="catalog-collections-track">
                {collections.map((coll) => (
                  <CollectionCard key={coll.id} coll={coll} activeTag={activeTag} />
                ))}
                {collections.map((coll) => (
                  <CollectionCard key={`dup-${coll.id}`} coll={coll} activeTag={activeTag} duplicate />
                ))}
              </div>
            </div>
          </div>
        )}

        {!bannerInfo && (
          <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
            {loading ? 'در حال بارگذاری...' : `${filtered.length} نتیجه`}
          </div>
        )}
      </div>

      {/* Products grid sits on one solid themed panel — unique orange shade per collection.
          Folder-style tab with the collection name is attached to the panel's top edge. */}
      <div
        ref={productsSectionRef}
        className={`catalog-products-anchor${bannerInfo && bannerTheme ? ' collection-panel-wrap' : ''}`}
      >
        <h2 className="sr-only">محصولات کاتالوگ</h2>
        {bannerInfo && bannerTheme && (
          <div
            className="collection-panel-tab"
            style={{ background: bannerTheme.from }}
          >
            <span className="collection-panel-tab-name">{bannerInfo.title}</span>
            <span className="collection-panel-tab-count">{filtered.length} محصول</span>
          </div>
        )}
        <div
          className={bannerInfo && bannerTheme ? 'collection-solid-panel' : ''}
          style={
            bannerInfo && bannerTheme
              ? { background: bannerTheme.to, '--banner-accent': bannerTheme.accent }
              : undefined
          }
        >
      {error ? (
        <div className="catalog-product-card p-12 sm:p-16 text-center">
          <div className="text-sm font-semibold" style={{ color: '#ef4444' }}>{error}</div>
        </div>
      ) : loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-5">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <article key={i} className="catalog-product-card flex flex-col relative overflow-hidden">
              <div className="w-full aspect-square skeleton-pulse" style={{ background: 'var(--bg-tertiary)', borderRadius: '1.25rem' }} />
              <div className="p-4 flex-1 flex flex-col gap-2.5">
                <div className="h-5 w-3/4 skeleton-pulse rounded" />
                <div className="h-3 w-1/2 skeleton-pulse rounded" />
                <div className="mt-auto pt-3 border-t flex justify-between items-center" style={{ borderColor: 'var(--border-color)' }}>
                  <div className="h-5 w-20 skeleton-pulse rounded" />
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="catalog-product-card p-12 sm:p-16 text-center">
          <div
            className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
            style={{ background: 'var(--accent-light)' }}
          >
            <Package size={28} style={{ color: 'var(--accent)', opacity: 0.85 }} />
          </div>
          <p className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>
            محصولی یافت نشد
          </p>
          <p className="text-xs mb-4" style={{ color: 'var(--text-muted)' }}>
            فیلترها یا عبارت جستجو را بررسی کنید. شاید دستهبندی یا نام دیگری مد نظرتان باشد.
          </p>
          <Link
            to="/contact"
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            تماس با ما
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-5">
          {filtered.slice(0, visibleCount).map((product, idx) => {
            const price = product.final_price;
            const isNew = isWithinDays(product.created_at, 14);
            const shareUrl = telegramShareUrl(product);
            const isBundle = product.isCollectionBundle;
            const cardLink = isBundle ? `/collection/${encodeURIComponent(product.collectionTag)}` : `/catalog/${product.slug}`;

            return (
              <article
                key={isBundle ? `bundle-${product.collectionTag}` : product.id}
                className="catalog-product-card group flex flex-col relative"
                style={{ animationDelay: `${Math.min(idx, 12) * 40}ms` }}
              >
                <Link
                  to={cardLink}
                  className="flex-1 flex flex-col focus:outline-none focus-visible:ring-2 focus-visible:ring-inset"
                  style={{ '--tw-ring-color': 'var(--accent)' }}
                  aria-label={`مشاهده ${displayName(product.name)}`}
                >
                  <div
                    className="relative overflow-hidden"
                    style={{ background: 'var(--bg-tertiary)' }}
                  >
                    {product.images?.length > 0 || product.image_url ? (
                      <CatalogImageCarousel images={product.images} imageUrl={product.image_url} name={product.name} priority={idx < 2} />
                    ) : (
                      <div className="w-full aspect-square flex flex-col items-center justify-center gap-2 catalog-img-placeholder">
                        <Package size={32} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>بدون تصویر</span>
                      </div>
                    )}

                    {/* bottom gradient on image */}
                    <div className="catalog-img-fade pointer-events-none" aria-hidden="true" />

                    <div className="absolute top-2.5 inset-x-2.5 flex items-start justify-between gap-2 pointer-events-none z-[1]">
                      {product.product_id ? (
                        <span className="catalog-code-badge">{product.product_id}</span>
                      ) : (
                        <span />
                      )}
                      <div className="flex items-center gap-1.5 flex-wrap justify-end">
                        {isNew && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
                            style={{ background: '#22c55e', color: '#fff' }}
                          >
                            جدید
                          </span>
                        )}
                        {(product.categories || []).map((c) => (
                          <span key={c.id} className="catalog-cat-badge">{c.name}</span>
                        ))}
                        {/* Collection Badge */}
                        {product.tags && (() => {
                          const rawTags = (product.tags || '').split(',').map((t) => t.trim()).filter(Boolean);
                          const collTag = rawTags.find((t) => t.includes('کالکشن') || t.includes('مجموعه') || t.includes('بافتنی') || t.includes('فلکسی'));
                          return collTag ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-accent/20 text-accent border border-accent/30">
                              📦 {collTag}
                            </span>
                          ) : null;
                        })()}
                      </div>
                    </div>
                  </div>

                  <div className="p-4 flex-1 flex flex-col gap-2.5">
                    <h3
                      className="font-bold text-[15px] leading-snug line-clamp-2 tracking-tight"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {displayName(product.name)}
                    </h3>

                    <div
                      className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {product.material_name && (
                        <span className="inline-flex items-center gap-1">
                          <Layers size={11} className="opacity-70" />
                          <span
                            className="inline-block rounded-full"
                            style={{
                              width: 8,
                              height: 8,
                              backgroundColor: product.material_color || '#94a3b8',
                            }}
                            aria-hidden="true"
                          />
                          {product.material_name}
                        </span>
                      )}
                      {product.weight_g > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Weight size={11} className="opacity-70" /> {product.weight_g}g
                        </span>
                      )}
                      {(product.dimension_x || product.dimension_y || product.dimension_z) ? (() => {
                        // Sort longest -> shortest for natural reading (L × W × H). Convert mm → cm.
                        const dims = [product.dimension_x, product.dimension_y, product.dimension_z]
                          .map((d) => (d / 10).toFixed(1))
                          .sort((a, b) => b - a);
                        return (
                          <span className="inline-flex items-center gap-1">
                            <Ruler size={11} className="opacity-70" />{' '}
                            {dims[0]} × {dims[1]} × {dims[2]} سانتی‌متر
                          </span>
                        );
                      })() : null}
                    </div>

                    <div
                      className="pt-3 mt-auto border-t flex items-end justify-between gap-2"
                      style={{ borderColor: 'var(--border-color)' }}
                    >
                      {isBundle ? (
                        <div>
                          <div
                            className="text-[10px] uppercase tracking-wide mb-0.5"
                            style={{ color: 'var(--text-muted)' }}
                          >
                            مجموعه کامل
                          </div>
                          <span className="catalog-price text-sm font-bold text-accent">
                            مشاهده {product.collectionCount} آیتم ←
                          </span>
                        </div>
                      ) : price ? (
                        <div>
                          <div
                            className="text-[10px] uppercase tracking-wide mb-0.5"
                            style={{ color: 'var(--text-muted)' }}
                          >
                            {product.final_price ? 'قیمت' : 'قیمت'}
                          </div>
                          <span className="catalog-price text-lg font-bold tabular-nums">
                            {formatPrice(price)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          قیمت تماس بگیرید
                        </span>
                      )}
                    </div>
                  </div>
                </Link>

                {/* Telegram share — sits in the bottom-left corner next to the price, outside the Link to avoid nesting */}
                <a
                  href={shareUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="absolute bottom-4 left-4 z-[2] p-2 rounded-full bg-[var(--bg-secondary)] hover:bg-[#2AABEE] text-[var(--text-secondary)] hover:text-white transition-colors border border-[var(--border-color)] shadow-sm"
                  aria-label="اشتراک در تلگرام"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Send size={13} />
                </a>
              </article>
            );
          })}
        </div>
      )}

      {/* Option A: Controlled Click-to-Load More */}
      {!loading && visibleCount < filtered.length && (
        <div className="py-8 flex flex-col items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => setVisibleCount((c) => Math.min(c + BATCH_SIZE, filtered.length))}
            className="px-6 py-3 rounded-2xl text-xs font-bold transition-all border shadow-sm hover:scale-[1.02] flex items-center gap-2"
            style={{
              backgroundColor: 'var(--bg-card)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <span>نمایش ۲۴ محصول بیشتر</span>
            <span style={{ color: 'var(--text-muted)' }}>({filtered.length - visibleCount} محصول باقیمانده)</span>
            <span>↓</span>
          </button>
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            برای مشاهده راهنما و سؤالات متداول، ادامه صفحه را ببینید
          </span>
        </div>
      )}
        </div>
      </div>

      {/* Ordering Guide, FAQ, and CTA Sections (Main Homepage) */}
      {!activeTag && !activeCategory && !search && (
        <div className="space-y-8 mt-10 sm:mt-14">
          <OrderProcessSection />
          <FaqSection />
          <BottomCtaSection />
        </div>
      )}
    </div>
  );
}
