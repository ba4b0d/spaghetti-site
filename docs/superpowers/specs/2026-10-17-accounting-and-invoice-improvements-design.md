# Design Document: Accounting Module, Invoice Enhancements & Client Pay Flow

- **Date:** 2026-10-17
- **Project:** 3DJAT / Spaghetti Print
- **Status:** Approved & Hardened, Ready for Implementation

---

## 1. Overview & Goals

This project implements three interconnected financial and commercial capabilities:
1. **Accounting Subsystem (دفتر حسابداری و مدیریت مالی):** A cash-basis bookkeeping module designed for a 3D printing workshop. Tracks operating expenses (filaments, printer parts, electricity, packaging, shipping, marketing) and automated revenues (paid invoices & orders) with categorized breakdowns, net profit (P&L), and Shamsi date filtering/exporting.
2. **Admin Invoice Management Improvements:** Upgrades `CommerceAdmin.jsx` with real-time search (debounced), status tabs (*all, draft, pending payment, paid, cancelled/expired*), manual payment recording (کارت به کارت / نقدی) with automatic fulfillment order creation, postal shipping label generator (لیبل پستی برای تیپاکس/پست), and bank gateway transaction details.
3. **Client Area Online Payment («پرداخت آنلاین» در سفارش‌های من):** In `/my-orders`, authenticated customers viewing an approved invoice can click **«پرداخت آنلاین»** to open a gateway selector modal (DigiPay / BitPay) and redirect directly to payment without needing manual link copying.

---

## 2. Architecture & Data Models

### 2.1 Database Models (`backend/app/models.py`)

#### `AccountingCategory` (`accounting_categories`)
- `id`: `Integer`, Primary Key, autoincrement.
- `name`: `String(100)`, not null.
  - **Default Expense Seeds:** "خرید فیلامنت و متریال", "قطعات یدکی و نگهداری پرینتر", "بسته‌بندی و کارتن", "هزینه ارسال و پست", "هزینه اشتراک و اینترنت", "برق کارگاه", "تبلیغات و مارکتینگ", "سایر هزینه‌ها".
  - **Default Income Seeds:** "فروش محصول و خدمات", "سایر درآمدها".
- `type`: `String(20)`, not null (`income` or `expense`).
- `is_system`: `Boolean`, default `False` (system seeds cannot be deleted or have their `type` changed).
- `is_active`: `Boolean`, default `True` (soft deletion).
- `created_at`: `DateTime`, default UTC now.

#### `AccountingTransaction` (`accounting_transactions`)
- `id`: `Integer`, Primary Key, autoincrement.
- `title`: `String(200)`, not null.
- `category_id`: `Integer`, ForeignKey(`accounting_categories.id`, ondelete="RESTRICT"), not null, indexed.
- `type`: `String(20)`, not null (`income` or `expense`), indexed.
- `amount_toman`: `BigInteger`, not null (prevents 32-bit integer overflow during `SUM()` aggregations).
- `transaction_date`: `Date`, not null, indexed (stored in Gregorian `YYYY-MM-DD`, converted from/to Shamsi at UI/export boundaries).
- `account_type`: `String(30)`, default `'bank'` (`bank`, `cash`, `gateway`, `other`).
- `reference_code`: `String(100)`, default `""`.
- `description`: `String(1000)`, default `""`.
- `attachment_url`: `String(500)`, nullable.
- `invoice_id`: `Integer`, ForeignKey(`commerce_invoices.id`, ondelete="SET NULL"), nullable, unique, indexed (unique constraint guarantees idempotency so an invoice never generates duplicate income entries).
- `order_id`: `Integer`, ForeignKey(`orders.id`, ondelete="SET NULL"), nullable, indexed.
- `created_by_user_id`: `Integer`, ForeignKey(`users.id`, ondelete="SET NULL"), nullable.
- `created_at`: `DateTime`, default UTC now.
- `updated_at`: `DateTime`, default UTC now, onupdate UTC now.

