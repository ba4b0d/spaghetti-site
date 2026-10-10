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

/** Staff — paginated, newest-first request review queue (requires staff session). */
export const getStaffRequests = (params = {}, config) =>
  commerceApi.get('/staff/requests', { params, ...config });

// ── Staff invoices (Task 2) ──────────────────────────────────────────
//
// All staff invoice calls require the existing staff session cookie; the
// private share link is only ever returned by `approveStaffInvoice`, and the
// frontend must never auto-forward it to a messenger — staff copy it manually.

/** Staff — paginated, newest-first invoice queue. */
export const getStaffInvoices = (params = {}, config) =>
  commerceApi.get('/staff/invoices', { params, ...config });

/** Staff — create a draft invoice (manual or linked to a website request). */
export const createStaffInvoice = (payload) =>
  commerceApi.post('/staff/invoices', payload);

/** Staff — revise a non-settled invoice (drops to draft, invalidates the link). */
export const updateStaffInvoice = (id, payload) =>
  commerceApi.put(`/staff/invoices/${id}`, payload);

/** Staff — freeze the invoice and mint a one-time private share link. */
export const approveStaffInvoice = (id) =>
  commerceApi.post(`/staff/invoices/${id}/approve`);

/** Staff — invalidate the private share link. */
export const revokeStaffInvoice = (id) =>
  commerceApi.post(`/staff/invoices/${id}/revoke`);

export default commerceApi;
