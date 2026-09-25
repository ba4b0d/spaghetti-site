import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Clock, Eye, Calendar, ArrowLeft, BookOpen, AlertCircle } from 'lucide-react';
import { getBlogPosts } from '../lib/api';
import { useSEO } from '../lib/seo';

export default function BlogList() {
  useSEO({
    title: 'وبلاگ و مقالات — اسپاگتی پرینت',
    description: 'جدیدترین اخبار، آموزش‌ها و مقالات دنیای چاپ سه‌بعدی و مدل‌سازی در اسپاگتی پرینت',
    url: '/blog',
  });

  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchPosts() {
      try {
        setLoading(true);
        const res = await getBlogPosts();
        setPosts(res.data || []);
        setError(null);
      } catch (err) {
        if (err.response?.status === 404) {
          setError('وبلاگ در حال حاضر غیرفعال است.');
        } else {
          setError('خطا در بارگذاری مقالات وبلاگ');
        }
      } finally {
        setLoading(false);
      }
    }
    fetchPosts();
  }, []);

  // Helper to estimate reading time (words / 200)
  const getReadingTime = (content = '') => {
    const words = content.trim().split(/\s+/).length;
    const minutes = Math.ceil(words / 200);
    return minutes < 1 ? 1 : minutes;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return new Intl.DateTimeFormat('fa-IR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }).format(d);
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className="py-16 text-center">
        <div
          className="w-10 h-10 border-3 border-t-transparent rounded-full animate-spin mx-auto mb-4"
          style={{ borderColor: 'var(--accent, #FF9A3D)', borderTopColor: 'transparent' }}
        />
        <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
          در حال بارگذاری مقالات...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-16 max-w-lg mx-auto text-center px-4">
        <div className="w-14 h-14 rounded-2xl bg-amber-500/10 text-amber-400 flex items-center justify-center mx-auto mb-4">
          <AlertCircle size={28} />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">{error}</h2>
        <p className="text-sm text-slate-400 mb-6">
          می‌توانید از کاتالوگ محصولات دیدن کنید.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-medium text-white transition-all shadow-lg hover:shadow-orange-500/20"
          style={{ background: 'var(--accent, #FF9A3D)' }}
        >
          <span>بازگشت به کاتالوگ</span>
          <ArrowLeft size={18} />
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Header Banner */}
      <div className="relative rounded-3xl p-8 sm:p-12 overflow-hidden border border-white/10"
           style={{ background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95))' }}>
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-amber-500 via-orange-500 to-amber-400" />
        <div className="max-w-2xl relative z-10">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 mb-4">
            <BookOpen size={14} />
            <span>مجله اسپاگتی پرینت</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight leading-tight mb-4">
            وبلاگ و اخبار چاپ سه‌بعدی
          </h1>
          <p className="text-base text-slate-300 leading-relaxed">
            راهنماهای تخصصی، مقالات آموزشی، و رویدادهای دنیای ساخت و تولید اضافه و چاپ 3D.
          </p>
        </div>
      </div>

      {/* Blog Cards Grid */}
      {posts.length === 0 ? (
        <div className="text-center py-16 bg-slate-900/40 rounded-3xl border border-white/5 p-8">
          <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4 text-slate-400">
            <BookOpen size={28} />
          </div>
          <h3 className="text-lg font-bold text-white mb-2">هنوز مقاله‌ای منتشر نشده است</h3>
          <p className="text-sm text-slate-400">به‌زودی مقالات جدیدی در این بخش اضافه خواهند شد.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {posts.map((post) => (
            <article
              key={post.id}
              className="group flex flex-col rounded-2xl overflow-hidden border transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-orange-500/5"
              style={{
                backgroundColor: 'rgba(30, 41, 59, 0.6)',
                borderColor: 'rgba(255, 255, 255, 0.08)',
              }}
            >
              {/* Cover Image */}
              <Link
                to={`/blog/${post.slug}`}
                aria-label={`مطالعه مقاله ${post.title}`}
                className="block relative aspect-video overflow-hidden bg-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-500"
              >
                {post.cover_image ? (
                  <img
                    src={post.cover_image}
                    alt=""
                    aria-hidden="true"
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-slate-600 bg-gradient-to-br from-slate-800 to-slate-900">
                    <BookOpen size={48} opacity={0.3} />
                  </div>
                )}
                {/* Image Subtle Outline per better-ui skill */}
                <div className="absolute inset-0 ring-1 ring-inset ring-black/10 dark:ring-white/10 pointer-events-none" />
              </Link>

              {/* Card Body */}
              <div className="p-6 flex-1 flex flex-col justify-between space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-3 text-xs text-slate-400 font-medium">
                    <span className="flex items-center gap-1">
                      <Calendar size={13} className="text-amber-400" />
                      <time dateTime={post.created_at}>{formatDate(post.created_at)}</time>
                    </span>
                    <span>•</span>
                    <span className="flex items-center gap-1">
                      <Clock size={13} className="text-amber-400" />
                      <span>{getReadingTime(post.content)} دقیقه مطالعه</span>
                    </span>
                  </div>

                  <h2 className="text-xl font-bold text-white group-hover:text-amber-400 transition-colors line-clamp-2 leading-snug">
                    <Link to={`/blog/${post.slug}`}>{post.title}</Link>
                  </h2>

                  {post.summary && (
                    <p className="text-sm text-slate-300 line-clamp-3 leading-relaxed">
                      {post.summary}
                    </p>
                  )}
                </div>

                {/* Card Footer Action */}
                <div className="pt-4 border-t border-white/5 flex items-center justify-between text-xs font-semibold">
                  <span className="flex items-center gap-1 text-slate-400">
                    <Eye size={14} />
                    <span className="tabular-nums">{post.views || 0} بازدید</span>
                  </span>

                  <Link
                    to={`/blog/${post.slug}`}
                    className="inline-flex items-center gap-1 text-amber-400 group-hover:text-amber-300 transition-colors font-bold"
                  >
                    <span>ادامه مطلب</span>
                    <ArrowLeft size={14} className="transition-transform group-hover:-translate-x-1" />
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
