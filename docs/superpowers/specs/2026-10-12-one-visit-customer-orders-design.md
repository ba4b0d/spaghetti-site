# One-visit customer order history — design

## Goal and scope

A customer verifies ownership of an Iranian mobile number with SMS and sees requests and invoices associated with **that exact number**, including staff-created Telegram/Bale invoices. No customer account, password, or persistent login. This is separate from the BitPay payment-result receipt improvement. The existing staff-reviewed invoice remains the only payable artifact; a request cannot be paid directly.

## Entry and session

Add a public «سفارش‌های من» page reachable from the storefront. The visitor enters their mobile, receives a one-time SMS code, and submits it. Reuse the existing SMS delivery and throttle primitives, but distinguish the history-purpose challenge from checkout OTP so history verification cannot consume a checkout challenge or vice versa. No response discloses whether the number has orders. Codes are short-lived, single-use, hashed at rest, attempt-limited and issuance-limited per number and IP. On successful verification, issue a cryptographically random, server-stored **hashed** session token bound to the canonical mobile, valid for at most 30 minutes. Store the raw token **only in tab-scoped sessionStorage**, not localStorage/cookies/URLs, and send it in an Authorization header over HTTPS. Tab close loses access; the server TTL limits replay of a copied token. Show a sign-out action that revokes the session server-side and removes the tab token. Never put the token or mobile in a URL, log entry, analytics event, or referrer. All history API responses carry no-store; the UI does not cache personal data in service worker or persistent storage. Where a browser restores a closed tab's sessionStorage, server expiry still applies; a strict per-tab-close guarantee is not possible across all browser session-restore behaviors, so describe access as tab-scoped and time-limited, not a lifetime guarantee.

## Data and authorization

A single-purpose public history service resolves the verified session to its mobile, then queries `CommerceRequest.mobile` and `CommerceInvoice.mobile` with exact canonical equality, ordering newest first with bounded pagination. Each invoice is included once even if it references a website request; display that relationship rather than counting duplicate orders. No cross-number access through path parameters; IDs in responses are display IDs only, never authorization credentials. Staff-created invoices with a matching mobile appear, including drafts with their **customer-safe** status, but draft totals/specifications are not presented as final. Exclude internal notes, staff actions, raw OTP, gateway identifiers, provider response, full address and messenger handle. Return snapshots of customer-visible item names/quantities; approved/paid invoices may show frozen item prices, shipping and total. Keep server-owned status mapping (`pending_review`, `converted`, `draft`, `approved`, `paid`, `revoked`) and a neutral label for unknown states; never infer payment success from gateway redirect query parameters.

## Payment links and lifecycle

A history session grants read access to that mobile's history, **not** payment authority. Existing invoice payment links remain separate high-entropy bearer credentials and existing approval/expiry/revocation rules stay intact. Because only `token_hash` is persisted, the server cannot reconstruct a previously issued raw invoice link. For an approved invoice whose raw link is unavailable, show «برای دریافت لینک پرداخت با پشتیبانی تماس بگیرید» rather than generating a token silently or putting a new token into history JSON. An explicit future staff-controlled reissue flow can be separately designed if necessary. Revoked/expired invoices have no pay CTA. Paid status comes only from persisted server-verified settlement. SMS availability is a deployment precondition; if SMS delivery fails, no history session is issued and no order data is shown.

## Interfaces and failure modes

Backend: dedicated history OTP issue/verify, history list, and sign-out routes; separate history-purpose challenge/session state. Validate Iranian phone format and canonicalize before lookup. Rate-limit issue/verify/read; make verify/code consumption atomic and session creation committed together. Return generic errors for unknown number, wrong/expired code, and no history. Session auth failure clears client token and returns to the verification screen. Frontend: RTL responsive verification view, loading/error/empty states, grouped request/invoice cards with statuses, item snapshots, totals where final, and explicit sign-out. Keep invoice history behind a no-store API and avoid browser/back-forward stale data after sign-out. Reuse current catalog typography/theme and accessibility patterns.

## Verification and rollout

TDD backend tests for OTP isolation from checkout, throttle and concurrent single-use behavior, exact-mobile ownership and cross-number denial, staff-created invoice inclusion, pagination, privacy redaction, expiry/revocation, and no-store. Frontend tests for verified/empty/expired/sign-out flows, status labels and no payment CTA without a valid link. Independent security review before deployment; staging SMS provider and edge log checks, then production deployment with fail-closed verification. Do not launch until SMS transport can deliver reliably; current SMS credential/balance issues may block customer use.

## Out of scope

Password/customer account, persistent login or remembered device, profile edits, address book, arbitrary invoice reissue, changing BitPay settlement, and granting payment authority from OTP history alone.
