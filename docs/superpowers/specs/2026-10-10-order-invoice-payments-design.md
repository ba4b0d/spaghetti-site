# Spaghetti Print: reviewed orders, shareable invoices, and payments

## Scope and decision

One commerce flow with two intake paths: (A) catalog cart requests, and (B) staff-created orders from Telegram/Bale/phone. Color, size, and custom text are finalized by staff in messenger, not required in the cart. No customer account or OTP in v1. Existing admin authentication remains mandatory for invoice creation and approval. DigiPay is merchant-approved; BitPay and SnappPay remain disabled until individually approved and integrated. Never display a disabled method as payable.

## Customer request and cart

Public catalog/product detail has accessible add-to-cart actions; a persistent cart stores only product IDs and quantities, not authoritative prices. Checkout collects name, Iranian mobile, preferred Telegram/Bale channel and handle (optional if phone contact is possible), optional initial note and shipping contact/address. A submission records a pending-review request and item snapshots from active catalog products; any displayed catalog price is explicitly an estimate. Server enforces product validity, quantity and payload limits, rate limiting, and does not trust client-supplied prices. It returns an opaque receipt identifier, not an invoice payment URL. Confirmation says the team will finalize options and price in chat. Keep existing custom-order/upload flow separate.

## Staff-created orders and approval

Staff can create a draft invoice from the existing Orders board using catalog products or custom line items with positive integer-Toman prices. Staff can convert a website request into a reviewed invoice, edit line items, price, shipping charge and finalized specification notes after messenger discussion. Do not silently change a customer's payable invoice; revisions invalidate prior payment attempts and issue a fresh invoice link. Approval is a separate authenticated action that freezes item, price, shipping and customer snapshots and issues a cryptographically random bearer link with expiry. Staff can revoke and regenerate the link. New website requests do not become payable automatically. Existing admin order-board statuses and accounting must not be confused with payment state: review/payment state is separate and explicit.

## Public invoice and payment

`/pay/:token` shows only necessary customer-visible information (final items/specifications, price, shipping, validity and payment state), does not reveal admin notes or full contact details. Token is sufficiently random, hashed at rest, expires and can be revoked; rate-limit the public endpoints, avoid sensitive referrers and cache. A customer can initiate payment only for an approved, unexpired, unpaid invoice. Server computes payable total in integer Toman and converts to integer Rial exactly once at the gateway boundary. Create a durable payment attempt with unique merchant reference, immutable amount and provider. Repeated clicks/callbacks are idempotent; never allow double crediting. Redirect only to the verified DigiPay-supplied HTTPS payment URL.

DigiPay UPG adapter follows the official documentation: get bearer token from `/oauth/token`, request a business ticket at `/tickets/business?type=11` using `amount`, `cellNumber`, unique `providerId`, and `callbackUrl`, then redirect to `redirectUrl`. Depending on enabled product configuration, UPG can expose IPG/Wallet/Credit/BNPL; do not claim all merchant-enabled methods without a live test. DigiPay posts `result`, `amount`, `providerId`, `trackingCode`, `type` to the callback. Before calling `/purchases/verify?type=...`, compare callback identity and amount with the stored attempt and require success; verify with DigiPay server-to-server and record the verified reference only once. Failed, mismatched, forged, replayed or timed-out callbacks do not mark payment complete. A transient verification error leaves a recoverable pending/unknown attempt for staff reconciliation; do not claim paid. Use env secrets for auth and callback origin, never store secrets in DB, front-end bundle or git. No live request without production credentials and explicit deployment configuration.

BitPay and SnappPay are future payment adapters; no fake checkout or success state. DigiPay alone is selectable in v1.

## Notifications

A notification service emits events on request submission, invoice approval and confirmed payment. Telegram admin message carries order ID, source, items and contact channel. SMS.ir sends short admin alerts to a configured phone with an approved template/API key; SMTP sends a concise admin email to a configured mailbox. Each channel is independently configurable and failures are logged without losing the committed order. Public launch must disclose channel availability accurately: missing SMS/SMTP credentials or unapproved templates disable that channel rather than imply it works. Customer invoice link can be copied into Telegram/Bale; optional SMS to customer only if configured, with an approved service template. Avoid leaking a bearer payment link into logs. No OTP in v1; future OTP can be added without changing the invoice identity model.

## Data and interfaces

Use dedicated commerce request, invoice, invoice-line, and payment-attempt records (or carefully scoped additions to existing order models) with explicit state transition rules. Link paid invoices back to the existing Orders board exactly once; avoid duplicating existing order revenue. Keep historical/manual orders intact and perform additive migrations for SQLite. Server is authoritative for status, totals and timestamps. Public endpoints return minimal data; staff endpoints require existing RBAC/CSRF protections. Schema must preserve exact totals in integer minor units and never use floating-point math for payment amounts.

## Tests and acceptance

Backend tests cover inactive/deleted product, price tampering, abusive payload and rate limit, staff-only actions, editing/approval/revision/revocation/expiry, unit conversion, callback mismatch/replay/concurrency, provider errors and idempotent order accounting. Mock DigiPay/SMS/SMTP/Telegram; do not touch live providers in tests. Frontend tests cover add/remove/quantity persistence, request form and disabled pay until approval, manual invoice editing, share/copy link, invoice expiry/failure/paid states and RTL accessibility. Build and run existing suites; manually smoke-test a local end-to-end flow with simulated provider. A real DigiPay sandbox/live payment is a separate acceptance check once merchant test credentials and callback configuration are supplied securely. Do not deploy to production or issue real SMS/payment requests from development without explicit configuration.

## Delivery sequence

1. Cart, customer request and notification event on submission.
2. Staff draft/manual invoice creation, review, approval and link lifecycle.
3. Public invoice page and DigiPay UPG adapter with durable verification.
4. Multi-channel notifications, full automated tests and local end-to-end smoke test.

This is four workstreams, not four independent isolated changes: each later stage consumes state and interfaces from the preceding stage. Implement serially with a fresh worker and review per task, then whole-branch review.

## Primary source

DigiPay UPG: https://www.mydigipay.com/developers/docs/upg/ — login, ticket, POST callback and purchase verification sections. SMS.ir: https://sms.ir/web-service/ — verification-pattern API; non-OTP notification method/template is to be validated against the current SMS.ir dashboard/docs before enabling live sends.
