import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Package,
  Layers,
  Cog,
  Calculator,
  Store,
  ArrowUpLeft,
  ClipboardList,
  TrendingUp,
  Printer,
  Boxes,
  Inbox,
  BarChart3,
  Wallet,
  ShoppingBag,
  Eye,
  CalendarDays,
} from 'lucide-react';
import { getStats, getProducts, getSettings } from '../lib/api';
import { formatPrice } from '../lib/utils';

const QUICK_ACTIONS = [
  {
    path: '/products',
    title: 'محصول جدید',
    subtitle: 'وزن · زمان · قیمت پیشنهادی',
    icon: Package,
    tint: 'rgba(99, 102, 241, 0.13)',
    color: '#6366f1',
  },
  {
    path: '/materials',
    title: 'ماده جدید',
    subtitle: 'قیمت هر کیلو · ضایعات',
    icon: Layers,
    tint: 'rgba(8, 145, 178, 0.13)',
    color: '#0891b2',
  },
  {
    path: '/machines',
    title: 'ماشین جدید',
    subtitle: 'ولت · عمر · نگهداری',
    icon: Cog,
    tint: 'rgba(217, 119, 6, 0.13)',
    color: '#d97706',
  },
  {
    path: '/calculator',
    title: 'ماشین حساب',
    subtitle: 'محاسبه سریع بدون ذخیره',
    icon: Calculator,
    tint: 'rgba(22, 163, 74, 0.13)',
    color: '#16a34a',
  },
];

function KpiCard({ label, value, hint, icon: Icon }) {
  return (
    <div className="card p-5 flex flex-col gap-2 min-h-[118px]">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
          {label}
        </span>
        {Icon ? (
          <span
            className="w-9 h-9 rounded-xl shrink-0 flex items-center justify-center"
            style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}
          >
            <Icon size={17} />
          </span>
        ) : null}
      </div>
      <span
        className="text-3xl font-bold tracking-tight leading-none"
        style={{ color: 'var(--text-primary)' }}
      >
        {value}
      </span>
      {hint ? (
        <span className="text-xs mt-auto flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
          <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: 'var(--accent)' }} />
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function EmptyState({ icon: Icon, text = 'هنوز داده‌ای نیست', sub }) {
  return (
    <div className="py-6 flex flex-col items-center gap-2 text-center">
      <span
        className="w-10 h-10 rounded-xl flex items-center justify-center"
        style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}
      >
        <Icon size={18} />
      </span>
      <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{text}</p>
      {sub ? <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{sub}</p> : null}
    </div>
  );
}

function StatusBadge({ active }) {
  if (active) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: '#16a34a' }}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: '#22c55e' }} />
        فعال
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold"
      style={{ backgroundColor: 'rgba(245, 158, 11, 0.16)', color: '#b45309' }}
    >
      پیش‌نویس
    </span>
  );
}

const numberFormat = new Intl.NumberFormat('fa-IR');
const persianDate = (val) =>
  new Date(`${val}T12:00:00`).toLocaleDateString('fa-IR', { month: 'short', day: 'numeric' });

