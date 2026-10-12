import { useEffect } from 'react';

/**
 * Force a document-level ``referrer: origin`` policy while the token-free
 * gateway hand-off page is mounted.
 *
 * The hand-off page carries NO bearer token, so it deliberately does the
 * opposite of the private /pay/<token> page: it must let the browser emit
 * ``Referer: https://spaghettiprints.ir/`` (scheme+host+port only, never a
 * path or query) for the outbound navigation to the BitPay portal, which
 * rejects a hand-off that arrives with no/invalid referer.
 *
 * This meta is defence in depth behind the nginx ``Referrer-Policy: origin``
 * header and the anchor's ``referrerpolicy="origin"``: it keeps the document
 * policy origin-only even if this component is reached by a client-side route
 * change from the no-referrer pay document. The previous document state is
 * restored on unmount so no other route inherits it.
 */

export const ORIGIN_REFERRER_META_ID = 'gateway-referrer-policy';

export function useOriginReferrerPolicy() {
  useEffect(() => {
    const existing = document.getElementById(ORIGIN_REFERRER_META_ID);
    const created = !existing;

    const meta = existing || document.createElement('meta');
    if (created) {
      meta.id = ORIGIN_REFERRER_META_ID;
      meta.setAttribute('name', 'referrer');
      document.head.appendChild(meta);
    }
    const previous = meta.getAttribute('content');
    meta.setAttribute('content', 'origin');

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
