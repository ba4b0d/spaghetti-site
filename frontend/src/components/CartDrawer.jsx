import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { X, ShoppingBag, Trash2, Plus, Minus, ArrowRight } from 'lucide-react';
import { getCatalog } from '../lib/api';
import { readCart, updateQuantity, removeItem, subscribe, cartCount } from '../lib/cart';
import { Z_INDEX_SIDEBAR, Z_INDEX_OVERLAY } from '../lib/constants';

/**
 * Storefront cart drawer.
 *
 * Reads only ids + quantities from the persisted cart and resolves display
 * names from the public catalogue. Prices shown here are INDICATIVE — the
 * authoritative amount is computed server-side after staff review.
 *
 * NOTE: deliberately does NOT reuse the `.catalog-drawer*` classes — those are
 * `display: none !important` at >=1200px (they belong to the mobile nav).
 */

const PANEL_WIDTH = 'min(92vw, 24rem)';

// Same focusable contract as the mobile nav drawer (CatalogLayout) so the two
// modals behave identically for keyboard users.
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
    (element) =>
      !element.hasAttribute('disabled') &&
      element.getAttribute('aria-hidden') !== 'true' &&
      element.getAttribute('aria-disabled') !== 'true'
  );

export default function CartDrawer({ open, onClose }) {
  const [items, setItems] = useState(() => readCart());
  const [catalog, setCatalog] = useState([]);
  const panelRef = useRef(null);
  const previousFocusRef = useRef(null);

  // `onClose` must be reachable from the open/close effect WITHOUT being a
  // dependency. Callers commonly pass an inline arrow (e.g. `() => setOpen(false)`)
  // whose identity changes on every parent render; because the layout subscribes
  // to the cart store, mutating the cart inside the drawer re-renders the parent
  // and would otherwise re-run that effect mid-session — re-capturing the opener
  // and yanking focus back to the panel header on every `+`/`−`/trash click.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Keep the drawer in sync with the shared cart store.
  useEffect(() => subscribe(() => setItems(readCart())), []);

  useEffect(() => {
    if (!open) return undefined;
    setItems(readCart());
    let active = true;
    getCatalog()
      .then((res) => {
        if (active) setCatalog(Array.isArray(res?.data) ? res.data : []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    // Remember the element that opened the drawer so focus can be restored.
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const onKey = (event) => {
      if (event.key === 'Escape') {
        onCloseRef.current?.();
        return;
      }

      if (event.key !== 'Tab') return;
      const focusableElements = getFocusableElements(panelRef.current);
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        firstElement.focus();
      } else if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKey);

    // Move focus into the panel once it is rendered/visible.
    const frame = requestAnimationFrame(() => {
      const focusableElements = getFocusableElements(panelRef.current);
      (focusableElements[0] || panelRef.current)?.focus();
    });

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
      cancelAnimationFrame(frame);
    };
    // Deliberately NOT depending on `onClose` (read via `onCloseRef`) so a
    // re-render of the parent mid-session cannot re-run this effect and
    // re-capture/re-steal focus. The opener is captured once, on open.
  }, [open]);

  // Restore focus to the trigger once the drawer closes.
  useEffect(() => {
    if (open) return undefined;
    const previous = previousFocusRef.current;
    previousFocusRef.current = null;
    // Only a control OUTSIDE the panel is a legitimate opener: the panel stays
    // mounted (inert) after close, so restoring into it would silently no-op
    // in a real browser.
    if (previous && previous.isConnected && !panelRef.current?.contains(previous)) {
      previous.focus();
    }
    return undefined;
  }, [open]);

  const byId = useMemo(() => {
    const map = new Map();
    for (const product of catalog) map.set(Number(product.id), product);
    return map;
  }, [catalog]);

  const total = cartCount(items);

  const changeQty = useCallback((id, qty) => {
    setItems(updateQuantity(id, qty));
  }, []);

  const drop = useCallback((id) => {
    setItems(removeItem(id));
  }, []);

  return (
    <>
      <div
        aria-hidden={!open}
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(15, 23, 42, 0.55)',
          opacity: open ? 1 : 0,
          visibility: open ? 'visible' : 'hidden',
          transition: 'opacity 0.22s ease, visibility 0.22s ease',
          zIndex: Z_INDEX_OVERLAY,
        }}
      />
      <aside
        id="catalog-cart-drawer"
        ref={panelRef}
        tabIndex={-1}
        dir="rtl"
        aria-hidden={!open}
        inert={!open ? '' : undefined}
        role="dialog"
        aria-modal={open ? 'true' : undefined}
        aria-label="سبد خرید"
        style={{
          position: 'fixed',
          top: 0,
          bottom: 0,
          right: 0,
          width: PANEL_WIDTH,
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-card)',
          borderInlineStart: '1px solid var(--border-color)',
          boxShadow: '0 24px 60px rgba(0, 0, 0, 0.28)',
          transform: open ? 'translateX(0)' : 'translateX(105%)',
          transition: 'transform 0.26s ease',
          zIndex: Z_INDEX_SIDEBAR,
        }}
      >
        <div
          className="flex items-center justify-between gap-3 px-4 py-3 border-b shrink-0"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
              style={{ backgroundColor: 'var(--accent-light)', color: 'var(--accent)' }}
              aria-hidden="true"
            >
              <ShoppingBag size={18} />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                سبد خرید
              </p>
              <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                {total > 0 ? `${total} عدد کالا` : 'خالی'}
              </p>
            </div>
          </div>
          <button
            type="button"
            className="p-2 rounded-xl shrink-0 hover:opacity-80"
            style={{ color: 'var(--text-secondary)' }}
            aria-label="بستن سبد خرید"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-4 flex-1 overflow-y-auto space-y-3">
          {items.length === 0 ? (
            <div className="text-center py-12 space-y-3">
              <div
                className="mx-auto w-14 h-14 rounded-2xl flex items-center justify-center"
                style={{ backgroundColor: 'var(--accent-light)' }}
                aria-hidden="true"
              >
                <ShoppingBag size={26} style={{ color: 'var(--accent)', opacity: 0.85 }} />
              </div>
              <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                سبد خرید خالی است
              </p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                از کاتالوگ، محصول مورد نظرتان را اضافه کنید.
              </p>
            </div>
          ) : (
            items.map((item) => {
              const product = byId.get(Number(item.id));
              const name = product?.name || `کد ${item.id}`;
              const price = product?.final_price || product?.suggested_price;
              return (
                <div
                  key={item.id}
                  className="rounded-2xl border p-3 flex flex-col gap-2"
                  style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      to={product?.slug ? `/catalog/${product.slug}` : '/catalog'}
                      className="text-sm font-semibold leading-snug line-clamp-2 hover:opacity-80"
                      style={{ color: 'var(--text-primary)' }}
                      onClick={onClose}
                    >
                      {name}
                    </Link>
                    <button
                      type="button"
                      className="p-1.5 rounded-lg shrink-0"
                      style={{ color: '#ef4444' }}
                      aria-label={`حذف ${name} از سبد خرید`}
                      onClick={() => drop(item.id)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>

                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="inline-flex items-center gap-1 rounded-xl border" style={{ borderColor: 'var(--border-color)' }}>
                      <button
                        type="button"
                        className="w-7 h-7 inline-flex items-center justify-center"
                        aria-label={`کاهش تعداد ${name}`}
                        onClick={() => changeQty(item.id, item.qty - 1)}
                      >
                        <Minus size={13} />
                      </button>
                      <span className="text-xs font-bold tabular-nums w-7 text-center" style={{ color: 'var(--text-primary)' }}>
                        {item.qty}
                      </span>
                      <button
                        type="button"
                        className="w-7 h-7 inline-flex items-center justify-center"
                        aria-label={`افزایش تعداد ${name}`}
                        onClick={() => changeQty(item.id, item.qty + 1)}
                      >
                        <Plus size={13} />
                      </button>
                    </div>
                    {price ? (
                      <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                        قیمت نمایشی: {Number(price).toLocaleString('fa-IR')} تومان
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="p-4 border-t space-y-2 shrink-0" style={{ borderColor: 'var(--border-color)' }}>
          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            مبلغ نهایی پس از بررسی توسط تیم پشتیبانی اعلام و تأیید میشود.
          </p>
          <Link
            to="/checkout"
            className="btn-primary w-full inline-flex items-center justify-center gap-2"
            aria-disabled={items.length === 0}
            onClick={(event) => {
              // A disabled CTA must not navigate for pointer OR keyboard users:
              // native anchors fire a click on Enter, so preventDefault here
              // blocks both activation paths.
              if (items.length === 0) {
                event.preventDefault();
                return;
              }
              onClose?.();
            }}
            style={items.length === 0 ? { opacity: 0.5, pointerEvents: 'none' } : undefined}
          >
            ادامه و ثبت درخواست
            <ArrowRight size={16} />
          </Link>
        </div>
      </aside>
    </>
  );
}
