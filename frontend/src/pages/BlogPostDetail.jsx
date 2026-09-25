import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Calendar, Clock, Eye, Share2, Copy, Check, ArrowRight, BookOpen, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getBlogPostBySlug } from '../lib/api';
import { useSEO } from '../lib/seo';

export default function BlogPostDetail() {
  const { slug } = useParams();
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    async function fetchPost() {
      try {
        setLoading(true);
        const res = await getBlogPostBySlug(slug);
        setPost(res.data);
        setError(null);
      } catch (err) {
        if (err.response?.status === 404) {
          setError('مقاله مورد نظر پیدا نشد یا وبلاگ غیرفعال است.');
        } else {
          setError('خطا در بارگذاری مقاله');
        }
      } finally {
        setLoading(false);
      }
    }
    fetchPost();
  }, [slug]);

  // Dynamic SEO & Article JSON-LD
  useSEO({
    title: post ? `${post.title} — وبلاگ اسپاگتی پرینت` : 'مقاله — اسپاگتی پرینت',
    description: post?.summary || post?.title || 'مقاله چاپ سه‌بعدی',
    image: post?.cover_image,
    jsonLd: post
      ? {
          '@context': 'https://schema.org',
          '@type': 'Article',
          headline: post.title,
          description: post.summary,
          image: post.cover_image ? [post.cover_image] : [],
          datePublished: post.created_at,
          dateModified: post.updated_at || post.created_at,
          author: {
            '@type': 'Organization',
            name: 'Spaghettiprints',
          },
          publisher: {
            '@type': 'Organization',
            name: 'Spaghettiprints',
            logo: {
              '@type': 'ImageObject',
              url: 'https://spaghettiprints.ir/favicon.ico',
            },
          },
        }
      : null,
  });

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

  const handleCopyLink = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleShareTelegram = () => {
    const text = encodeURIComponent(`${post?.title}\n${window.location.href}`);
    window.open(`https://t.me/share/url?url=${encodeURIComponent(window.location.href)}&text=${text}`, '_blank');
  };

  if (loading) {
    return (
      <div className="py-20 text-center">
        <div
          className="w-10 h-10 border-3 border-t-transparent rounded-full animate-spin mx-auto mb-4"
          style={{ borderColor: 'var(--accent, #FF9A3D)', borderTopColor: 'transparent' }}
        />
        <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
          در حال دریافت مقاله...
        </p>
      </div>
    );
  }

  if (error || !post) {
    return (
      <div className="py-16 max-w-lg mx-auto text-center px-4">
        <div className="w-14 h-14 rounded-2xl bg-red-500/10 text-red-400 flex items-center justify-center mx-auto mb-4">
          <AlertCircle size={28} />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">{error || 'مقاله پیدا نشد'}</h2>
        <p className="text-sm text-slate-400 mb-6">
          ممکن است آدرس مقاله تغییر کرده باشد یا مقاله حذف شده باشد.
        </p>
        <Link
          to="/blog"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-medium text-white transition-all shadow-lg hover:shadow-orange-500/20"
          style={{ background: 'var(--accent, #FF9A3D)' }}
        >
          <ArrowRight size={18} />
          <span>بازگشت به مقالات</span>
        </Link>
      </div>
    );
  }

  return (
    <article className="max-w-4xl mx-auto space-y-8 text-right" dir="rtl" style={{ direction: 'rtl', textAlign: 'right' }}>
      {/* Breadcrumbs & Navigation */}
      <nav className="flex items-center gap-2 text-xs text-slate-400" aria-label="مسیر صفحه">
        <Link to="/" className="hover:text-amber-400 transition-colors">کاتالوگ</Link>
        <span>/</span>
        <Link to="/blog" className="hover:text-amber-400 transition-colors">وبلاگ</Link>
        <span>/</span>
        <span className="text-slate-200 truncate max-w-[200px] sm:max-w-xs">{post.title}</span>
      </nav>

      {/* Article Header */}
      <header className="space-y-6 text-right">
        <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black text-white leading-tight tracking-tight text-right">
          {post.title}
        </h1>

        {/* Metadata Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 py-4 border-y border-white/10 text-xs sm:text-sm text-slate-300">
          <div className="flex flex-wrap items-center gap-4">
            <span className="flex items-center gap-1.5">
              <Calendar size={16} className="text-amber-400" />
              <time dateTime={post.created_at}>{formatDate(post.created_at)}</time>
            </span>
            <span>•</span>
            <span className="flex items-center gap-1.5">
              <Clock size={16} className="text-amber-400" />
              <span>زمان مطالعه: {getReadingTime(post.content)} دقیقه</span>
            </span>
            <span>•</span>
            <span className="flex items-center gap-1.5">
              <Eye size={16} className="text-amber-400" />
              <span className="tabular-nums">{post.views || 0} بازدید</span>
            </span>
          </div>

          {/* Share buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyLink}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors text-xs font-medium border border-white/5"
              aria-label="کپی لینک مقاله"
            >
              {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
              <span>{copied ? 'کپی شد' : 'کپی لینک'}</span>
            </button>
            <button
              onClick={handleShareTelegram}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 text-sky-400 transition-colors text-xs font-medium border border-sky-500/20"
              aria-label="اشتراک‌گذاری در تلگرام"
            >
              <Share2 size={14} />
              <span>تلگرام</span>
            </button>
          </div>
        </div>

        {/* Summary Box */}
        {post.summary && (
          <div className="p-5 rounded-2xl bg-amber-500/5 border border-amber-500/20 text-amber-200/90 text-sm sm:text-base leading-relaxed text-right">
            <p className="font-semibold text-amber-400 mb-1">خلاصه مقاله:</p>
            {post.summary}
          </div>
        )}

        {/* Cover Image */}
        {post.cover_image && (
          <div className="relative rounded-3xl overflow-hidden aspect-video border border-white/10 bg-slate-900 shadow-2xl">
            <img
              src={post.cover_image}
              alt={post.title}
              className="w-full h-full object-cover"
            />
            <div className="absolute inset-0 ring-1 ring-inset ring-black/10 pointer-events-none" />
          </div>
        )}
      </header>

      {/* Article Body */}
      <main className="py-6 text-slate-200 text-base sm:text-lg leading-loose text-right" dir="rtl" style={{ direction: 'rtl', textAlign: 'right' }}>
        {post.content ? (
          <div className="blog-content space-y-6 text-right" dir="rtl">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ node, ...props }) => (
                  <h2 className="text-2xl sm:text-3xl font-black text-white mt-10 mb-4 pb-2 border-b border-white/10 text-right" {...props} />
                ),
                h2: ({ node, ...props }) => (
                  <h2 className="text-xl sm:text-2xl font-bold text-white mt-8 mb-3 text-right" {...props} />
                ),
                h3: ({ node, ...props }) => (
                  <h3 className="text-lg sm:text-xl font-bold text-amber-300 mt-6 mb-2 text-right" {...props} />
                ),
                p: ({ node, ...props }) => (
                  <p className="text-slate-300 leading-relaxed text-sm sm:text-base mb-4 text-right" {...props} />
                ),
                ul: ({ node, ...props }) => (
                  <ul className="list-disc list-inside space-y-2 text-sm sm:text-base text-slate-300 pr-2 mb-4 text-right" {...props} />
                ),
                ol: ({ node, ...props }) => (
                  <ol className="list-decimal list-inside space-y-2 text-sm sm:text-base text-slate-300 pr-2 mb-4 text-right" {...props} />
                ),
                li: ({ node, ...props }) => (
                  <li className="leading-relaxed text-slate-300 text-right" {...props} />
                ),
                a: ({ node, href, ...props }) => (
                  <Link
                    to={href || '#'}
                    className="text-amber-400 font-bold hover:text-amber-300 underline underline-offset-4 decoration-amber-400/50 hover:decoration-amber-300 transition-colors"
                    {...props}
                  />
                ),
                strong: ({ node, ...props }) => (
                  <strong className="font-bold text-white" {...props} />
                ),
                table: ({ node, style, ...props }) => (
                  <div className="overflow-x-auto my-6 rounded-2xl border border-white/10 bg-slate-900/60" dir="rtl" style={{ direction: 'rtl' }}>
                    <table className="w-full text-right text-xs sm:text-sm" dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                  </div>
                ),
                thead: ({ node, style, ...props }) => (
                  <thead className="bg-slate-800 text-amber-300 font-bold border-b border-white/10" dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                ),
                tbody: ({ node, style, ...props }) => (
                  <tbody dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                ),
                tr: ({ node, style, ...props }) => (
                  <tr dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                ),
                th: ({ node, style, ...props }) => (
                  <th className="p-3.5 font-bold text-right text-amber-300" dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                ),
                td: ({ node, style, ...props }) => (
                  <td className="p-3.5 border-t border-white/5 text-slate-300 text-right" dir="rtl" {...props} style={{ ...style, direction: 'rtl', textAlign: 'right' }} />
                ),
                hr: () => (
                  <hr className="my-8 border-white/10" />
                ),
                blockquote: ({ node, ...props }) => (
                  <blockquote className="p-4 my-4 rounded-2xl border-r-4 border-amber-400 bg-amber-500/10 text-amber-200 text-sm leading-relaxed text-right" dir="rtl" {...props} />
                ),
              }}
            >
              {post.content}
            </ReactMarkdown>
          </div>
        ) : (
          <p className="text-slate-500 italic text-center py-8">محتوایی برای این مقاله نوشته نشده است.</p>
        )}
      </main>

      {/* Article Footer */}
      <footer className="pt-8 border-t border-white/10 flex items-center justify-between">
        <Link
          to="/blog"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors text-sm font-medium border border-white/5"
        >
          <ArrowRight size={16} />
          <span>همه مقالات وبلاگ</span>
        </Link>
      </footer>
    </article>
  );
}
