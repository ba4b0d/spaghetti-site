# Accounting Module, Invoice Enhancements & Client Pay Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete cash-basis accounting & bookkeeping system, enhance the admin invoice manager with search/tabs/manual payments/postal slips, and enable authenticated customers to directly pay approved invoices via a gateway selector modal in `/my-orders`.

**Architecture:** 
1. Database & Models: Add `AccountingCategory` and `AccountingTransaction` with `BigInteger` amount storage and `unique` invoice idempotency.
2. Backend Services: Create `backend/app/services/accounting.py` and router `backend/app/routers/accounting.py`, add client payment initiation in `commerce_history.py`, and implement manual payment + auto-accounting sync in `commerce.py`.
3. Frontend: Build `Accounting.jsx` with Shamsi date filtering/summary/export, upgrade `CommerceAdmin.jsx` with tabs/search/manual-pay/postal-slip, and update `CustomerOrders.jsx` with online payment modal.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, React 18, TailwindCSS, Lucide icons, jdatetime / Shamsi date utilities.

**Spec:** `docs/superpowers/specs/2026-10-17-accounting-and-invoice-improvements-design.md`

## Global Constraints
- Persian/Farsi (RTL) copy across all UI elements and validation errors.
- Monetary values stored in Iranian Toman (IRR) as integer/BigInteger.
- Soft-deletes (`is_active = False`) for categories.
- Role-based authorization (`require_admin` or staff) for accounting and commerce admin endpoints.
- SMS-OTP session ownership verification for `/my-orders` payment initiation.
- SQLite-safe startup migrations via `PRAGMA table_info` and `inspect(engine)`.

---

### Task 1: Database Models, Seed Categories & SQLite Migrations

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_accounting_models.py`

**Interfaces:**
- Produces: `AccountingCategory`, `AccountingTransaction` models in `backend/app/models.py`
- Produces: Default categories seed logic and table creation migration in `backend/app/main.py`

- [ ] **Step 1: Write the failing test for accounting models and category seeds**

```python
# backend/tests/test_accounting_models.py
import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import AccountingCategory, AccountingTransaction, CommerceInvoice

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_accounting_category_creation_and_defaults(test_db):
    cat = AccountingCategory(
        name="خرید فیلامنت و متریال",
        type="expense",
        is_system=True,
        is_active=True,
    )
    test_db.add(cat)
    test_db.commit()
    test_db.refresh(cat)

    assert cat.id is not None
    assert cat.name == "خرید فیلامنت و متریال"
    assert cat.type == "expense"
    assert cat.is_system is True
    assert cat.is_active is True

def test_accounting_transaction_uniqueness_on_invoice_id(test_db):
    cat = AccountingCategory(name="فروش محصول و خدمات", type="income", is_system=True)
    test_db.add(cat)
    test_db.commit()

    inv = CommerceInvoice(customer_name="علی رضایی", mobile="09121112233", total_toman=500000)
    test_db.add(inv)
    test_db.commit()

    t1 = AccountingTransaction(
        title="فاکتور ۱",
        category_id=cat.id,
        type="income",
        amount_toman=500000,
        transaction_date=date(2026, 10, 17),
        invoice_id=inv.id,
    )
    test_db.add(t1)
    test_db.commit()

    t2 = AccountingTransaction(
        title="فاکتور ۱ تکراری",
        category_id=cat.id,
        type="income",
        amount_toman=500000,
        transaction_date=date(2026, 10, 17),
        invoice_id=inv.id,
    )
    test_db.add(t2)
    with pytest.raises(Exception):
        test_db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_accounting_models.py`
Expected: FAIL with `ImportError: cannot import name 'AccountingCategory' from 'app.models'`

- [ ] **Step 3: Implement AccountingCategory and AccountingTransaction models in models.py**

In `backend/app/models.py`:
Add `AccountingCategory` and `AccountingTransaction` classes with:
- `BigInteger` for `amount_toman`
- Foreign keys and unique constraint on `invoice_id`
- Default system seed categories in startup migration in `backend/app/main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_accounting_models.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/main.py backend/tests/test_accounting_models.py
git commit -m "feat(accounting): add accounting models, migrations, and seed categories"
```

---

### Task 2: Accounting Service, Summary & CRUD API

**Files:**
- Create: `backend/app/services/accounting.py`
- Create: `backend/app/routers/accounting.py`
- Modify: `backend/app/main.py` (include router `/api/v1/accounting`)
- Create: `backend/tests/test_accounting_api.py`

**Interfaces:**
- Produces: `GET/POST/PUT/DELETE /api/v1/accounting/categories`
- Produces: `GET/POST/PUT/DELETE /api/v1/accounting/transactions`
- Produces: `GET /api/v1/accounting/summary`
- Produces: `GET /api/v1/accounting/export`
- Produces: `POST /api/v1/accounting/upload-attachment`

- [ ] **Step 1: Write the failing tests for accounting API endpoints**

```python
# backend/tests/test_accounting_api.py
def test_accounting_categories_crud(client, admin_token):
    # list categories
    res = client.get("/api/v1/accounting/categories", cookies={"access_token": admin_token})
    assert res.status_code == 200
    data = res.json()
    assert any(c["name"] == "فروش محصول و خدمات" for c in data)

    # create custom category
    res = client.post(
        "/api/v1/accounting/categories",
        json={"name": "پذیرایی و قهوه کارگاه", "type": "expense"},
        cookies={"access_token": admin_token},
    )
    assert res.status_code == 200
    cat_id = res.json()["id"]

    # delete category
    res = client.delete(f"/api/v1/accounting/categories/{cat_id}", cookies={"access_token": admin_token})
    assert res.status_code == 200

