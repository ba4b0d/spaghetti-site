# Reviewed Checkout, Invoices and DigiPay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept storefront cart requests and staff-created messenger invoices, requiring staff approval before DigiPay payment and notifying staff on key events.

**Architecture:** New commerce records represent website requests, reviewed invoices and immutable payment attempts; existing shop Orders remain the fulfillment/accounting board and are linked to a paid invoice once. Public APIs never trust client prices; staff APIs freeze an invoice, create a private expiring token, and may revise/revoke it. DigiPay UPG is the sole enabled payment adapter, its POST callback is verified against stored amount/reference before server-to-server confirmation.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, Pydantic, pytest/TestClient, React 18, React Router, Axios, Vitest/Testing Library; Python stdlib secrets/hashlib/smtplib, httpx if already installed.

**Spec:** `docs/superpowers/specs/2026-10-10-order-invoice-payments-design.md`

## Global Constraints

- Color, size, and custom text are finalized in Telegram/Bale, not required at cart time.
- No customer account or OTP in v1; admin invoice actions use existing staff auth.
- DigiPay only in v1; BitPay and SnappPay remain unavailable, never fake success.
- Currency in commerce tables is integer Toman; multiply by 10 exactly once for DigiPay Rial. Never use floating point to compute payment amounts.
- Invoice bearer tokens are random, hashed at rest, expiring and revocable; redact sensitive details from public responses, logs and referrers.
- Callback POST is untrusted; compare result, providerId, amount, type and stored attempt before DigiPay server-side verify. Replay cannot double-credit.
- Failures in optional notifications do not lose committed orders; missing credentials disable delivery rather than pretend to succeed.
- Additive SQLite schema/migrations; do not erase existing Orders or tests. Do not edit existing untracked files.
- No live payment/SMS/email requests in development; use mocked providers. Secrets from `C:/Users/barba/OneDrive/Desktop/local gtw.txt` only to authenticate OpenCode local gateway, never print or copy to project.

## File responsibilities and interfaces

- `backend/app/models.py`: CommerceRequest, CommerceRequestItem, Invoice, InvoiceItem, PaymentAttempt relational models; `Invoice.order_id` unique link to legacy Orders.
- `backend/app/routers/commerce.py`: public create request/get invoice/pay initiation, staff request/list/draft/edit/approve/revoke; thin handlers calling service.
- `backend/app/services/commerce.py`: input validation, state transitions, snapshots, totals and token handling; explicit functions consumed by router.
- `backend/app/services/digipay.py`: external login/ticket/verify adapter; bounded timeouts, secrets from env.
- `backend/app/routers/digipay_callback.py`: callback parsing, mismatch validation, server verification and exactly-once settlement.
- `backend/app/services/commerce_notifications.py`: Telegram/SMS.ir/SMTP delivery isolated from transaction.
- `frontend/src/lib/commerceApi.js`: public and staff HTTP calls using same-site Axios; public 401 must not force login.
- `frontend/src/lib/cart.js` and `frontend/src/components/CartDrawer.jsx`: persistent product-ID/quantity cart, accessible controls.
- `frontend/src/pages/CheckoutRequest.jsx`, `frontend/src/pages/InvoicePayment.jsx`, `frontend/src/pages/CommerceAdmin.jsx`: request intake, private invoice/payment and staff review/editor respectively.
- `frontend/src/App.jsx`, `CatalogLayout.jsx`, `Catalog.jsx`, `PublicProductDetail.jsx`: routes, cart link and add buttons; preserve approved storefront design.
- Tests: new `backend/tests/test_commerce*.py`, `frontend/src/__tests__/commerce*.test.jsx`, and concise env/deployment instructions.

## Task 1: Persist website cart requests and add public cart/checkout

**Files:** Create commerce models/service/router (request portion), `frontend/src/lib/cart.js`, `frontend/src/lib/commerceApi.js`, CartDrawer and CheckoutRequest; modify `backend/app/main.py`, `frontend/src/App.jsx`, `CatalogLayout.jsx`, `Catalog.jsx`, `PublicProductDetail.jsx`; add backend/frontend tests.

