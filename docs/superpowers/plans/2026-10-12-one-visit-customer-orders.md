# One-Visit Customer Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer verify an SMS code and view their own website requests and staff-created invoices, items, and server-owned statuses for one short tab-scoped visit.

**Architecture:** Separate history-purpose OTP challenges from checkout OTP, issue a 30-minute revocable server-side session keyed by a hash of a random bearer, and authorize every history read by that session's exact canonical mobile. Present bounded, redacted history through an RTL storefront page using tab-only sessionStorage; never derive payment authority from history or recreate a hashed invoice payment link.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, slowapi, pytest/TestClient; React 18, Axios, React Router, Vitest/Testing Library, Tailwind.

**Spec:** `docs/superpowers/specs/2026-10-12-one-visit-customer-orders-design.md`

## Global Constraints

- No persistent customer account, password, cookie, remembered device or customer login.
- A history OTP must not verify or consume a checkout OTP; rate limits on both flows must not be bypassed by alternating flows.
- The raw history bearer lives only in `sessionStorage` and an `Authorization: Bearer` header, never URLs, logs, localStorage, analytics or a service-worker cache. Server stores only a SHA-256 token hash; absolute TTL 30 minutes.
- No public response may reveal existence of orders for an unverified phone. Never expose internal notes, full address, messenger handle, gateway details or private invoice tokens.
- Only an existing, approved, nonexpired private invoice bearer authorizes payment; history is read-only. Paid means persisted server-verified settlement, not a redirect hint.
- Fail closed when SMS cannot deliver. Deploy only after SMS delivery and edge no-log behavior are verified. Use the backend project's existing test environment and never send real SMS or reach live payment gateways in tests.
- User-approved UI remains Persian/RTL with Vazirmatn, soft-blue/orange storefront theme. Touch no unrelated untracked files; stage explicit paths only. Do not deploy merely because tests pass.

## File map

- `backend/app/models.py`: `CommerceHistoryOtpChallenge` and `CommerceHistorySession` models only; no changes to existing checkout columns or invoice token storage.
- `backend/app/services/commerce_history_auth.py`: history-purpose OTP issuance/verification, hashed token, session lookup and revoke. May extract a private shared throttle counter from checkout service if necessary to prevent cross-purpose SMS cap bypass; keep checkout's external API unchanged.
- `backend/app/services/commerce_history.py`: exact-mobile redacted history query/serialization, bounded pagination and safe state mapping.
- `backend/app/routers/commerce_history.py`: four thin public routes under `/api/v1/commerce/history`; request-first slowapi handlers, no-store even on errors.
- `backend/app/main.py`: register the history router as public; `Base.metadata.create_all` already creates added tables on startup.
- `backend/tests/test_commerce_history_auth.py`, `backend/tests/test_commerce_history.py`: TDD for authentication and history/privacy.
- `frontend/src/lib/commerceHistoryApi.js`: purpose-built Axios requests with explicit Bearer header; no admin 401 redirect.
- `frontend/src/lib/commerceHistorySession.js`: safe per-tab token access with expiry, no persistent storage.
- `frontend/src/pages/CustomerOrders.jsx`: phone/OTP/list/empty/expiry/sign-out view; never retain sensitive history after sign-out.
- `frontend/src/App.jsx`, `frontend/src/components/CatalogLayout.jsx`: route `/my-orders` and storefront entry.
- `frontend/public/sw.js`, `frontend/nginx.conf`: ensure history UI/API never cached, no-store/security headers for route and avoid personal query strings; test nginx syntax.
- `frontend/src/__tests__/pages/CustomerOrders.test.jsx`, `frontend/src/__tests__/lib/commerceHistorySession.test.js`: lifecycle and safe-copy tests.

## Task 1: History-only OTP and tab session backend

**Files:** create `backend/app/services/commerce_history_auth.py`, `backend/tests/test_commerce_history_auth.py`; modify `backend/app/models.py`, and only if needed `backend/app/services/commerce_otp.py` to share SMS send quotas. This task exposes a service API, no public route yet.

**Interfaces:** `issue_history_challenge(db: Session, mobile: str, *, client_ip: str|None) -> CommerceHistoryOtpChallenge`; `verify_history_challenge(db: Session, challenge_id: int, code: str, mobile: str) -> tuple[str, datetime]` (commits OTP claim + hashed session atomically); `resolve_history_session(db: Session, bearer: str) -> str|None` returns canonical mobile; `revoke_history_session(db: Session, bearer: str) -> None` idempotent. Define `HistoryOtpThrottled`, `HistoryOtpDeliveryError`, `HistoryOtpInvalid`. Models have `mobile`, salted code hash, expiry, consumed_at, attempts, client_ip_hash, creation time; session has unique `token_hash`, mobile, expires_at, revoked_at, creation time. Use 32 random bytes, `secrets.token_urlsafe(32)`, and SHA-256 only of token; `hmac.compare_digest` for code. Session TTL = `timedelta(minutes=30)`.

