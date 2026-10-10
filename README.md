<p align="center">
  <img src="./assets/readme/hero.svg" width="100%"
       alt="Spaghetti — 3D printing pricing, catalog, blog CMS and workshop orders">
</p>

<div align="center">

**سیستم جامع مدیریت محصولات، قیمت‌گذاری و سفارشات چاپ سه‌بعدی اسپاگتی**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)](https://reactjs.org)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

## 🌟 Overview

**Spaghetti** is a modern, production-ready full-stack web application designed for 3D printing workshops (**FDM**). It combines an automated product pricing engine, public storefront catalog with mega-menu navigation, lightweight blog/CMS with SEO metadata, a Telegram order bot, and a real-time shop order tracking board.

---

## ✨ Key Features & Capabilities

- 🧮 **Real-time Cost Engine** — Material weight, support, flushed volume, power consumption, machine depreciation, maintenance, post-processing, overhead, and custom markup in a single formula.
- ⭐ **Default Printer & Filament** — Mark primary machines and filaments to auto-populate forms when creating new products.
- 📂 **Sub-categories & Mega-menu** — Hierarchical category tree with two-panel mega-menu dropdown on desktop and expandable accordion in mobile hamburger menu.
- 🛍️ **Public Catalog Storefront** — Hero section with CTA, product grid with images/prices/dimensions (cm), Telegram share buttons, category filtering via URL params.
- 🎨 **Custom Order Page** — Dedicated "سفارش طرح دلخواه" page with step-by-step flow for custom 3D print requests.
- 📝 **Blog & CMS Module** — Built-in article manager with cover image upload, Persian reading time, Telegram sharing, and structured `Article` JSON-LD schema for SEO. Dynamic on/off toggle via Settings.
- 🛒 **Workshop Orders Board** — Manage shop orders with Shamsi (Jalali) calendar support, payment statuses, and quick action steps.
- 📏 **Auto 3D Mesh Extraction** — Automatically computes X/Y/Z dimensions directly from uploaded 3MF or STL files.
- 💾 **WAL-Safe Database Backup & Restore** — One-click database export (`.db`), instant backup upload & restore in UI, plus an automated daily 14-day rolling backup script for production.
- 🤖 **Telegram Order Bot** — Lightweight polling bot with SOCKS5 proxy, inline keyboards, multi-item order wizard with dynamic pricing, and multi-admin support via comma-separated chat IDs.
- 🛡️ **Hardened Security & RBAC** — `httpOnly` cookie JWT auth, `slowapi` rate limiting on all mutating endpoints, `require_admin` enforcement on product/material/machine/settings mutations, SVG stored XSS sanitization, magic-byte validation for uploaded images, `COOKIE_SECURE` env var, `SENSITIVE_SETTING_KEYS` RBAC filtering, and Farsi slug generation.
- 📝 **Writer Role** — Blog-only access role for content creators; sidebar shows only "وبلاگ" for writers.
- 🇮🇷 **Native Persian / RTL UI** — Vazirmatn typography, responsive Tailwind layout, and soft-blue / brand-orange dark theme.

---

<p align="center">
  <img src="./assets/readme/section-screenshots.svg" width="100%"
       alt="Screenshots section header">
</p>

| 📊 Dashboard & Analytics | 🛒 Orders Board (Kanban) | 📦 Inventory & Products |
|:---:|:---:|:---:|
| ![Dashboard](screenshots/dashboard.png) | ![Orders](screenshots/orders.png) | ![Products](screenshots/products.png) |
| *KPIs + Monthly Analytics* | *Kanban Board + Shamsi Dates* | *Inventory Management* |

| 🧮 Cost Calculator Engine | 🛍️ Public Customer Storefront | 📝 Blog & CMS Module |
|:---:|:---:|:---:|
| ![Calculator](screenshots/calculator.png) | ![Catalog](screenshots/catalog.png) | ![Blog & CMS Module](screenshots/blog.png) |
| *Live Pricing Breakdown* | *Farsi Customer Catalog* | *SEO Articles & CMS Management* |

---

## 🧮 Cost Calculation Engine

$$\text{Material Cost} = (\text{weight} + \text{support} + \text{flushed}) \times (1 + \text{waste\%}) \times \frac{\text{price\_per\_kg}}{1000}$$

$$\text{Power Cost} = \frac{\text{watts}}{1000} \times \text{print\_hours} \times \text{electricity\_rate}$$

$$\text{Depreciation Cost} = \text{print\_hours} \times \frac{\text{purchase\_price}}{\text{life\_hours}}$$

$$\text{Base Price} = \text{Material} + \text{Power} + \text{Depreciation} + \text{Maintenance} + \text{Coloring} + \text{Overhead (30\%)}$$

$$\text{Suggested Price} = \text{Base Price} \times \text{Markup (e.g. 3.0}\times\text{)}$$

---

## 🚀 Quick Start

### Prerequisites
- **Python** 3.11+
- **Node.js** 18+ & **npm**

### 1. Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # Edit with your JWT_SECRET and other vars
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 3. Production Docker Deployment
```bash
docker compose up -d --build
docker compose logs -f
```

---

## ⚙️ Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable | Description | Default |
|:---|:---|:---|
| `JWT_SECRET` | Secret key for JWT signing (≥32 chars). Read by `app/routers/auth.py`; the name is `JWT_SECRET` (**not** `JWT_SECRET_KEY`) and startup fails without it | *required* |
| `INITIAL_ADMIN_PASSWORD` | Bootstrap admin password. **Only applied on the first start with an empty users table** (brand-new database/volume); once any user exists it is ignored and the existing admin hash is preserved — it never resets the live admin. Unset ⇒ a one-time random password is generated and printed | *optional* |
| `COOKIE_SECURE` | Set `true` for HTTPS production | `false` |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`) | `INFO` |
| `CORS_ORIGINS` | Comma-separated list of the **exact** frontend origin(s) allowed cross-origin (scheme + host + port, no trailing slash). Must be the real deployed origin, e.g. `https://spaghettiprints.ir` | localhost dev |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token (a non-empty DB Settings `telegram_bot_token` overrides it) | *optional* |
| `TELEGRAM_ADMIN_CHAT_ID` | Comma-separated admin chat IDs (DB Settings `telegram_admin_chat_id` overrides it) | *optional* |
| `TELEGRAM_PROXY` | SOCKS5 proxy for the Telegram API, e.g. `socks5://192.168.100.50:10805`. Use the `socks5` scheme, **not** `socks5h`. DB Settings `telegram_proxy` overrides this env value | *optional* |
| `PUBLIC_SITE_ORIGIN` | Bare **HTTPS** origin for customer invoice links (no path/query/fragment/userinfo). Plain HTTP is rejected unless the host is an explicit local dev host (`localhost`/`127.0.0.1`/`::1`) | `https://spaghettiprints.ir` |
| `DIGIPAY_CLIENT_ID` / `DIGIPAY_CLIENT_SECRET` / `DIGIPAY_USERNAME` / `DIGIPAY_PASSWORD` | DigiPay UPG merchant credentials. Leave blank to disable online payment — the pay endpoint then returns `503` instead of pretending to work | *optional* |
| `DIGIPAY_ENV` | DigiPay UPG base URL selector: `production` → `api.mydigipay.com`, `staging` (or `uat`/`test`) → `uat.mydigipay.info`. **Caution:** `staging` points every payment (and its redirect allowlist) at the UAT host — never combine it with live merchant credentials; leave as `production` | `production` |
| `DIGIPAY_BASE_URL` | Optional HTTPS host override (DigiPay hosts only; any other host is refused) | *optional* |
| `DIGIPAY_CALLBACK_URL` | Optional absolute HTTPS callback; defaults to `PUBLIC_SITE_ORIGIN` + `/api/v1/commerce/digipay/callback` | *optional* |
| `COMMERCE_NOTIFY_TELEGRAM` | Enable Telegram admin alerts (`0`/`false` to silence) | `1` |
| `COMMERCE_NOTIFY_SMS` | Enable SMS.ir admin alerts | `1` |
| `SMS_IR_API_KEY` / `SMS_IR_TEMPLATE_ID` / `SMS_IR_ADMIN_MOBILE` | SMS.ir API key + approved admin-alert template id + recipient. All three required together or the channel is skipped. The approved template's parameter placeholders must match the names the app sends **exactly, case-sensitively** (the admin-alert template `309349` is approved with `#EVENT#` / `#CODE#`, sent uppercase as `EVENT` / `CODE`); a differently-cased name is not substituted and the send is rejected | *optional* |
| `SMS_IR_OTP_TEMPLATE_ID` / `SMS_IR_OTP_PARAM_OTP` / `SMS_IR_OTP_PARAM_TIME` | Customer checkout one-time code (cart OTP). Approved SMS.ir OTP template id + its parameter names. Needs only `SMS_IR_API_KEY`; it is **independent of the admin SMS channel** (no admin recipient, not gated by `COMMERCE_NOTIFY_SMS`). The approved OTP template `337011` uses the placeholders `#OTP#` / `#TIME#`, so `SMS_IR_OTP_PARAM_OTP` must be the UPPERCASE name `OTP` and `SMS_IR_OTP_PARAM_TIME` the UPPERCASE name `TIME` (SMS.ir substitutes case-sensitively) | `337011` / `OTP` / `TIME` |
| `COMMERCE_NOTIFY_SMTP` | Enable SMTP admin alerts | `1` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_ADMIN_TO` | Admin mailbox. All required together (no fallback mailbox); incomplete config disables the channel | *optional* |
| `SMTP_TLS` | `starttls` (port 587) or `ssl` (port 465) | `starttls` |

---

## 📍 Navigation & Access

| Page / Endpoint | Path | Auth Required |
|:---|:---|:---:|
| Public Storefront Catalog | `http://localhost:5173/` | ❌ |
| Category Page (no hero) | `http://localhost:5173/category/:id` | ❌ |
| Public Blog Articles | `http://localhost:5173/blog` | ❌ (if enabled) |
| How to Order | `http://localhost:5173/how-to-order` | ❌ |
| Custom Order | `http://localhost:5173/custom-order` | ❌ |
| Contact | `http://localhost:5173/contact` | ❌ |
| Admin Login | `http://localhost:5173/login` | ❌ |
| Dashboard | `http://localhost:5173/dashboard` | ✅ |
| Workshop Orders Board | `http://localhost:5173/orders` | ✅ |
| Admin CMS Posts | `http://localhost:5173/admin/posts` | ✅ (admin/writer) |
| System Settings | `http://localhost:5173/settings` | ✅ (admin) |
| Interactive API Docs | `http://localhost:8000/docs` | ❌ |

On first startup with an **empty** users table, set `INITIAL_ADMIN_PASSWORD` to
choose the bootstrap administrator password. If it is unset, the backend
generates and prints a one-time random password. This value is read **only**
while no user exists: once an admin is present it is ignored and the stored
password hash is preserved (the variable never resets or overwrites a live
admin). The administrator must change the password on first login.

---

## 🛡️ Security & Backup Architecture

- **Auth Storage & Role Enforcement**: JWT issued via `httpOnly`, `SameSite=Lax` cookies — immune to XSS token theft. Strict `require_admin` role checks enforced across products, materials, machines, settings, users, and backup endpoints.
- **Rate Limiting**: `slowapi` on all mutating endpoints — login (5/min), orders (20/min), settings (20/min), blog (10/min), backup (5/min).
- **Image Inspection & SVG Sanitization**: Validates binary magic-byte signatures (`\x89PNG`, `\xff\xd8\xff`, `RIFF` WEBP) for all uploads. Rejects executable `<script>` tags or event handlers in SVG branding assets.
- **Sensitive Settings RBAC**: Credential fields (JWT_SECRET, passwords, Telegram tokens) hidden from non-admin roles.
- **Backup Integrity**: Upload size limit (10MB) and SQLite header validation on backup import.
- **Logging Framework**: Structured logging via `logging` module with configurable `LOG_LEVEL` env var.
- **Database Backup**:
  - **Manual UI**: Download `.db` backup file or restore from a previous backup in `/settings`.
  - **Automated Host Script**: Run `./scripts/backup-db.sh` via cron for daily WAL-safe backups with automatic 14-day rotation.

```cron
# Example daily 3:00 AM backup cron job
0 3 * * * /bin/bash /path/to/3djat-pricing/scripts/backup-db.sh >> /path/to/backup.log 2>&1
```

---

## 💳 Commerce & Payments Operations

Order flow: a storefront cart request (`POST /api/v1/commerce/requests`) is
reviewed by staff, who draft an invoice, **approve** it (freezing the price and
issuing a one-time private `/pay/<token>` link), and the customer pays through
DigiPay UPG. The callback (`POST /api/v1/commerce/digipay/callback`) is treated
as an untrusted hint — the invoice is settled only after a server-side
`/purchases/verify` confirms the amount, provider id and tracking code.

- **Online payment is off unless DigiPay is configured**: with no merchant
  credentials the pay endpoint returns `503` rather than pretending to work.
- **Only IPG/Wallet are enabled in v1.** Credit / BNPL callbacks (and BitPay /
  SnappPay, which are not integrated) are never auto-verified; the attempt is
  held (its lock kept) for manual review.
- **Admin alerts are best-effort and off the request path.** A
  `request_created` / `invoice_approved` / `payment_verified` alert is
  snapshotted after the DB commit and delivered by a FastAPI background task
  (Telegram / SMS.ir / SMTP, each independently opt-in), so a slow or dead
  transport never delays the customer response and can never roll back a
  committed order. There is **no durable outbox**: if a channel was down (or
  unconfigured), a staff member resends explicitly —
  `POST /api/v1/commerce/staff/invoices/{id}/notify` (approved/paid invoice) or
  `POST /api/v1/commerce/staff/requests/{id}/notify` (website request) — both
  rate-limited to `10/minute`. The response reports the per-channel result
  (`sent` / `skipped` / `failed`); a `failed` Telegram send with a configured
  bot is reported distinctly from an unconfigured (`skipped`) bot.
- **Telegram proxy precedence.** `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ADMIN_CHAT_ID`
  / `TELEGRAM_PROXY` are read from the environment and then **overridden** by a
  non-empty DB `Settings` row (`telegram_bot_token` / `telegram_admin_chat_id` /
  `telegram_proxy`). A proxy saved in the admin Settings page therefore wins
  over the env value — do **not** overwrite an existing `telegram_proxy` setting
  without operator approval. The proxy must use the `socks5` scheme (e.g.
  `socks5://192.168.100.50:10805`), **not** `socks5h`. A reachable SOCKS5 TCP
  port does **not** prove Telegram HTTPS works through it — the previous
  `:10806` proxy timed out, while a no-credential HTTPS probe via `:10805`
  reached Telegram (HTTP 302). Verify a real authorized send before relying
  on Telegram alerts. This is why alerts are best-effort and
  kept off the request path (see the retry endpoints above).
- **Reconciling unknown / stuck payments.** `GET
  /api/v1/commerce/staff/payments` lists attempts needing attention (bounded;
  `min_age_seconds` only filters, it never changes state). The default queue
  includes both in-flight attempts **and** a genuine, provider-verified payment
  that could not be settled against its invoice (`reconciliation_required`;
  filter with `needs_reconciliation=true`). Resolve one via
  `POST /api/v1/commerce/staff/payments/{id}/reconcile` with
  `action=verify` (re-queries the provider; only a provider-confirmed
  non-success **tied to the exact transaction** closes the attempt) or
  `action=abandon` (an explicit, audited staff decision that **requires a
  reason** and releases the invoice lock). An attempt is never failed on age
  alone, so an invoice is never permanently locked without a human able to
  release it.
- **Settlement is bound to the invoice revision _and_ amount.** A settlement is
  applied only when the attempt's `invoice_revision` and `amount_rial` still
  match the current invoice. A genuine but stale success — an abandoned attempt
  from an earlier revision, or a session against an invoice that was since
  revoked/re-priced — never marks the invoice paid and never 500s the gateway
  callback: the attempt keeps its verified evidence (`state=verified` +
  tracking/`verified_at`) and is flagged `reconciliation_required` for the
  staff/refund queue above, and the customer is sent to a neutral
  `payment=pending` result page. A **replay** of that flagged attempt (a gateway
  retry or the customer re-submitting the form) returns the same `pending` — it
  never reports `success` while the invoice is unsettled and no order exists.
- **Client IP / rate-limit trust behind the proxy (two tiers).** slowapi keys
  login and callback limits on the client address (`request.client.host`),
  which only equals the real client when *both* proxy tiers are handled:
  - **Edge → frontend nginx.** In production the request path is
    `client → Pi5 edge reverse proxy (192.168.100.50) → frontend nginx →
    backend`. The edge replaces `X-Forwarded-For` with the real client, but the
    peer the frontend nginx sees is the edge, so `$remote_addr` would otherwise
    be the edge for everyone. The frontend recovers the client with nginx's
    realip module — `set_real_ip_from 192.168.100.50` (the exact edge, never a
    range and never `*`), `real_ip_header X-Forwarded-For`, `real_ip_recursive
    on` — and then forwards the recovered `$remote_addr` (it *overwrites* the
    forwarded chain, never appends it). A caller hitting the published `:3000`
    port directly is not the trusted edge, so its real peer is kept and a forged
    `X-Forwarded-For` is ignored.
  - **frontend nginx → backend.** nginx is pinned to a static IP
    (`172.28.0.2`) on the compose network and the backend is started with
    `--forwarded-allow-ips 172.28.0.2` — **never `*`** — so a direct request to
    the published backend port (whose peer is not the proxy) cannot forge its
    IP, and two clients behind nginx keep separate rate-limit buckets.
- **Container healthchecks probe `127.0.0.1`, not `localhost`.** Inside the
  containers `localhost` resolves to `127.0.0.1` *and* `::1`, while nginx
  (`listen 80;`) and uvicorn (`--host 0.0.0.0`) bind IPv4 only, so a
  `localhost` probe can hit the unbound `::1` and report a perfectly healthy
  container **unhealthy** (which blocks `depends_on: service_healthy`
  dependents). Both compose healthchecks therefore target
  `http://127.0.0.1:<port>`.
- **The invoice bearer token is kept out of the logs.** The public token is a
  URL path credential, and the pay page hits it on every load, so it is
  redacted at **both** layers:
  - **nginx** disables its access log for the token-bearing paths — the
    `/pay/<token>` page **and** the `/api/v1/commerce/invoices/<token>…` API
    the page calls (`GET` and `POST …/pay`). The API prefix uses a dedicated,
    *longer* `^~` prefix (plus a case-insensitive `~*` companion for mixed-case
    variants), because an `^~` prefix match stops regex evaluation and would
    otherwise shadow a plain `~*` block — the token would still be logged. The
    `/pay/` page keeps its security headers (no-referrer, no-store, CSP).
  - **backend** installs a `logging.Filter` on `uvicorn.access` that rewrites
    the token path segment to `<redacted>`, for any case, **without** disabling
    access logging (`app/log_redaction.py`).
  - **Residual:** nginx's *error* log can still record the full request line
    (including the token) when an upstream error embeds the URI. A hardened
    deployment should lower `error_log` to `crit` so those lines are not kept;
    the access-log leak is fully closed.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11, FastAPI 0.104+, SQLAlchemy 2.0 (SQLite WAL mode), Pydantic v2, PyJWT, slowapi, PySocks (SOCKS5 proxy).
- **Frontend**: React 18, Vite 5, TailwindCSS, React Router v6, Axios (`withCredentials`), Lucide Icons, `jalaali-js`.
- **Infrastructure**: Docker Compose (Non-root containers with HTTP healthchecks).
- **Telegram Bot**: Lightweight polling + `PySocks` + SOCKS5 proxy. Inline keyboards, multi-item order wizard.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

<div align="center">

**Designed with ❤️ for 3D Printing Workshops & Businesses**

</div>