**Interfaces:**
- `POST /api/v1/commerce/requests` JSON `{customer_name,mobile,messenger,messenger_handle?,address?,note?,items:[{product_id,qty}]}` -> `{receipt_id,state:'pending_review'}`; no invoice link.
- `GET /api/v1/commerce/staff/requests` requires staff; returns ordered requests with snapshots.
- `CommerceRequest` states `pending_review`, `converted`, `cancelled`; `CommerceRequestItem` stores product ID, display name, qty, optional integer indicative price.
- `cart.js`: `addItem(id, qty)`, `updateQuantity(id, qty)`, `removeItem(id)`, `readCart()` persist only IDs and qty; React state integration may wrap these.

- [ ] **Step 1: Write failing backend tests** for guest submission, price-tampering ignored, inactive/missing product, invalid phone/quantity, huge note/items and unauthenticated staff listing. Example:
```python
r = client.post('/api/v1/commerce/requests', json={
  'customer_name':'رضا', 'mobile':'09123456789', 'messenger':'telegram',
  'items':[{'product_id': product.id, 'qty':2, 'unit_price':1}]})
assert r.status_code == 200 and r.json()['state'] == 'pending_review'
assert 'payment_url' not in r.json()
```
Run `backend/venv/Scripts/python.exe -m pytest backend/tests/test_commerce_requests.py -q` from repo root with `PYTHONPATH=backend` (or `cd backend` and clear polluted PYTHONPATH). Expected red: route missing.
- [ ] **Step 2: Implement** additive model/table creation via existing `Base.metadata.create_all` lifespan. Pydantic constraints: name 1..120, mobile `09`+9 digits, messenger `telegram|bale`, handle ≤100, note ≤2000, address ≤500, 1..30 distinct product IDs and qty 1..99. Disallow surplus fields on public payload to avoid silent price acceptance. Query only active products and snapshot names. Apply `@limiter.limit('5/minute')` with `request: Request` on public POST; after commit emit notification in Task 4. Staff listing protected with `require_staff_role`.
- [ ] **Step 3: Run backend tests green** and commit only Task 1 backend paths.
- [ ] **Step 4: Write failing frontend tests** for cart add/quantity/removal/localStorage reload, checkout submit and server-error state. Run `npm test -- --run src/__tests__/commerceCart.test.jsx` in `frontend` (adapt Vitest exact file path); expected red.
- [ ] **Step 5: Implement frontend** cart drawer/header trigger, add buttons on catalog grid/detail, checkout form and confirmation. The cart is not an authoritative price source. Use existing RTL style and accessible button names. Expose API functions without disturbing admin Axios interceptor for public calls (separate instance or guarded 401). Persist cart only after successful user action, clear only after request success.
- [ ] **Step 6: Run frontend tests and `npm run build` green; commit Task 1 frontend paths.**

## Task 2: Staff draft/review, manual invoices and private links

**Files:** Extend models/service/router; create `frontend/src/pages/CommerceAdmin.jsx`; modify `frontend/src/App.jsx` and admin navigation (find Layout component); add tests.

**Interfaces:**
- Staff `POST /api/v1/commerce/staff/invoices` accepts `{request_id?, customer_name,mobile,messenger?,items:[{product_id?,description,qty,unit_toman}],shipping_toman,specification}`; `request_id` links site requests, omitted for chat/manual orders.
- Staff `PUT /api/v1/commerce/staff/invoices/{id}` edits only draft/reviewed (not paid) invoice; invalidates existing link and previous pending attempts.
- Staff `POST /api/v1/commerce/staff/invoices/{id}/approve` -> `{id,state:'approved',share_url,expires_at}`; `share_url` uses configured `PUBLIC_SITE_ORIGIN` (validated HTTPS in production), raw token returned only here.
- Staff `POST /api/v1/commerce/staff/invoices/{id}/revoke`; staff `GET /api/v1/commerce/staff/invoices`; `GET /api/v1/commerce/invoices/{token}` returns minimal invoice data, never raw contact/address or internal notes.
- Invoice states `draft`, `approved`, `paid`, `revoked`; revision returns to draft and increments revision. `InvoiceItem` snapshots description/qty/unit_toman. `Invoice` stores `token_hash`, expiry, `total_toman`, `shipping_toman`, unique `order_id` nullable, optional request link; links expire after 7 days.