def test_manual_transaction_and_summary(client, admin_token):
    # Get an expense category
    res = client.get("/api/v1/accounting/categories?type=expense", cookies={"access_token": admin_token})
    cat = res.json()[0]

    # Create manual expense
    tx_payload = {
        "title": "خرید رول PLA مشکی",
        "category_id": cat["id"],
        "type": "expense",
        "amount_toman": 450000,
        "transaction_date": "2026-10-17",
        "account_type": "bank",
        "reference_code": "REF-998811",
        "description": "خرید فوری برای سفارش مشتری",
    }
    res = client.post("/api/v1/accounting/transactions", json=tx_payload, cookies={"access_token": admin_token})
    assert res.status_code == 200
    tx_id = res.json()["id"]

    # Check summary
    res = client.get("/api/v1/accounting/summary?start_date=2026-10-01&end_date=2026-10-31", cookies={"access_token": admin_token})
    assert res.status_code == 200
    summary = res.json()
    assert summary["total_expense"] >= 450000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_accounting_api.py`
Expected: FAIL with `404 Not Found` (endpoint not registered)

- [ ] **Step 3: Implement accounting service and router**

Implement:
1. `backend/app/services/accounting.py` with validation:
   - Type consistency between category and transaction.
   - Deletion/modification guardrails for invoice-linked transactions.
   - BigInteger summary metrics and Shamsi CSV generation.
2. `backend/app/routers/accounting.py` role-gated with `get_current_user`.
3. Register router in `backend/app/main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_accounting_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting.py backend/app/routers/accounting.py backend/app/main.py backend/tests/test_accounting_api.py
git commit -m "feat(accounting): add accounting service, summary, export and CRUD endpoints"
```

---

### Task 3: Client Area Pay Button & API (`/my-orders`)

**Files:**
- Modify: `backend/app/routers/commerce_history.py`
- Modify: `frontend/src/lib/commerceHistoryApi.js`
- Modify: `frontend/src/pages/CustomerOrders.jsx`
- Create: `backend/tests/test_customer_pay_endpoint.py`
- Create: `frontend/src/__tests__/customerOrdersPayModal.test.jsx`

**Interfaces:**
- Produces: `POST /api/v1/commerce/history/invoices/{invoice_id}/pay`
- Consumes: `start_payment()` in `backend/app/services/commerce.py`
- Produces: Interactive payment modal in `CustomerOrders.jsx`

- [ ] **Step 1: Write backend test for client invoice payment initiation**

```python
# backend/tests/test_customer_pay_endpoint.py
def test_customer_cannot_pay_unowned_invoice(client, test_db, valid_history_session):
    # Attempting to pay an invoice belonging to another mobile returns 404/403
    token, mobile = valid_history_session
    res = client.post(
        "/api/v1/commerce/history/invoices/99999/pay",
        headers={"Authorization": f"Bearer {token}"},
        json={"gateway": "digipay"},
    )
    assert res.status_code in (403, 404)
