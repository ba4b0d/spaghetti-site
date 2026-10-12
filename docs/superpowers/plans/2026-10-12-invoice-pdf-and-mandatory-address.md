# Invoice PDF Download and Mandatory Checkout Address — Tasks

> **Goal:** Enforce mandatory delivery addresses in storefront checkout, implement high-fidelity Persian PDF invoice rendering with QR code and brand styling, provide public/staff download endpoints, and dispatch invoice PDFs to Telegram admins on approval and payment.

**Spec Reference:** `docs/superpowers/specs/2026-10-12-invoice-pdf-and-mandatory-address-design.md`

---

## Task Breakdown

### Phase 1: Mandatory Delivery Address
- [x] **TASK-001** [REQ-001] **Backend Checkout Address Validation**
  - Update `CartRequestIn` in `backend/app/routers/commerce.py` so `address: str = Field(..., min_length=5, max_length=500)`.
  - Update `prepare_website_request` in `backend/app/services/commerce.py` to validate `if not address or len(address.strip()) < 5: raise CommerceValidationError("نشانی تحویل الزامی است")`.
  - Add backend test verifying that empty or whitespace addresses are rejected with 400.
  - Verification: `pytest backend/tests/test_commerce_requests.py` passes.

- [x] **TASK-002** [REQ-001] **Frontend Checkout Address Enforcement**
  - In `frontend/src/pages/CheckoutRequest.jsx`:
    - Update label to «نشانی دقیق تحویل (الزامی) *».
    - Add required check in `validateForm`: address must have at least 5 characters.
    - Display inline error message when invalid.
  - Update existing frontend tests in `src/__tests__/pages/CheckoutRequest.test.jsx`.
  - Verification: `npx vitest run src/__tests__/pages/CheckoutRequest.test.jsx` passes.

---

### Phase 2: PDF Generation Service & Assets
- [x] **TASK-003** [REQ-002] **Font Assets & Dependencies**
  - Add `reportlab>=4.0.0` to `backend/requirements.txt` and install in `backend/venv`.
  - Download / provide TTF fonts for Persian (`Vazirmatn-Regular.ttf`, `Vazirmatn-Bold.ttf`) in `backend/app/assets/fonts/`.
  - Verification: Python script registers fonts in ReportLab `pdfmetrics` successfully.

- [x] **TASK-004** [REQ-002] **Persian Invoice PDF Engine (`invoice_pdf.py`)**
  - Create `backend/app/services/invoice_pdf.py`:
    - BiDi shaping helper (`arabic_reshaper.reshape` + `bidi.algorithm.get_display`) supporting mixed numbers/Farsi text.
    - QR Code generation using `qrcode` for `https://spaghettiprints.ir/pay/{token}`.
    - Header: Spaghetti Print brand, invoice ID, Jalali date, status badge («در انتظار پرداخت» / «پرداخت‌شده»).
    - Seller: «اسپاگتی پرینت» - «تهران، شهرک امید» - «spaghettiprints.ir».
    - Buyer: Customer name, phone, messenger, full delivery address.
    - Line items table: row index, description, qty, unit price (Toman), total (Toman).
    - Summary section: subtotal, shipping fee, payable total in Toman.
    - Finalized specifications / notes box.
  - Write test `backend/tests/test_invoice_pdf.py` verifying PDF generation produces valid PDF bytes with non-zero length and expected content.
  - Verification: `pytest backend/tests/test_invoice_pdf.py` passes.

---

### Phase 3: Download Endpoints
- [x] **TASK-005** [REQ-003] **Public & Staff PDF Download Routes**
  - In `backend/app/routers/commerce.py`:
    - Add `GET /invoices/{token}/pdf` (rate-limited, public, streaming `application/pdf`, no-store header, Content-Disposition: inline/attachment).
    - Add `GET /staff/invoices/{invoice_id}/pdf` (requires `require_staff_role`, streaming `application/pdf`).
  - Write integration tests in `backend/tests/test_commerce_invoices.py` for both routes.
  - Verification: `pytest backend/tests/test_commerce_invoices.py` passes.

---

### Phase 4: Telegram Admin Dispatch
- [x] **TASK-006** [REQ-004] **Telegram Invoice PDF Attachment**
  - In `backend/app/services/commerce_notifications.py` / `commerce.py`:
    - On invoice approval: generate PDF to scratch temp file, call `send_telegram_document` with invoice summary caption, clean up temp file.
    - On invoice payment settled: generate paid PDF, call `send_telegram_document` with payment confirmation caption, clean up temp file.
  - Add test in `backend/tests/test_commerce_notifications.py` asserting `send_telegram_document` is called when approved and paid.
  - Verification: `pytest backend/tests/test_commerce_notifications.py` passes.

---

### Phase 5: Frontend UI Download CTAs
- [x] **TASK-007** [REQ-005] **Customer & Admin PDF Download Buttons**
  - In `frontend/src/lib/commerceApi.js`: Add helper functions / URL builders for PDF download (`getPublicInvoicePdfUrl(token)`, `getStaffInvoicePdfUrl(id)`).
  - In `frontend/src/pages/InvoicePayment.jsx`: Add «📄 دریافت نسخه PDF فاکتور» button.
  - In `frontend/src/pages/CommerceAdmin.jsx`: Add PDF download button in invoice list row.
  - Add/update tests in frontend.
  - Verification: `npx vitest run` passes.

---

### Phase 6: End-to-End Verification
- [x] **TASK-008** Full suite regression test (`pytest` + `vitest` + `npm run build`).