- [ ] **Step 1: Write failing backend tests**: staff-only create/edit/approve/revoke, website conversion, manual custom item, exact integer totals, zero/negative/overflow rejection, token not stored in plaintext, revoked/expired link 404 or 410, revision invalidates old token, no customer PII in public response, paid edit rejected. Example:
```python
approved = staff.post(f'/api/v1/commerce/staff/invoices/{invoice_id}/approve').json()
assert approved['share_url'].startswith('https://spaghettiprints.ir/pay/')
assert guest.get('/api/v1/commerce/invoices/'+approved['share_url'].split('/')[-1]).status_code == 200
```
Run targeted pytest; expected red.
- [ ] **Step 2: Implement** token via `secrets.token_urlsafe(32)` and `hashlib.sha256(raw.encode()).hexdigest()`; schema unique index on token hash, expiry UTC, manual revision revokes old link; no weakening existing RBAC. Reject edits while active payment attempt is in-flight until its outcome is reconciled; staff may revoke/reissue after expiry/failure. Money sums integer, maximum bounded according to provider limits and application requirements (e.g. total ≤50,000,000 Toman; enforce at both staff and payment transition).
- [ ] **Step 3: Run backend tests green and commit.**
- [ ] **Step 4: Write failing frontend tests** for manual draft with custom line, converting request to invoice, approve/share/copy, re-edit invalidates link and clear paid/revoked states.
- [ ] **Step 5: Implement staff page/navigation** separate from legacy Orders board but with a clear link from it, or integrate compact invoice tab if existing board layout supports it. Copy link after approval; never auto-send to Telegram/Bale (staff pastes it into established conversation).
- [ ] **Step 6: Run frontend tests/build and commit.**

## Task 3: Public invoice payment and verified DigiPay UPG adapter

**Files:** Create `backend/app/services/digipay.py`, `backend/app/routers/digipay_callback.py`, extend commerce service/router and `main.py`; create `frontend/src/pages/InvoicePayment.jsx`, add route; update env example; tests.

**Interfaces:**
- `POST /api/v1/commerce/invoices/{token}/pay` creates `PaymentAttempt(provider='digipay', state='initiating|pending|verified|failed|unknown', provider_id=unique, amount_rial=invoice.total_toman*10, invoice_revision=...)` and returns `{redirect_url}` on successful ticket. Valid only for approved, unexpired, unpaid invoice.
- `POST /api/v1/commerce/digipay/callback` consumes DigiPay form POST; returns a safe redirect to `/pay/{token}?payment=...` or server-rendered success/failure; never trusts query state for success.
- DigiPay client: `login()`, `create_ticket(amount_rial, mobile, provider_id, callback_url)`, `verify(tracking_code, provider_id, type)` with HTTP timeouts, auth refresh on 401 and strict response checks. Base URLs live `https://api.mydigipay.com/digipay/api`, staging `https://uat.mydigipay.info/digipay/api` via explicit env; no arbitrary client URL. Headers per docs `Agent: WEB`, `Digipay-Version: 2022-02-02`.
- On confirmed verify, atomically mark attempt verified and invoice paid; create/link exactly ONE legacy `Order`+`OrderItem` representation with paid_amount equal confirmed Toman total; optional notifications Task 4. Callback might not provide token; resolve attempt via unique provider_id, then redirect via appropriate public confirmation route without exposing token in logs.