```

- [ ] **Step 2: Implement POST /api/v1/commerce/history/invoices/{invoice_id}/pay**

In `backend/app/routers/commerce_history.py`:
- Fetch invoice by `invoice_id`.
- Assert `session.mobile == invoice.mobile`.
- Assert `invoice.state == 'approved'` and link is not expired.
- Call `start_payment(db, invoice, gateway=body.gateway, request=request)`.
- Return `{"redirect_url": attempt.redirect_url}`.

- [ ] **Step 3: Update CustomerOrders.jsx with Online Payment Button & Modal**

In `frontend/src/pages/CustomerOrders.jsx`:
- For approved invoices (`state === 'approved'`), replace support notice with **«پرداخت آنلاین»** button.
- Clicking opens a modal:
  - Total price & shipping breakdown.
  - Gateway selector (DigiPay / BitPay).
  - Submit button with spinner that initiates payment and calls `window.location.href = res.redirect_url`.

- [ ] **Step 4: Run backend & frontend tests**

Run: `pytest backend/tests/test_customer_pay_endpoint.py`
Run: `npm --prefix frontend test -- customerOrdersPayModal`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/commerce_history.py frontend/src/lib/commerceHistoryApi.js frontend/src/pages/CustomerOrders.jsx backend/tests/test_customer_pay_endpoint.py
git commit -m "feat(commerce): enable direct online payment from customer my-orders area"
```

---

### Task 4: Admin Manual Payment & Automated Accounting Sync

**Files:**
- Modify: `backend/app/services/commerce.py`
- Modify: `backend/app/routers/commerce.py`
- Create: `backend/tests/test_manual_pay_and_accounting_sync.py`

**Interfaces:**
- Produces: `POST /api/v1/commerce/admin/invoices/{invoice_id}/manual-pay`
- Produces: Automatic insertion of `AccountingTransaction` whenever an invoice is paid (online or manual).

- [ ] **Step 1: Write test for manual invoice payment and auto accounting sync**

```python
# backend/tests/test_manual_pay_and_accounting_sync.py
def test_manual_payment_transitions_invoice_and_creates_accounting_entry(client, admin_token, test_approved_invoice):
    res = client.post(
        f"/api/v1/commerce/admin/invoices/{test_approved_invoice.id}/manual-pay",
        json={
            "payment_method": "card_to_card",
            "reference_code": "CART-123456",
            "paid_at": "2026-10-17",
            "note": "واریز به صادرات",
        },
        cookies={"access_token": admin_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "paid"

    # Verify accounting transaction was created
    res = client.get(f"/api/v1/accounting/transactions?search={test_approved_invoice.id}", cookies={"access_token": admin_token})
    assert res.status_code == 200
    txs = res.json()["items"]
    assert len(txs) == 1
    assert txs[0]["invoice_id"] == test_approved_invoice.id
    assert txs[0]["amount_toman"] == test_approved_invoice.total_toman
```

- [ ] **Step 2: Implement manual payment endpoint and auto-sync hook**

In `backend/app/services/commerce.py`:
- In `record_manual_payment()` and in online gateway completion callback:
  - Create fulfillment Order.
  - Insert/upsert `AccountingTransaction` with `invoice_id`.
  - Ensure idempotency so repeated calls do not duplicate entries.

- [ ] **Step 3: Run tests**

Run: `pytest backend/tests/test_manual_pay_and_accounting_sync.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/commerce.py backend/app/routers/commerce.py backend/tests/test_manual_pay_and_accounting_sync.py
git commit -m "feat(commerce): add manual payment recording and auto-sync with accounting"
```

---

### Task 5: Admin Invoice Management UI Upgrade (`CommerceAdmin.jsx`)

**Files:**
- Modify: `frontend/src/pages/CommerceAdmin.jsx`
- Modify: `frontend/src/lib/api.js`
- Create: `frontend/src/__tests__/commerceAdminEnhancements.test.jsx`

**Interfaces:**
- Produces: Debounced search bar (customer name, mobile, invoice ID)
- Produces: Status segmented tabs (all, draft, approved, paid, cancelled/expired)
- Produces: Manual payment modal
- Produces: Printable postal packing slip modal (`@media print` styled)
- Produces: Gateway reference code badges on paid cards