- [ ] Write failing tests in `backend/tests/test_commerce_history_auth.py`: issue produces hashed code and SMS fake, returns no code; wrong code increments/exhausts attempts; second verification of same challenge fails; checkout challenge ID cannot authenticate history and history challenge cannot authorize `/requests`; one valid verify returns bearer whose hash resolves to exact mobile; revoke and expiry invalidate; simultaneous claims yield one session; delivery failure issues no usable challenge. Patch `commerce_notifications.send_customer_otp` and reset slowapi limiter; use `tests.conftest.TestSessionLocal` fixture conventions.
- [ ] Run `env -u PYTHONPATH backend/venv/Scripts/python.exe -m pytest backend/tests/test_commerce_history_auth.py -q` and record RED (module/model absent), not an infrastructure error.
- [ ] Implement separate challenge/session models and service with serialized issue throttle and atomic conditional claim as in `commerce_otp.py:135-226,229-352`, but **do not import `verify_challenge` for history**: a purpose bypass is unacceptable. Validate canonical mobile exactly (`len=11`, `startswith('09')`, ASCII digits). On failed SMS, invalidate/delete challenge; on success generate token and add session in the same transaction as the OTP consumption before returning it. Limit resend 60 seconds, 5 sends/hour/mobile, 20 sends/hour/IP, 5 wrong attempts, 300-second code TTL; count sends across both challenge tables (or a shared throttle ledger) before issuing either purpose. Use SQLite `BEGIN IMMEDIATE` for check/insert and guarded UPDATE for consume. Wrong-attempt accounting must commit even when verify fails. Never log code/token/mobile.
- [ ] Re-run the focused tests GREEN, then existing `backend/tests/test_commerce_otp.py` to prove checkout stays functional. Commit explicitly these file paths with `feat(commerce): isolate history OTP and short sessions`.

## Task 2: Authorized redacted history query and HTTP boundary

**Files:** create `backend/app/services/commerce_history.py`, `backend/app/routers/commerce_history.py`, `backend/tests/test_commerce_history.py`; modify `backend/app/main.py` to include the router.

**Interfaces:** `list_history(db: Session, mobile: str, *, limit: int, offset: int) -> list[dict]` returns newest-first composite entries `{kind, id, request_id, state, created_at, items, shipping_toman?, total_toman?}`. Endpoints: `POST /api/v1/commerce/history/otp` `{mobile}` → `{challenge_id, expires_in, resend_after, delivery, masked_mobile}`; `POST /api/v1/commerce/history/verify` `{mobile, challenge_id, code}` → `{token, expires_at}`; `GET /api/v1/commerce/history?limit=20&offset=0` → `{items, has_more}`; `POST /api/v1/commerce/history/sign-out` → `{ok:true}`. GET/sign-out require `Authorization: Bearer <token>`; invalid/expired/revoked token returns 401, never staff cookie auth. Body models `extra='forbid'` and valid ASCII Iranian mobile; no phone as query/path. Limit `1..50`, offset `>=0` capped reasonably; fetch `limit+1` to derive has_more. Specify stable global ordering by `created_at DESC, kind, id DESC` and test ties.

- [ ] Write failing API tests: no header/malformed header/expired session → 401 and no details; normal issue/verify/read; another number's request/invoice is not returned; staff-created Telegram/Bale invoice is visible; linked request+invoice appear as related entries without duplicating invoice; draft/revoked have no final totals or payment action, approved/paid totals and item snapshots are correct; internal notes/full address/handle/provider IDs/token hashes absent; no raw link generated; pagination has no repeats; 404 versus empty-number history does not disclose before OTP; all success and error responses carry `Cache-Control: no-store` and `Referrer-Policy: no-referrer`; transport 503 fails closed. Use fake SMS, no real credentials.
- [ ] Run `env -u PYTHONPATH backend/venv/Scripts/python.exe -m pytest backend/tests/test_commerce_history.py -q` to see RED (route absent).
- [ ] Implement serializer with explicit **allowlisted** fields rather than model `__dict__`. Query both tables by exact mobile, bound SQL result size, merge/sort/paginate deterministically (do not load entire history into Python). Use SQL UNION ALL projected IDs/timestamps and load only page rows with their snapshot items. Only invoice states `approved`/`paid` may carry finalized monetary fields; `state=='paid'` comes from DB only. Do not include raw link or payment URL. Verify no-store on FastAPI validation errors/429 too (router-level middleware or exception-safe response handling). Apply slowapi: first handler argument must be `request: Request`; issue 3/min, verify 5/min, history read 30/min. Authenticate only with explicit Authorization header, not a cookie.
- [ ] Run focused backend tests plus `test_commerce_otp.py`, `test_commerce_requests.py`, `test_commerce_invoices.py` serially; resolve root causes. Commit explicit paths as `feat(commerce): expose verified customer order history`.

