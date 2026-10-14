/**
 * Customer order-history HTTP client — the one-visit «سفارش‌های من» flow.
 *
 * Deliberately a SEPARATE Axios instance from both ``lib/api.js`` (the admin
 * client, which force-redirects any 401 to /login) and ``lib/commerceApi.js``
 * (the storefront client, which forwards the staff session cookie):
 *
 *   * it sets **no default ``Authorization`` header** — the history bearer is a
 *     private credential attached to exactly the two calls that need it (the
 *     history read and sign-out) and never to the OTP calls, so it can never be
 *     accidentally sprayed at an unrelated endpoint;
 *   * it sets ``withCredentials: false`` so the browser does not attach
 *     credentials to a cross-origin call. This does **not** stop a same-origin
 *     request from carrying the browser's cookies, so the real guarantee is
 *     server-side: the history router authenticates **only** the explicit
 *     bearer header and ignores any cookie. ``withCredentials: false`` is
 *     defence in depth, not cookie isolation;
 *   * it propagates errors untouched, so the page can tell a dead session (401)
 *     from a throttle (429) or a delivery failure (503) and react per case.
 */
import axios from 'axios';

const historyApi = axios.create({
  baseURL: '/api/v1/commerce',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
});

// Propagate errors untouched — no login redirect, no cookie fallback.
historyApi.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);

/** A real bearer is required; otherwise reject rather than send an anonymous call. */
function missingBearer(token) {
  return typeof token !== 'string' || token.trim() === ''
    ? Promise.reject(new Error('history bearer required'))
    : null;
}

/** Explicit bearer header for a single request — never an instance default. */
function bearerHeaders(token, config) {
  return {
    ...(config?.headers || {}),
    Authorization: `Bearer ${String(token)}`,
  };
}

/**
 * Public — begin the history OTP gate: send a one-time SMS code to the
 * customer's own mobile. Returns `{ challenge_id, expires_in, resend_after,
 * delivery, masked_mobile }`. The code itself is never returned.
 */
export const requestHistoryOtp = (payload = {}, config) =>
  historyApi.post('/history/otp', { mobile: payload.mobile }, config);

/**
 * Public — exchange a valid code for the short-lived bearer session. Returns
 * `{ token, expires_at }`; the raw token is stored only in this tab.
 */
export const verifyHistoryOtp = (payload = {}, config) =>
  historyApi.post(
    '/history/verify',
    {
      mobile: payload.mobile,
      challenge_id: payload.challenge_id,
      code: payload.code,
    },
    config
  );

/**
 * Public — the verified mobile's own redacted history, newest first.
 * `{ items, has_more }`; requires the caller to pass the bearer explicitly.
 */
export const getCustomerHistory = (token, params = {}, config) => {
  const missing = missingBearer(token);
  if (missing) return missing;
  const { limit = 20, offset = 0 } = params || {};
  return historyApi.get('/history', {
    ...config,
    params: { limit, offset },
    headers: bearerHeaders(token, config),
  });
};

/** Public — the verified customer's profile, contact info and saved addresses. */
export const getCustomerProfile = (token, config) => {
  const missing = missingBearer(token);
  if (missing) return missing;
  return historyApi.get('/history/profile', {
    ...config,
    headers: bearerHeaders(token, config),
  });
};

/** Public — revoke the presented bearer server-side (idempotent). */
export const signOutHistory = (token, config) => {
  const missing = missingBearer(token);
  if (missing) return missing;
  return historyApi.post('/history/sign-out', null, {
    ...config,
    headers: bearerHeaders(token, config),
  });
};

export default historyApi;