function SiteAnalyticsSection({ stats }) {
  const [period, setPeriod] = useState('daily');
  const points = (period === 'daily' ? stats?.site_views_daily : stats?.site_views_weekly) || [];
  const max = Math.max(...points.map((p) => p.views), 1);
  const labels =
    period === 'daily'
      ? points.map((p) => persianDate(p.date))
      : points.map((p) => `هفته ${persianDate(p.week_start)}`);
  const topContent = stats?.site_top_content || [];

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-0.5">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: '#ffffff' }}>
            <Eye size={16} style={{ color: 'var(--accent)' }} />
            بازدید سایت (عمومی)
          </h3>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            ثبت بدون اطلاعات هویتی و کوکی · محاسبه بر اساس منطقه زمانی تهران
          </p>
        </div>
        <div
          className="flex p-1 rounded-xl self-start sm:self-auto"
          style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}
        >
          <button
            type="button"
            onClick={() => setPeriod('daily')}
            className="px-3 py-1 text-xs rounded-lg font-medium transition-colors"
            style={{
              backgroundColor: period === 'daily' ? 'var(--accent)' : 'transparent',
              color: period === 'daily' ? '#000000' : 'var(--text-secondary)',
              fontWeight: period === 'daily' ? '700' : '500',
            }}
          >
            روزانه (۷ روز)
          </button>
          <button
            type="button"
            onClick={() => setPeriod('weekly')}
            className="px-3 py-1 text-xs rounded-lg font-medium transition-colors"
            style={{
              backgroundColor: period === 'weekly' ? 'var(--accent)' : 'transparent',
              color: period === 'weekly' ? '#000000' : 'var(--text-secondary)',
              fontWeight: period === 'weekly' ? '700' : '500',
            }}
          >
            هفتگی (۸ هفته)
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KpiCard
          label="بازدید امروز"
          value={numberFormat.format(stats?.site_views_today ?? 0)}
          hint="از ساعت ۰۰:۰۰ به وقت تهران"
          icon={Eye}
        />
        <KpiCard
          label="بازدید این هفته"
          value={numberFormat.format(stats?.site_views_week ?? 0)}
          hint="از ابتدای هفته جاری"
          icon={CalendarDays}
        />
        <KpiCard
          label="کل بازدیدهای ثبت‌شده"
          value={numberFormat.format(stats?.site_views_total ?? 0)}
          hint="از زمان فعال‌سازی قابلیت"
          icon={BarChart3}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Chart */}
        <section className="lg:col-span-8 card p-5 flex flex-col justify-between gap-4">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
              {period === 'daily' ? 'روند بازدید روزانه' : 'روند بازدید هفتگی'}
            </h4>
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              بیشترین: {numberFormat.format(Math.max(...points.map((p) => p.views), 0))} بازدید
            </span>
          </div>

          <div className="space-y-2">
            <div
              className="h-40 flex items-end gap-2 pt-6 pb-1 border-b"
              style={{ borderColor: 'var(--border-color)' }}
              dir="ltr"
            >
              {points.map((pt, idx) => (
                <div key={idx} className="h-full flex-1 flex flex-col justify-end group relative items-center">
                  <div
                    className="w-full max-w-[40px] rounded-t transition-all"
                    style={{
                      height: `${Math.max((pt.views / max) * 100, 4)}%`,
                      backgroundColor: pt.views > 0 ? 'var(--accent)' : 'var(--bg-tertiary)',
                      opacity: pt.views > 0 ? 0.9 : 0.4,
                    }}
                    title={`${labels[idx]}: ${numberFormat.format(pt.views)} بازدید`}
                  />
                  <span
                    className="absolute -top-6 opacity-0 group-hover:opacity-100 transition-opacity text-[10px] px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap z-10 font-bold"
                    style={{
                      backgroundColor: 'var(--bg-tertiary)',
                      color: 'var(--text-primary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    {numberFormat.format(pt.views)}
                  </span>
                </div>
              ))}
            </div>
            <div
              className="grid text-[10px]"
              style={{ gridTemplateColumns: `repeat(${Math.max(labels.length, 1)}, minmax(0, 1fr))` }}
              dir="ltr"
            >
              {labels.map((lbl, i) => (
                <span key={i} className="truncate text-center" style={{ color: 'var(--text-muted)' }} title={lbl}>
                  {lbl}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Top Content */}
        <section className="lg:col-span-4 card p-5 flex flex-col justify-between gap-3">
          <div>
            <h4 className="text-xs font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>
              پربازدیدترین صفحات و محصولات
            </h4>
            {topContent.length === 0 ? (
              <EmptyState icon={Eye} text="هنوز بازدیدی ثبت نشده است" sub="بازدیدهای جدید به مرور اضافه می‌شوند" />
            ) : (
              <div className="space-y-2">
                {topContent.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-xl flex items-center justify-between gap-2 text-xs"
                    style={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold truncate" dir="ltr" style={{ color: 'var(--text-primary)' }}>
                        {item.path}
                      </p>
                      <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                        {item.content_type === 'product'
                          ? 'محصول'
                          : item.content_type === 'home'
                          ? 'صفحه اصلی'
                          : item.content_type === 'blog'
                          ? 'وبلاگ'
                          : 'صفحه'}
                      </p>
                    </div>
                    <span className="shrink-0 font-bold text-xs" style={{ color: 'var(--accent)' }}>
                      {numberFormat.format(item.views)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [markup, setMarkup] = useState(3);
  const [recentProducts, setRecentProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const fetchAll = async () => {
      try {
        const [statsRes, productsRes, settingsRes] = await Promise.all([
          getStats({ signal: controller.signal }),
          getProducts(
            { sort: 'created_at', order: 'desc', limit: 8 },
            { signal: controller.signal }
          ),
          getSettings({ signal: controller.signal }).catch(() => null),
        ]);
        setStats(statsRes.data);
        setRecentProducts(
          Array.isArray(productsRes.data)
            ? productsRes.data
            : productsRes.data?.items || productsRes.data?.products || []
        );
        const settingsData = settingsRes?.data;
        // API: { default_markup_pct: { value, description, id, string_value }, ... }
        const raw =
          settingsData?.default_markup_pct?.value ??
          settingsData?.default_markup_pct ??
          null;
        if (raw != null) setMarkup(Number(raw) || 3);
        setError(null);
      } catch (err) {
        if (err?.name !== 'CanceledError' && err?.code !== 'ERR_CANCELED') {
          console.error('Dashboard load error:', err);
          setError('خطا در بارگذاری داشبورد');
        }
      } finally {
        setLoading(false);
      }
    };
    fetchAll();
    return () => controller.abort();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="skeleton-pulse h-8 w-32 rounded" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card p-5 space-y-3">
              <div className="skeleton-pulse h-3 w-20 rounded" />
              <div className="skeleton-pulse h-8 w-16 rounded" />
              <div className="skeleton-pulse h-3 w-24 rounded" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
          <div className="xl:col-span-4 card p-5 h-72 skeleton-pulse" />
          <div className="xl:col-span-8 card p-5 h-72 skeleton-pulse" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
      </div>
    );
  }

  const markupLabel = `x${Number(markup).toFixed(1).replace(/\\.0$/, '')}`;
  // Backend /products ignores the limit param — cap client-side so the
  // dashboard shows a summary, not the full catalog
  const recent = recentProducts.slice(0, 8);

  return (
    <div className="space-y-6">
      {/* Page title — mock: large داشبورد on the right (RTL start) */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl lg:text-[26px] font-bold tracking-tight" style={{ color: '#ffffff' }}>
          داشبورد
        </h2>
      </div>

      {/* KPI row — catalog / pricing */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="میانگین ضریب"
          value={markupLabel}
          hint="هدف ۳.۲"
          icon={TrendingUp}
        />
        <KpiCard
          label="ماشین‌ها"
          value={stats?.total_machines ?? 0}
          hint="همه آنلاین"
          icon={Printer}
        />
        <KpiCard
          label="مواد اولیه"
          value={stats?.total_materials ?? 0}
          hint={`${stats?.total_materials ?? 0} نوع فعال`}
          icon={Boxes}
        />
        <KpiCard
          label="محصولات فعال"
          value={stats?.active_products ?? stats?.total_products ?? 0}
          hint={`${stats?.total_products ?? 0} کل`}
          icon={Package}
        />
      </div>

      {/* Site view analytics (daily/weekly) */}
      <SiteAnalyticsSection stats={stats} />

      {/* Shop ops this month — board B, not accounting */}
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3 px-0.5">
          <h3 className="text-sm font-semibold" style={{ color: '#ffffff' }}>
            سفارش‌ها
          </h3>
          <button
            type="button"
            onClick={() => navigate('/orders')}
            className="text-xs font-medium px-3 py-1.5 rounded-lg flex items-center gap-1"
            style={{
              backgroundColor: 'var(--bg-tertiary)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
            }}
          >
            <ClipboardList size={14} />
            تابلو سفارش‌ها
            <ArrowUpLeft size={14} />
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard
            label="تعداد سفارش"
            value={stats?.orders_this_month ?? 0}
            hint="بدون لغو · همین ماه"
            icon={ShoppingBag}
          />
          <KpiCard
            label="دریافتی"
            value={formatPrice(stats?.orders_paid_this_month ?? 0)}
            hint="جمع مبلغ پرداخت‌شده"
            icon={Wallet}
          />
          <KpiCard
            label="مبلغ کل (نقل‌قول)"
            value={formatPrice(stats?.orders_quoted_this_month ?? 0)}
            hint="جمع قیمت اعلام‌شده"
            icon={BarChart3}
          />
          <KpiCard
            label="باز · در جریان"
            value={stats?.orders_open ?? 0}
            icon={ClipboardList}
            hint={
              stats?.orders_remaining_this_month != null
                ? `مانده ماه: ${formatPrice(stats.orders_remaining_this_month)}`
                : 'جدید تا آماده‌تحویل'
            }
          />
        </div>
      </div>

      {/* Insights — top selling, most viewed, revenue, status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top selling */}
        <section className="card p-5">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>پرفروش‌ترین محصولات</h3>
          {stats?.top_selling_products?.length ? (
            <div className="space-y-2">
              {stats.top_selling_products.map((p, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2 min-w-0 truncate" style={{ color: 'var(--text-secondary)' }}>
                    <span className="text-xs font-bold w-5 text-center" style={{ color: 'var(--accent)' }}>{i + 1}</span>
                    <span className="truncate">{p.name}</span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {p.orders} سفارش · {formatPrice(p.total)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={ShoppingBag} sub="بعد از ثبت اولین سفارش، پرفروش‌ترین‌ها اینجا نمایش داده می‌شوند" />
          )}
        </section>

        {/* Most viewed */}
        <section className="card p-5">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>پربازدیدترین محصولات</h3>
          {stats?.most_viewed_products?.length ? (
            <div className="space-y-2">
              {stats.most_viewed_products.map((p, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2 min-w-0 truncate" style={{ color: 'var(--text-secondary)' }}>
                    <span className="text-xs font-bold w-5 text-center" style={{ color: 'var(--accent)' }}>{i + 1}</span>
                    <span className="truncate">{p.name}</span>
                  </span>
                  <span className="shrink-0 text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{p.views} بازدید</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={Eye} sub="بازدید هر محصول پس از انتشار در کاتالوگ شمارش می‌شود" />
          )}
        </section>
      </div>

      {/* Orders by status + revenue */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="card p-5">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>سفارش‌ها بر اساس وضعیت</h3>
          {Object.entries(stats?.orders_by_status || {}).length === 0 ? (
            <EmptyState icon={Inbox} sub="وضعیت سفارش‌های این ماه اینجا نمایش داده می‌شود" />
          ) : (
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats?.orders_by_status || {}).map(([status, count]) => {
              const labels = { new: 'جدید', quoted: 'قیمت‌داده‌شده', printing: 'در حال چاپ', ready: 'آماده', delivered: 'تحویل‌شده', cancelled: 'لغو' };
              const colors = { new: '#6366f1', quoted: '#0891b2', printing: '#d97706', ready: '#16a34a', delivered: '#64748b', cancelled: '#ef4444' };
              return (
                <div key={status} className="px-3 py-2 rounded-xl border flex items-center gap-2" style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}>
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colors[status] || '#94a3b8' }} />
                  <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{labels[status] || status}</span>
                  <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{count}</span>
                </div>
              );
            })}
          </div>
          )}
        </section>

        <section className="card p-5">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-primary)' }}>درآمد ماهانه</h3>
          {stats?.revenue_by_month?.length ? (
            <div className="space-y-2">
              {stats.revenue_by_month.map((m, i) => (
                <div key={i} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
                    {m.year} / {m.month}
                  </span>
                  <span className="text-xs font-bold" style={{ color: 'var(--accent)' }}>{formatPrice(m.total)}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={BarChart3} sub="درآمد ماهانه پس از ثبت سفارش‌ها محاسبه می‌شود" />
          )}
        </section>
      </div>

      {/* Quick actions + recent products */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        {/* Quick actions — mock left panel */}
        <section className="xl:col-span-4 card p-5 flex flex-col gap-4">
          <div>
            <h3 className="font-semibold text-base" style={{ color: 'var(--text-primary)' }}>
              اقدام سریع
            </h3>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              افزودن موجودیت جدید
            </p>
          </div>

          <div className="flex flex-col gap-2">
            {QUICK_ACTIONS.map((item) => (
              <button
                key={item.path}
                type="button"
                onClick={() => navigate(item.path)}
                className="flex items-center gap-3 w-full text-right px-3 py-3 rounded-xl transition-colors"
                style={{
                  backgroundColor: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent) 45%, transparent)';
                  e.currentTarget.style.backgroundColor = 'var(--accent-light)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-color)';
                  e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)';
                }}
              >
                <div
                  className="w-10 h-10 rounded-xl shrink-0 flex items-center justify-center"
                  style={{ backgroundColor: item.tint, color: item.color }}
                >
                  <item.icon size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {item.title}
                  </div>
                  <div className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                    {item.subtitle}
                  </div>
                </div>
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn-primary w-full justify-center mt-1"
            onClick={() => navigate('/')}
          >
            <Store size={16} />
            ورود به کاتالوگ عمومی
          </button>
        </section>

        {/* Recent products table */}
        <section className="xl:col-span-8 card overflow-hidden">
          <div
            className="flex items-center justify-between gap-3 px-5 py-4 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <h3 className="font-semibold" style={{ color: 'var(--text-primary)' }}>
              محصولات اخیر
            </h3>
            <button
              type="button"
              onClick={() => navigate('/products')}
              className="text-xs font-medium px-3 py-1.5 rounded-lg flex items-center gap-1"
              style={{
                backgroundColor: 'var(--bg-tertiary)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
              }}
            >
              مشاهده همه
              <ArrowUpLeft size={14} />
            </button>
          </div>

          {recent.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
              هنوز محصولی ثبت نشده است
            </div>
          ) : (
            <>
              <div className="hidden sm:block overflow-x-auto">
                <table className="w-full text-sm" dir="rtl">
                  <thead>
                    <tr className="border-b" style={{ borderColor: 'var(--border-color)' }}>
                      <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>کد</th>
                      <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>نام</th>
                      <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>ماده</th>
                      <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>قیمت</th>
                      <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>وضعیت</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((p) => (
                      <tr
                        key={p.id}
                        className="table-row cursor-pointer"
                        onClick={() => navigate(`/products/${p.id}`)}
                      >
                        <td className="px-4 py-3 font-mono text-xs" style={{ color: 'var(--text-secondary)' }}>
                          {p.product_id || `P${p.id}`}
                        </td>
                        <td className="px-4 py-3 font-medium" style={{ color: 'var(--text-primary)' }}>
                          {p.name}
                        </td>
                        <td className="px-4 py-3" style={{ color: 'var(--text-secondary)' }}>
                          {p.material_name || '—'}
                        </td>
                        <td className="px-4 py-3 font-semibold" style={{ color: 'var(--text-primary)' }}>
                          {p.suggested_price != null ? formatPrice(p.suggested_price) : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge active={p.is_active !== false} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="sm:hidden divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {recent.map((p) => (
                  <div
                    key={p.id}
                    className="p-4 cursor-pointer active:bg-white/5"
                    onClick={() => navigate(`/products/${p.id}`)}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div>
                        <div className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                          {p.product_id || `P${p.id}`}
                        </div>
                        <h4 className="font-medium text-sm" style={{ color: 'var(--text-primary)' }}>
                          {p.name}
                        </h4>
                      </div>
                      <StatusBadge active={p.is_active !== false} />
                    </div>
                    <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                      <span>{p.material_name || '—'}</span>
                      <span className="font-bold mr-auto" style={{ color: 'var(--accent)' }}>
                        {p.suggested_price != null ? formatPrice(p.suggested_price) : '—'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
