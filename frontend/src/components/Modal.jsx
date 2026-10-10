import { useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { Z_INDEX_MODAL_PORTAL } from '../lib/constants';

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

export default function Modal({ isOpen, onClose, title, children, size = 'lg' }) {
  const sizes = {
    sm: '400px',
    md: '520px',
    lg: '640px',
    xl: '860px',
  };
  const dialogRef = useRef(null);
  const previousFocusRef = useRef(null);

  // Keep the latest onClose available to the keydown listener without making it
  // an effect dependency: a parent that re-creates onClose on every render must
  // not re-run the open effect, which would re-steal focus mid-typing.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const handleEscape = useCallback((e) => {
    if (e.key === 'Escape') onCloseRef.current();
  }, []);

  const handleKeyDown = useCallback((e) => {
    if (e.key !== 'Tab') return;

    const focusableElements = getFocusableElements(dialogRef.current);
    if (focusableElements.length === 0) {
      e.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (e.shiftKey && document.activeElement === firstElement) {
      e.preventDefault();
      lastElement.focus();
    } else if (!e.shiftKey && document.activeElement === lastElement) {
      e.preventDefault();
      firstElement.focus();
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';

      requestAnimationFrame(() => {
        const focusableElements = getFocusableElements(dialogRef.current);
        (focusableElements[0] || dialogRef.current)?.focus();
      });
    }
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
      if (previousFocusRef.current?.isConnected) {
        previousFocusRef.current.focus();
      }
    };
  }, [isOpen, handleEscape]);

  if (!isOpen) return null;

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: Z_INDEX_MODAL_PORTAL,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        dir: 'rtl',
      }}
    >
      {/* Backdrop */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'var(--overlay-bg)',
          animation: 'fadeIn 0.3s ease forwards',
        }}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal content */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: sizes[size] || sizes.lg,
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderRadius: '0.75rem',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
          animation: 'fadeInScale 0.2s ease forwards',
          overscrollBehavior: 'contain',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--border-color)',
            flexShrink: 0,
          }}
        >
          <h3 id="modal-title" style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="بستن پنجره"
            style={{
              padding: '6px',
              borderRadius: '8px',
              color: 'var(--text-muted)',
              backgroundColor: 'var(--bg-tertiary)',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: 32,
              minHeight: 32,
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px', overflowY: 'auto', flex: 1 }}>
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}
