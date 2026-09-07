import { useCallback, useEffect, useState, useRef } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { Menu, X, ChevronDown, Search } from 'lucide-react';
import { Z_INDEX_STICKY } from '../lib/constants';
import BrandLogo from './BrandLogo';
import { getBlogPosts, getCatalogCategories, getPublicBrand } from '../lib/api';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const getFocusableElements = (container) =>
  Array.from(container?.querySelectorAll(FOCUSABLE_SELECTOR) || []).filter(
    (element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true'
  );

const navLinkClass = ({ isActive }) =>
  `catalog-nav-link${isActive ? ' catalog-nav-link--active' : ''}`;

const drawerLinkClass = ({ isActive }) =>
  `catalog-drawer-link${isActive ? ' catalog-drawer-link--active' : ''}`;

export default function CatalogLayout({ children }) {
  // NOTE: this layout does NOT call useSEO — individual child pages set their
  //       own SEO title/description/canonical. The inline <script> in index.html
  //       provides a synchronous fallback canonical tag on every page load.

  const [menuOpen, setMenuOpen] = useState(false);
  const [blogEnabled, setBlogEnabled] = useState(false);
  const [catTree, setCatTree] = useState([]);
  const [megaOpen, setMegaOpen] = useState(false);
  const [megaSearch, setMegaSearch] = useState('');
  const [megaHoveredCat, setMegaHoveredCat] = useState(null);
  const [mobileExpandedCat, setMobileExpandedCat] = useState(null);
  const megaRef = useRef(null);
  const drawerRef = useRef(null);
  const menuButtonRef = useRef(null);
  const previousFocusRef = useRef(null);
  const megaTimer = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    getCatalogCategories()
      .then((res) => setCatTree(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});

    getPublicBrand()
      .then((res) => {
        if (res.data?.enable_blog != null) {
          setBlogEnabled(Boolean(res.data.enable_blog));
        }
      })
      .catch(() => {});
  }, []);

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const toggleMenu = () => {
    if (!menuOpen) {
      previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : menuButtonRef.current;
    }
    setMenuOpen((open) => !open);
  };

  useEffect(() => {
    if (!menuOpen) {
      if (previousFocusRef.current?.isConnected) {
        previousFocusRef.current.focus();
      }
      return undefined;
    }

    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => {
      if (e.key === 'Escape') {
        closeMenu();
        return;
      }

      if (e.key !== 'Tab') return;
      const focusableElements = getFocusableElements(drawerRef.current);
      if (focusableElements.length === 0) return;
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (!drawerRef.current?.contains(document.activeElement)) {
        e.preventDefault();
        firstElement.focus();
      } else if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    requestAnimationFrame(() => {
      getFocusableElements(drawerRef.current)[0]?.focus();
    });
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
  }, [menuOpen, closeMenu]);

  // Hover handlers with delay to prevent flicker
  const megaEnter = () => {
    clearTimeout(megaTimer.current);
    setMegaOpen(true);
    // Measure header height and set CSS variable
    requestAnimationFrame(() => {
      const header = document.querySelector('.catalog-topbar');
      if (header) {
        const rect = header.getBoundingClientRect();
        document.documentElement.style.setProperty('--mega-top', `${rect.bottom}px`);
      }
    });
  };
  const megaLeave = () => {
    megaTimer.current = setTimeout(() => setMegaOpen(false), 150);
  };

  const toggleMegaMenu = () => {
    clearTimeout(megaTimer.current);
    setMegaOpen((open) => !open);
  };

  const handleMegaKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleMegaMenu();
    } else if (event.key === 'Escape') {
      setMegaOpen(false);
    }
  };

  // Filter categories by search
  const filteredTree = megaSearch.trim()
    ? catTree.filter((cat) => {
        const q = megaSearch.toLowerCase();
        const nameMatch = cat.name.toLowerCase().includes(q);
        const childMatch = (cat.children || []).some((sub) =>
          sub.name.toLowerCase().includes(q)
        );
        return nameMatch || childMatch;
      })
    : catTree;

  return (
    <div
      className="catalog-shell min-h-screen flex flex-col relative"
      dir="rtl"
      style={{ backgroundColor: 'transparent', color: 'var(--text-primary)' }}
    >
      <div className="catalog-ambient" aria-hidden="true" />

      <header className="catalog-topbar" style={{ zIndex: Z_INDEX_STICKY }}>
        <div className="catalog-topbar-inner">
          <Link to="/" className="catalog-brand-link flex items-center gap-2.5 sm:gap-3.5 min-w-0">
            <BrandLogo height={85} className="catalog-logo-img shrink-0">
              <div className="catalog-logo-mark shrink-0" aria-hidden="true">S</div>
            </BrandLogo>
            <div className="min-w-0 catalog-brand-text">
              <h1 className="catalog-brand-title truncate">اسپاگتی پرینت</h1>
              <p className="catalog-brand-sub truncate">Spaghetti · کاتالوگ</p>
            </div>
          </Link>

          <nav className="catalog-nav catalog-nav--desktop" aria-label="منوی عمومی">
            {/* Categories mega-menu trigger + panel (single positioned container) */}
            <div
              ref={megaRef}
              className="catalog-mega-wrap"
              onMouseEnter={megaEnter}
              onMouseLeave={megaLeave}
            >
              <button
                type="button"
                className={`catalog-nav-link flex items-center gap-1 ${megaOpen ? 'catalog-nav-link--active' : ''}`}
                aria-expanded={megaOpen}
                aria-haspopup="menu"
                aria-controls="catalog-mega-menu"
                onClick={toggleMegaMenu}
                onKeyDown={handleMegaKeyDown}
              >
                دسته‌بندی‌ها
                <ChevronDown size={14} className={`transition-transform duration-200 ${megaOpen ? 'rotate-180' : ''}`} />
              </button>

              {megaOpen && (
                <div id="catalog-mega-menu" className="mega-menu-panel" role="menu" aria-label="دستهبندی محصولات">
                  <div className="mega-menu-inner">
                    {/* Search bar */}
                    <div className="mega-menu-search">
                      <Search size={16} style={{ color: 'var(--text-muted)' }} />
                      <input
                        type="text"
                        placeholder="جستجوی دسته‌بندی..."
                        value={megaSearch}
                        onChange={(e) => setMegaSearch(e.target.value)}
                        autoFocus
                      />
                    </div>

                    {/* Two-panel layout: right = parents, left = children */}
                    <div className="mega-menu-panels">
                      {/* Right panel: main categories */}
                      <div className="mega-menu-right">
                        {filteredTree.length === 0 ? (
                          <div className="mega-menu-empty">دسته‌بندی‌ای یافت نشد</div>
                        ) : (
                          filteredTree.map((cat) => (
                            <button
                              key={cat.id}
                              type="button"
                              className={`mega-menu-parent ${megaHoveredCat === cat.id ? 'mega-menu-parent--active' : ''}`}
                              onMouseEnter={() => setMegaHoveredCat(cat.id)}
                              onClick={() => {
                                setMegaOpen(false);
                                navigate(`/?category=${cat.id}`);
                              }}
                            >
                              <span>{cat.name}</span>
                              {cat.children && cat.children.length > 0 && (
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.4, transform: 'scaleX(-1)' }}>
                                  <polyline points="9 18 15 12 9 6" />
                                </svg>
                              )}
                            </button>
                          ))
                        )}
                      </div>

                      {/* Left panel: sub-categories */}
                      <div className="mega-menu-left">
                        {megaHoveredCat && (() => {
                          const parent = filteredTree.find((c) => c.id === megaHoveredCat);
                          if (!parent) return <div className="mega-menu-empty">زیرمجموعه‌ای ندارد</div>;
                          if (!parent.children || parent.children.length === 0) {
                            return (
                              <div className="mega-menu-left-header">
                                <span className="mega-menu-left-title">{parent.name}</span>
                                <span className="mega-menu-left-hint">زیرمجموعه‌ای ندارد</span>
                              </div>
                            );
                          }
                          return (
                            <>
                              <div className="mega-menu-left-header">
                                <span className="mega-menu-left-title">{parent.name}</span>
                              </div>
                              <div className="mega-menu-left-list">
                                {parent.children.map((sub) => (
                                  <button
                                    key={sub.id}
                                    type="button"
                                    className="mega-menu-child"
                                    onClick={() => {
                                      setMegaOpen(false);
                                      navigate(`/?category=${sub.id}`);
                                    }}
                                  >
                                    {sub.name}
                                  </button>
                                ))}
                              </div>
                              <button
                                type="button"
                                className="mega-menu-see-all"
                                onClick={() => {
                                  setMegaOpen(false);
                                  navigate(`/?category=${parent.id}`);
                                }}
                              >
                                مشاهده همه {parent.name}
                              </button>
                            </>
                          );
                        })()}
                        {!megaHoveredCat && (
                          <div className="mega-menu-empty" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            یک دسته‌بندی را انتخاب کنید
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <NavLink to="/" end className={navLinkClass}>
              کاتالوگ
            </NavLink>
            {blogEnabled && (
              <NavLink to="/blog" className={navLinkClass}>
                وبلاگ
              </NavLink>
            )}
            <NavLink to="/how-to-order" className={navLinkClass}>
              سفارش از کاتالوگ
            </NavLink>
            <NavLink to="/custom-order" className={navLinkClass}>
              سفارش طرح دلخواه
            </NavLink>
            <NavLink to="/contact" className={navLinkClass}>
              تماس با ما
            </NavLink>
          </nav>

          <div className="catalog-topbar-actions">
            <button
              ref={menuButtonRef}
              type="button"
              className="catalog-menu-btn"
              aria-label={menuOpen ? 'بستن منو' : 'باز کردن منو'}
              aria-expanded={menuOpen}
              aria-controls="catalog-mobile-drawer"
              onClick={toggleMenu}
            >
              {menuOpen ? <X size={22} strokeWidth={2.25} /> : <Menu size={22} strokeWidth={2.25} />}
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer */}
      <div
        className={`catalog-drawer-backdrop${menuOpen ? ' is-open' : ''}`}
        aria-hidden={!menuOpen}
        onClick={closeMenu}
      />
      <aside
        ref={drawerRef}
        id="catalog-mobile-drawer"
        className={`catalog-drawer${menuOpen ? ' is-open' : ''}`}
        aria-hidden={!menuOpen}
        inert={!menuOpen ? '' : undefined}
        role="dialog"
        aria-modal={menuOpen ? 'true' : undefined}
        aria-label="منوی موبایل"
      >
        <div className="catalog-drawer-head">
          <div className="flex items-center gap-2.5 min-w-0">
            <BrandLogo height={48} className="catalog-drawer-logo shrink-0">
              <div className="catalog-logo-mark catalog-logo-mark--drawer shrink-0" aria-hidden="true">S</div>
            </BrandLogo>
            <div className="min-w-0">
              <p className="catalog-drawer-title truncate">اسپاگتی پرینت</p>
              <p className="catalog-drawer-sub truncate">منوی کاتالوگ</p>
            </div>
          </div>
          <button type="button" className="catalog-drawer-close" aria-label="بستن منوی موبایل" onClick={closeMenu}>
            <X size={20} />
          </button>
        </div>

        <nav className="catalog-drawer-nav" aria-label="پیوندهای موبایل">
          <NavLink to="/" end className={drawerLinkClass} onClick={closeMenu}>
            کاتالوگ
          </NavLink>
          {blogEnabled && (
            <NavLink to="/blog" className={drawerLinkClass} onClick={closeMenu}>
              وبلاگ
            </NavLink>
          )}
          <NavLink to="/how-to-order" className={drawerLinkClass} onClick={closeMenu}>
            سفارش از کاتالوگ
          </NavLink>
          <NavLink to="/custom-order" className={drawerLinkClass} onClick={closeMenu}>
            سفارش طرح دلخواه
          </NavLink>
          <NavLink to="/contact" className={drawerLinkClass} onClick={closeMenu}>
            تماس با ما
          </NavLink>

          {catTree.length > 0 && (
            <div className="mt-3 pt-3 border-t catalog-drawer-cats" style={{ borderColor: 'var(--border-color)' }}>
              <p className="text-xs font-semibold px-3 py-1" style={{ color: 'var(--text-muted)' }}>دسته‌بندی‌ها</p>
              {catTree.map((cat) => (
                <div key={cat.id} className="catalog-drawer-cat-item">
                  <button
                    type="button"
                    className={`catalog-drawer-link catalog-drawer-cat-btn${mobileExpandedCat === cat.id ? ' catalog-drawer-cat-btn--open' : ''}`}
                    onClick={() => {
                      if (cat.children && cat.children.length > 0) {
                        setMobileExpandedCat(mobileExpandedCat === cat.id ? null : cat.id);
                      } else {
                        closeMenu();
                        navigate(`/?category=${cat.id}`);
                      }
                    }}
                  >
                    <span>{cat.name}</span>
                    {cat.children && cat.children.length > 0 && (
                      <ChevronDown
                        size={14}
                        style={{
                          transition: 'transform 0.2s ease',
                          transform: mobileExpandedCat === cat.id ? 'rotate(180deg)' : 'none',
                          opacity: 0.5,
                        }}
                      />
                    )}
                  </button>
                  {cat.children && cat.children.length > 0 && mobileExpandedCat === cat.id && (
                    <div className="catalog-drawer-subcats">
                      <NavLink
                        to={`/?category=${cat.id}`}
                        className="drawer-link-class"
                        style={{ paddingLeft: '32px', fontSize: '12px', color: '#FF9A3D', fontWeight: 600 }}
                        onClick={closeMenu}
                      >
                        مشاهده همه {cat.name}
                      </NavLink>
                      {cat.children.map((sub) => (
                        <NavLink
                          key={sub.id}
                          to={`/?category=${sub.id}`}
                          className={drawerLinkClass}
                          onClick={closeMenu}
                          style={{ paddingLeft: '32px', fontSize: '13px' }}
                        >
                          {sub.name}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </nav>
      </aside>

      <main className="relative flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10" inert={menuOpen ? '' : undefined}>
        {children}
      </main>

      <footer className="relative border-t py-7 catalog-footer" style={{ borderColor: 'var(--border-color)' }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
          <div className="text-center sm:text-right catalog-footer-copy">
            <span className="opacity-95">© Spaghettiprints · اسپاگتی پرینت</span>
            <span className="mx-2 opacity-50">·</span>
            <span>کاتالوگ محصولات چاپ سه‌بعدی</span>
            <span className="mx-2 opacity-50">·</span>
            <span aria-hidden="true">✨</span>
            <span className="mx-1 opacity-50">·</span>
            <span>قدرت گرفته از ایده و خیال ما</span>
          </div>
          <nav className="flex flex-wrap items-center justify-center gap-3" aria-label="پاورقی">
            <Link to="/" className="catalog-footer-link">کاتالوگ</Link>
            {blogEnabled && <Link to="/blog" className="catalog-footer-link">وبلاگ</Link>}
            <Link to="/how-to-order" className="catalog-footer-link">سفارش از کاتالوگ</Link>
            <Link to="/custom-order" className="catalog-footer-link">سفارش طرح دلخواه</Link>
            <Link to="/contact" className="catalog-footer-link">تماس با ما</Link>
            <Link to="/card" className="catalog-footer-link">کارت ویزیت</Link>
            <Link to="/privacy" className="catalog-footer-link">حریم خصوصی</Link>
            <Link to="/terms" className="catalog-footer-link">قوانین</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