Relationships:
- `category = relationship("AccountingCategory")`
- `invoice = relationship("CommerceInvoice")`
- `order = relationship("Order")`

---

## 3. Backend Endpoints & Service Logic

### 3.1 Accounting Endpoints (`backend/app/routers/accounting.py`)
- `GET /api/v1/accounting/categories`: List active categories (filterable by `type`).
- `POST /api/v1/accounting/categories`: Create custom category.
- `PUT /api/v1/accounting/categories/{id}`: Update custom category name (blocks changing `type` if transactions already exist under it, or modifying `is_system` categories).
- `DELETE /api/v1/accounting/categories/{id}`: Soft delete (`is_active = False`) if not `is_system`.
- `GET /api/v1/accounting/transactions`: List transactions with filters (`type`, `category_id`, `start_date`, `end_date`, `search`, `page`, `limit`). `start_date` and `end_date` accept Gregorian `YYYY-MM-DD` converted by the frontend from Shamsi selections.
- `POST /api/v1/accounting/transactions`: Record manual income/expense.
  - **Validation:** Verifies `transaction.type == category.type` and `amount_toman > 0`.
- `PUT /api/v1/accounting/transactions/{id}`: Update transaction.
  - **Guardrail:** If `invoice_id IS NOT NULL`, block changes to `amount_toman`, `type`, and `invoice_id` (only `description`, `category_id`, `reference_code`, and `attachment_url` may be updated).
- `DELETE /api/v1/accounting/transactions/{id}`: Delete manual transaction.
  - **Guardrail:** Reject deletion with `400 Bad Request` if `invoice_id IS NOT NULL` (auto-synced invoice transactions cannot be manually deleted).
- `POST /api/v1/accounting/upload-attachment`: Upload receipt/bill image or PDF (`jpg`, `png`, `webp`, `pdf` up to 5MB) and return `{ "attachment_url": "..." }`.
- `GET /api/v1/accounting/summary`: Returns total income, total expenses, net profit, margin %, category breakdown, and monthly breakdown for the requested date range.
- `GET /api/v1/accounting/export`: Returns UTF-8 BOM CSV/Excel of filtered transactions with dates formatted as Shamsi (`YYYY/MM/DD` via `jdatetime`).

### 3.2 Automated Invoicing & Manual Payment Flow
- **Auto-Syncing Invoices:**
  When an invoice transitions to `state = 'paid'` (via online gateway webhook/callback or manual staff confirmation):
  1. A `CommercePaymentAttempt` is recorded or marked verified.
  2. The legacy fulfillment `Order` is created (if not already present).
  3. An `AccountingTransaction` is automatically upserted/inserted (idempotent check via `invoice_id`):
     - `title`: `f"فروش فاکتور #{invoice.id} - {invoice.customer_name}"`
     - `category_id`: System income category "فروش محصول و خدمات"
     - `type`: `'income'`
     - `amount_toman`: `invoice.total_toman`
     - `transaction_date`: Parsed `paid_at` date (if manual payment) or current date in `Asia/Tehran` timezone (if online gateway).
     - `account_type`: `'gateway'` (online) or `'bank'` / `'cash'` (manual).
     - `reference_code`: provider transaction ID / tracking code.
     - `invoice_id`: `invoice.id`
     - `order_id`: `order.id`
- **Manual Payment Endpoint (`POST /api/v1/commerce/admin/invoices/{invoice_id}/manual-pay`):**
  - Accepts: `{ payment_method: "card_to_card" | "cash", reference_code: str, paid_at: str (YYYY-MM-DD), note: str }`
  - Validates staff permissions and ensures `invoice.state` is not already `paid`.
  - Updates invoice state to `paid`, creates fulfillment order, and triggers accounting transaction creation using `paid_at`.