## Task 3: Tab-only history client and one-visit UX

**Files:** create `frontend/src/lib/commerceHistoryApi.js`, `frontend/src/lib/commerceHistorySession.js`, `frontend/src/pages/CustomerOrders.jsx`, `frontend/src/__tests__/pages/CustomerOrders.test.jsx`, `frontend/src/__tests__/lib/commerceHistorySession.test.js`; modify `frontend/src/App.jsx`, `frontend/src/components/CatalogLayout.jsx`, `frontend/public/sw.js`, `frontend/nginx.conf` and relevant existing config tests.

**Interfaces:** `requestHistoryOtp({mobile})`, `verifyHistoryOtp({mobile,challenge_id,code})`, `getCustomerHistory(token,{limit,offset})`, `signOutHistory(token)` on separate commerce API module, no global Axios default Authorization; `readHistorySession() -> {token,expiresAt}|null`, `writeHistorySession(token,expiresAt) -> boolean`, `clearHistorySession() -> void`. `CustomerOrders` uses these functions and labels from server-owned states.

- [ ] Write failing Vitest tests: OTP request/verify flow and mocked API, focus/input errors and rate limit, first-page load and next-page boundary, website request and manual invoice item/status cards, approved invoice no pay CTA (link unreconstructable), no persistent storage, stale session falls back to OTP, 401 clears session/data, sign-out invokes server and wipes data even if network fails, back navigation does not restore old history, phone never appears in URL, no query-hint payment claims. Test storage unavailable exceptions and expiration. Test SW bypass for `/my-orders` case-insensitively.
- [ ] Run `cd frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run --no-file-parallelism src/__tests__/pages/CustomerOrders.test.jsx src/__tests__/lib/commerceHistorySession.test.js` for RED.
- [ ] Implement `CustomerOrders` with RTL semantics, labels `pending_review`, `converted`, `draft`, `approved`, `paid`, `revoked` and unknown neutral fallback; render approved/paid frozen totals and request/other invoice item names/quantities only. Use `useEffect` cleanup/AbortController on history fetch; clear in-memory history immediately on 401/sign-out. Only sessionStorage (`'spaghetti:history:session'`) holds bearer; no localStorage/cookies, no query parameters. Cache-Control: no-store for `/my-orders` HTML and bypass SW cache for page/API; use no-referrer on page. Keep theme and keyboard/error accessibility patterns from `CheckoutRequest.jsx`/`CatalogLayout.jsx`.
- [ ] Re-run focused tests GREEN, then full frontend Vitest serial and `npm run build`; run nginx config tests. Commit explicit file paths as `feat(storefront): add one-visit My Orders page`.

## Task 4: Security/release gate

**Files:** change only defects actually found by verification; preserve above task boundaries. Deployment is a distinct approval gate.

- [ ] Run bounded combined backend `env -u PYTHONPATH backend/venv/Scripts/python.exe -m pytest backend/tests/test_commerce_history_auth.py backend/tests/test_commerce_history.py backend/tests/test_commerce_otp.py backend/tests/test_commerce_requests.py backend/tests/test_commerce_invoices.py -q` and serial frontend suites/build. Never run colliding DB tests in parallel.
- [ ] Have an **independent reviewer** inspect OTP purpose isolation, shared SMS quotas, concurrency, phone ownership, session revocation, cache/access logs, staff-only field omissions, pagination, no pay-token issuance, and UI session expiry. Fix blockers through RED→GREEN tests; re-review before release.
- [ ] Verify deployment preconditions on staging: SMS delivery with a real number only with user coordination; edge access logs do not record Authorization headers/mobile; API and `/my-orders` no-store/no-referrer; unknown mobile yields indistinguishable empty session after OTP; confirm live SMS.ir credential and balance. Do not claim activation until these gates actually pass.
- [ ] Only after explicit release approval, deploy reviewed commit with existing Docker workflow and read back live site, newly registered API behavior, disabled DigiPay and BitPay readiness. Avoid any live charge or SMS during automated checks. Keep a rollback commit/backup reference.

## Spec coverage/self-review

- Entry/session: Tasks 1 and 3. Exact ownership, staff-created invoice, pagination/privacy: Task 2. Payment-link boundary: Tasks 2 and 3. Failures/test/release: Task 4. No requirement depends on recovering a discarded invoice bearer; the history page intentionally has no pay CTA.
- The frontend API contract is given in Task 2, read by Task 3. Each task has its own RED/GREEN test cycle and explicit commit paths.
- One-visit means tab-scoped best effort plus server TTL: browser session restore can preserve sessionStorage; don't promise strict tab-close revocation without an explicit sign-out.
