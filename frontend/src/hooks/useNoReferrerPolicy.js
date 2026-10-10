import { useEffect } from 'react';

/**
 * Ensure a document-level ``referrer: no-referrer`` policy while a public
 * payment page is mounted.
 *
 * The ``/pay/:token`` URL carries a private bearer token, so any referrer the
 * document emits (asset loads, outbound navigation, third-party embeds) would
 * leak that token. The page owns the meta while it is on screen and restores
 * the document to its previous state on unmount, so no other route inherits
 * the tightened policy.
 *
 * This is the page-level control the design calls for; the backend separately
 * sends ``Referrer-Policy: no-referrer`` on the invoice API responses.
 */

export const NO_REFERRER_META_ID = 'pay-referrer-policy';

export function useNoReferrerPolicy() {
  useEffect(() => {
    const existing = document.getElementById(NO_REFERRER_META_ID);
    const created = !existing;

    const meta = existing || document.createElement('meta');
    if (created) {
      meta.id = NO_REFERRER_META_ID;
      meta.setAttribute('name', 'referrer');
      document.head.appendChild(meta);
    }
    const previous = meta.getAttribute('content');
    meta.setAttribute('content', 'no-referrer');

    return () => {
      if (created) {
        meta.remove();
        return;
      }
      if (previous == null) {
        meta.removeAttribute('content');
      } else {
        meta.setAttribute('content', previous);
      }
    };
  }, []);
}