- [ ] **Step 1: Write failing provider/unit tests** with httpx mocks or dependency-injected fake HTTP client for OAuth token, ticket type=11, expected `redirectUrl` host/HTTPS, POST callback success with matching providerId/amount/type, verify API success, mismatch, duplicate callback, transient verify error, repeated pay clicks, expired token and concurrency. Run targeted pytest; expected red.
- [ ] **Step 2: Implement provider adapter** using official UPG docs linked in spec. Interpret documented verify response status and types exactly; no invented success codes. Authenticate with Basic(client_id:client_secret), form username/password/grant_type=password. Callback URL from server config only. `amount` stored as int Rial; never derive from client. Persist pending attempt before network request and ticket/redirect after response; make start idempotent while pending, and handle network failure as recoverable unknown. Restrict gateway redirect to DigiPay-controlled HTTPS hosts (distinct UAT/live).
- [ ] **Step 3: Implement callback verification/settlement** with transaction and uniqueness constraints. Compare signed? DigiPay docs show POST without signature: treat callback as untrusted, require server verification; compare amount and providerId and known type, refuse result FAILURE. Settle exactly once, even on replay. Model/DB uniqueness enforces one linked legacy order. Never blindly set `printing`; fulfillment remains staff-controlled `new`.
- [ ] **Step 4: Run provider tests green; commit backend.**
- [ ] **Step 5: Write failing frontend tests** for approved invoice DigiPay pay button, expired/revoked/paid views, gateway error and retry state; implement page/API route with `Referrer-Policy: no-referrer`, no unsafe data logging. Run tests/build; commit frontend.

## Task 4: Admin notifications, full verification and operational handoff

**Files:** Create `backend/app/services/commerce_notifications.py`, extend commerce transitions; env example and deployment README; add backend/frontend tests where appropriate.

**Interfaces:**
- `notify_admin(event, invoice_or_request)` runs after DB commit for `request_created`, `invoice_approved`, `payment_verified`; per-channel failure logged safely without raising to caller.
- Telegram uses existing `send_telegram_notification`; SMS.ir uses `POST https://api.sms.ir/v1/send/verify` with `x-api-key`, configured template IDs and mobile, only if configured/approved; SMTP over STARTTLS/SSL with env credentials for admin mailbox. Keep secrets out of exceptions and logs.

- [ ] **Step 1: Write failing notification tests**: all 3 channels called once on configured event, a failed channel does not roll back a committed invoice, no configured credentials means skip, duplicate callback produces only one paid alert, HTML escaping and phone/address minimization. Run targeted pytest red.
- [ ] **Step 2: Implement optional notifiers**; avoid requests to live services in tests. Use dedicated admin SMS template with approved parameters, check success response and only claim delivery on provider acknowledgement. SMTP config requires sender, recipient, host, port, credentials and TLS mode; no fallback to personal Gmail password. Telegram HTML-escape user content and never include private invoice token in admin broadcast. Make notification retry/visibility explicit (a durable outbox if test shows crash/window loss; otherwise admin can resend from UI).
- [ ] **Step 3: Run all targeted backend tests then entire backend suite; run `npm test`, `npm run build`, `npm run lint` in frontend.** Record counts, failures and baseline issues. Run a local TestClient smoke flow with fake DigiPay/SMS/SMTP: request → staff invoice → approve → public read → initiate → matching callback → one paid legacy order → duplicate callback unchanged; manual invoice same path. Never use real merchant credentials.
- [ ] **Step 4: Review security and ops**: confirm no secrets/raw tokens in git/logs, expiration/mismatch paths and DB migration on existing copy. Document DigiPay merchant env values/approved methods, callback endpoint, staging validation, SMS template setup and SMTP settings, operational reconciliation of unknown payments, BitPay/SnappPay disabled until separately integrated. Commit docs/tests/fixes. Request broad branch review before merge/deploy.

## Plan self-review

- Spec coverage: request intake Task 1; messenger invoices/approval Task 2; payment Task 3; notifications and E2E Task 4. OTP, BitPay and SnappPay intentionally absent from v1.
- Task coupling: Task 2 consumes Task 1 request IDs/models; Task 3 consumes Task 2 invoice token/state; Task 4 consumes Task 1-3 events. Implementation must be serialized, one worker per task.
- No production deployment, credentials or real payment implied by local tests.
