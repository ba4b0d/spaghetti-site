/**
 * Commerce HTTP client.
 *
 * Deliberately a SEPARATE Axios instance from the admin client in lib/api.js:
 * the admin client force-redirects any 401 to /login, which would be wrong for
 * anonymous storefront visitors (e.g. a failing public cart request must render
 * an inline error, not bounce the visitor to the staff login).
 */
import axios from 'axios';

const commerceApi = axios.create({
  baseURL: '/api/v1/commerce',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Propagate errors untouched — no login redirect for public visitors.
commerceApi.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);

/** Public — submit a website cart request (returns { receipt_id, state }). */
export const submitCommerceRequest = (payload, config) =>
  commerceApi.post('/requests', payload, config);

/** Staff — newest-first request review queue (requires staff session). */
export const getStaffRequests = (config) => commerceApi.get('/staff/requests', config);

export default commerceApi;