- [ ] **Step 1: Write frontend test for CommerceAdmin search, tabs, and modals**

```jsx
// frontend/src/__tests__/commerceAdminEnhancements.test.jsx
import { render, screen, fireEvent } from '@testing-library/react';
import CommerceAdmin from '../pages/CommerceAdmin';

test('renders status tabs and filters invoices', async () => {
  // test tab switching and modal triggers
});
```

- [ ] **Step 2: Update CommerceAdmin.jsx with new tabs, search, manual-pay and postal slip**

Implement in `frontend/src/pages/CommerceAdmin.jsx`:
- Tabs for `all`, `draft`, `approved`, `paid`, `cancelled_or_expired`.
- Search input with clear button and 300ms debounce.
- Postal packing slip dialog with print button and "کپی آدرس گیرنده" action.
- Manual payment modal with Shamsi date input.

- [ ] **Step 3: Run frontend tests**

Run: `npm --prefix frontend test -- commerceAdminEnhancements`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/CommerceAdmin.jsx frontend/src/lib/api.js frontend/src/__tests__/commerceAdminEnhancements.test.jsx
git commit -m "feat(admin): upgrade invoices with search, status tabs, manual payment and postal labels"
```

---

### Task 6: Frontend Accounting Module (`Accounting.jsx`) & Navigation

**Files:**
- Create: `frontend/src/pages/Accounting.jsx`
- Modify: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/lib/api.js`
- Create: `frontend/src/__tests__/accountingPage.test.jsx`

**Interfaces:**
- Produces: Route `/accounting` gated by `ProtectedRoute`
- Produces: Sidebar nav item «دفتر حسابداری» with `CircleDollarSign` / `Calculator` icon
- Produces: KPI cards, Shamsi date filtering, Add Expense/Income modals, Categories management drawer, and transaction table with CSV export.

- [ ] **Step 1: Write frontend test for Accounting page**

```jsx
// frontend/src/__tests__/accountingPage.test.jsx
import { render, screen } from '@testing-library/react';
import Accounting from '../pages/Accounting';

test('renders KPI cards and transaction table', async () => {
  // verify summary metrics and action buttons
});
```

- [ ] **Step 2: Create frontend/src/pages/Accounting.jsx**

Implement:
- Top KPI summary cards (درآمد کل، مجموع هزینه‌ها، سود خالص، حاشیه سود).
- Shamsi period switcher (ماه جاری، سال جاری، بازه دلخواه).
- Transactions table with category badges, invoice link pills, receipt preview links, and CSV download.
- Add Transaction modal (type, title, category, amount, Shamsi date, account, reference, receipt upload).
- Categories management modal.

- [ ] **Step 3: Register route and sidebar navigation**

In `frontend/src/App.jsx` and `frontend/src/components/Sidebar.jsx`:
- Add `const Accounting = lazy(() => import('./pages/Accounting'));`
- Add route `<Route path="/accounting" element={<ProtectedRoute><Layout><Accounting /></Layout></ProtectedRoute>} />`
- Add navItem `{ path: '/accounting', label: 'دفتر حسابداری', icon: Landmark }`.

- [ ] **Step 4: Run frontend tests and build check**

Run: `npm --prefix frontend test -- accountingPage`
Run: `npm --prefix frontend run build`
Expected: PASS with 0 build errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Accounting.jsx frontend/src/components/Sidebar.jsx frontend/src/App.jsx frontend/src/lib/api.js frontend/src/__tests__/accountingPage.test.jsx
git commit -m "feat(ui): add accounting management page and sidebar navigation"
```

---

### Task 7: End-to-End System Verification & Final Smoke Test

**Files:**
- Run: Full backend pytest test suite
- Run: Full frontend test suite & Vite production build

- [ ] **Step 1: Run full backend test suite**
Run: `pytest backend/tests -v`
Expected: All tests PASS.

- [ ] **Step 2: Run full frontend test suite**
Run: `npm --prefix frontend test -- --run`
Expected: All tests PASS.

- [ ] **Step 3: Run frontend production build**
Run: `npm --prefix frontend run build`
Expected: Exit code 0, dist bundle successfully created.

- [ ] **Step 4: Final commit and summary**
```bash
git status
git commit -m "chore: complete accounting module, invoice improvements, and customer pay integration"
```