### 3.3 Client Area Payment Endpoint (`POST /api/v1/commerce/history/invoices/{invoice_id}/pay`)
- Checks valid customer history session token.
- Verifies `session.mobile == invoice.mobile`.
- Verifies `invoice.state == 'approved'` (and not expired).
- Takes `{ gateway: "digipay" | "bitpay" }`.
- Calls `start_payment(db, invoice, gateway=body.gateway, request=request)`.
- Returns `{ "redirect_url": attempt.redirect_url }`.

---

## 4. Frontend UI Components & Pages

### 4.1 Client Area (`frontend/src/pages/CustomerOrders.jsx`)
- Replaces the static `PAYMENT_SUPPORT_MESSAGE` with a prominent **«پرداخت آنلاین»** button for approved invoices.
- Modal:
  - Header: صورت‌حساب سفارش شماره #{id}
  - Price details: مبلغ سفارش، هزینه بسته‌بندی و ارسال، مبلغ قابل پرداخت
  - Gateway radio/buttons: درگاه پرداخت دیجی‌پی (پیش‌فرض) / درگاه بیت‌پی
  - Action: دکمه «انتقال به درگاه و پرداخت امن» with loading state
  - Automatically redirects window to `res.redirect_url`.

### 4.2 Admin Invoices (`frontend/src/pages/CommerceAdmin.jsx`)
- **Status Tabs:** همه (All) | پیش‌نویس (Draft) | در انتظار پرداخت (Approved) | پرداخت‌شده (Paid) | لغو / منقضی (Revoked / Expired).
- **Search Bar:** Real-time filter (300ms debounce) by customer name, mobile, and invoice ID.
- **Manual Payment Button & Modal:**
  - Method selector: کارت به کارت / نقدی / حضوری.
  - Tracking code & Shamsi date picker (converts to `YYYY-MM-DD` on submit).
- **Postal Packing Slip Modal:**
  - Printable clean voucher / label (`@media print` styled) with sender (Spaghetti Print), receiver address, contact number, order items, and barcode/QR placeholder.
  - One-click "کپی آدرس گیرنده" and "چاپ برچسب".
- **Gateway Tracking Details:**
  - Paid invoices display a pill with payment method (`درگاه آنلاین` / `کارت به کارت` / `نقدی`) and transaction reference code.

### 4.3 Accounting Management (`frontend/src/pages/Accounting.jsx`)
- Navigation item in `Sidebar.jsx` (دفتر حسابداری).
- **KPI Summary Cards:**
  - درآمد کل (Total Income)
  - هزینه‌های کل (Total Expenses)
  - سود خالص (Net Profit)
  - حاشیه سود (Profit Margin %)
- **Period Filter:** Shamsi month dropdown & custom Shamsi date range picker.
- **Add Expense & Add Income Modals:**
  - Fields: عنوان، سرفصل هزینه/درآمد، مبلغ به تومان، تاریخ شمسی، حساب (بانک/صندوق/درگاه)، شماره پیگیری، پیوست رسید (اختیاری)، توضیحات.
- **Manage Categories Drawer:**
  - List system & custom categories, add new categories, edit, or archive.
- **Transactions Table:**
  - Fast sorting, search, category badge, receipt preview link, and CSV export.
  - Auto-synced invoice rows show a linked invoice badge (`#فاکتور`) and disable the Delete button.

---

## 5. Security & Verification Strategy
- **Permissions:** Admin & Staff role-gating on `/api/v1/accounting/*` and `/api/v1/commerce/admin/*`.
- **Client Payment Guard:** Validated strictly against the verified customer's SMS-OTP session mobile; cannot initiate payment for other customers' invoices.
- **Idempotency:** Enforced via application check AND database `UNIQUE` constraint on `accounting_transactions.invoice_id`.
- **Testing:**
  - Unit tests for accounting calculations, `BigInteger` totals, and category-type matching constraints.
  - Backend API tests for manual payment, client payment initiation, auto-sync guardrails, and accounting CRUD.
  - Frontend component tests for pay modal, postal slip, and filter tabs.