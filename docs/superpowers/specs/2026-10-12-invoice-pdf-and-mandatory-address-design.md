# Invoice PDF Download and Mandatory Checkout Address — Design

## 1. Goal and Scope

Provide downloadable, high-fidelity Persian PDF invoices for Spaghetti Print customers and staff, automatically deliver invoice PDFs to the store administrator via Telegram upon invoice approval and payment settlement, and enforce mandatory delivery addresses during storefront cart checkout.

### Key Objectives
1. **Mandatory Delivery Address in Checkout:** Enforce non-empty, validated Iranian delivery address for all website cart requests across frontend UI and backend services.
2. **High-Fidelity Persian PDF Generation:** Build a dedicated backend PDF rendering service supporting Persian BiDi text, glyph shaping (`arabic-reshaper`, `python-bidi`), official Vazirmatn typography, Spaghetti Print brand styling, full buyer delivery address, seller details (Tehran Shahrak Omid), QR code payment link, itemized lines, and Jalali dates.
3. **Public & Staff PDF Download Endpoints:** Allow customers with private invoice bearer tokens (`GET /api/v1/commerce/invoices/{token}/pdf`) and authenticated staff (`GET /api/v1/commerce/staff/invoices/{id}/pdf`) to download invoices.
4. **Admin Telegram PDF Dispatch:** Automatically send the generated invoice PDF directly to admin Telegram chat(s) via `send_telegram_document` on invoice approval and on successful payment settlement.
5. **Frontend Download CTAs:** Add download buttons on the customer payment page (`/pay/:token`) and the admin commerce invoice table (`CommerceAdmin.jsx`).

---

## 2. Requirements & Acceptance Criteria

### REQ-001: Mandatory Checkout Address
- **Actor:** Customer / Storefront visitor.
- **Behavior:** The checkout form shall require an address before submitting or requesting an OTP.
- **Frontend Criteria:** Form field labeled «نشانی دقیق تحویل (الزامی) *»; submission blocked with Persian validation error if blank or < 5 characters.
- **Backend Criteria:** `CartRequestIn.address` requires `min_length=5, max_length=500`; `prepare_website_request` rejects blank/empty addresses with 400 `CommerceValidationError("نشانی تحویل الزامی است")`.

### REQ-002: Persian PDF Generation Engine
- **Actor:** Backend service (`app.services.invoice_pdf`).
- **Behavior:** Renders a clean single-page (or multi-page if many items) A4 PDF document using `reportlab`, `arabic-reshaper`, `python-bidi`, and `qrcode`.
- **Typography & Assets:** Embeds TTF font `Vazirmatn` (Regular and Bold) stored in `backend/app/assets/fonts/`.
- **Header:** Spaghetti Print logo/title, Jalali date (via `jalaali` or python-jdatetime calculation), Invoice number (`INV-{id:04d}`), Status badge («در انتظار پرداخت» or «پرداخت‌شده»).
- **Seller Details:**
  - نام فروشنده: اسپاگتی پرینت (Spaghetti Print)
  - نشانی: تهران، شهرک امید
  - وب‌سایت: spaghettiprints.ir
- **Buyer Details:**
  - نام خریدار: `customer_name`
  - شماره تماس: `mobile`
  - پیام‌رسان: `messenger` / `messenger_handle`
  - نشانی کامل خریدار: `address` (full text)
- **Itemized Table:** Row #, Description, Qty, Unit Price (Toman), Line Total (Toman).
- **Summary & Totals:** Items Subtotal, Shipping (`shipping_toman`), Payable Total (`total_toman`), Toman spelled out in Persian words where helpful.
- **Notes / Specs:** Finalized specifications (`specification`) rendered in a clean note box.
- **QR Code:** High-contrast QR code pointing to `https://spaghettiprints.ir/pay/{token}` (when token available) so customers/couriers can scan and pay.

### REQ-003: Public & Staff Download Endpoints
- **Public Endpoint:** `GET /api/v1/commerce/invoices/{token}/pdf`
  - Protected by private bearer token in URL.
  - Rate limited (30/minute).
  - Returns `application/pdf` with `Content-Disposition: inline; filename="spaghetti-invoice-{id}.pdf"`.
  - Cache-Control: `no-store`, Referrer-Policy: `no-referrer`.
- **Staff Endpoint:** `GET /api/v1/commerce/staff/invoices/{invoice_id}/pdf`
  - Requires `require_staff_role` dependency.
  - Returns invoice PDF even in draft or approved/paid/revoked state.

### REQ-004: Telegram Admin Dispatch
- **Trigger 1 (Approval):** In `approve_invoice` background task, generate the invoice PDF and call `send_telegram_document(pdf_path, caption=...)` with link and order summary.
- **Trigger 2 (Paid):** In `notify_invoice_paid` (or webhook/callback settlement), generate the paid invoice PDF with "پرداخت‌شده" stamp and send to Telegram admins.

### REQ-005: Frontend Download CTAs
- **Invoice Payment Page (`/pay/:token`):** Add a secondary action button with `Download` / `FileText` icon: «دریافت نسخه PDF فاکتور». Triggers browser download from `/api/v1/commerce/invoices/{token}/pdf`.
- **Commerce Admin Page (`CommerceAdmin.jsx`):** In invoice row action buttons, add a PDF download icon button linking to `/api/v1/commerce/staff/invoices/{id}/pdf`.

---

## 3. Architecture & File Structure

```
backend/
├── app/
│   ├── assets/
│   │   └── fonts/
│   │       ├── Vazirmatn-Regular.ttf
│   │       └── Vazirmatn-Bold.ttf
│   ├── services/
│   │   ├── invoice_pdf.py        # PDF generator (ReportLab + reshaper + bidi + QR)
│   │   ├── commerce.py           # Updated address validation in prepare_website_request
│   │   └── commerce_notifications.py # Telegram send_telegram_document dispatch
│   └── routers/
│       └── commerce.py           # Public & Staff PDF endpoints
└── requirements.txt              # Add reportlab==4.x

frontend/
└── src/
    ├── pages/
    │   ├── CheckoutRequest.jsx   # Required address field + validation
    │   ├── InvoicePayment.jsx    # "دانلود PDF فاکتور" CTA button
    │   └── CommerceAdmin.jsx     # "دانلود PDF" action in staff table
    └── lib/
        └── commerceApi.js        # Helper URLs for downloading PDFs
```

---

## 4. Security & Privacy
- Full delivery address is included for the buyer (as requested), while the seller address is restricted to `تهران، شهرک امید`.
- Public PDF endpoint is bound to the invoice private bearer token (`{token}`); no unauthenticated user can guess sequential IDs to access PDFs.
- Rate-limiting prevents scraping/DDoS on PDF rendering.
- Response headers enforce `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
- Ephemeral PDF temp files are cleaned up after Telegram dispatch.
