"""Admin-only, audited recovery of an already-paid *legacy* BitPay attempt.

A pre-fix BitPay attempt persisted the historical alnum merchant reference
``INV<id>-R<rev>-<hex>`` as ``provider_id`` and sent it as ``factorId``. The
documented gateway coerces any non-Integer factor to ``0`` on the verify reply,
so such a row can never be matched by the ordinary callback or a routine staff
``verify`` reconcile — both correctly fail closed and hold the lock.

This suite pins the single, explicit, admin-only recovery path that closes that
gap safely. Everything runs offline: the provider is injected through the
``bitpay.client_dependency`` FastAPI override and every reply is scripted, so no
socket is opened and no real gateway is ever contacted.

Covered here:

* admin-only access (anonymous and employee are refused);
* happy-path settlement — one paid order, ``verified`` attempt, audited;
* eligibility refusals (non-BitPay, modern numeric factor, wrong revision);
* provider-mismatch refusals (amount, nonzero factor, non-success, unreachable);
* persisted-evidence requirement (``id_get`` *and* ``trans_id``);
* replay idempotency (never a second order);
* no unsafe abandon (a refused recovery keeps the lock, never ``failed``);
* no card/PII leakage into the staff payload or ``last_error``.
"""
import pytest

from tests.test_bitpay_commerce import (
    BASE,
    FakeBitPay,
    invoice_state,
    latest_attempt,
    make_approved,
    order_for,
)

RECOVER_TMPL = BASE + "/staff/payments/{attempt_id}/recover-legacy-bitpay"

# The exact card number the fake verify echoes; it must never reach the staff
# payload or an error string.
FAKE_CARD = "6037990000001234"


@pytest.fixture()
def fake_bitpay(client, monkeypatch):
    """Offline BitPay fake injected as the provider dependency (no network)."""
    from app.main import app
    from app.services import bitpay

    fake = FakeBitPay()
    app.dependency_overrides[bitpay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(bitpay.client_dependency, None)


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _invoice_amount_rial(invoice_id):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return db.get(CommerceInvoice, invoice_id).total_toman * 10
    finally:
        db.close()


def _make_elder_bitpay_attempt(
    invoice_id,
    *,
    id_get,
    trans_id=12345,
    state="unknown",
    provider_id="INV3-R1-deadbeef",
    provider="bitpay",
    revision=None,
    amount_rial=None,
):
    """Insert an attempt directly, defaulting to the pre-fix legacy shape."""
    from app.models import CommerceInvoice, CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        attempt = CommercePaymentAttempt(
            invoice_id=invoice_id,
            provider=provider,
            state=state,
            provider_id=provider_id,
            amount_rial=amount_rial if amount_rial is not None else invoice.total_toman * 10,
            invoice_revision=revision if revision is not None else invoice.revision,
            type=0,
            tracking_code=None if id_get is None else str(id_get),
            provider_trans_id=trans_id,
            redirect_url=None if id_get is None else f"https://bitpay.ir/payment/gateway-{id_get}-get",
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return attempt.id
    finally:
        db.close()


def _legacy_session(fake, *, id_get, amount_rial, factor_id="0"):
    """Script the gateway reply for a legacy transaction (factorId artifact)."""
    fake.sessions[id_get] = {"factor_id": factor_id, "amount_rial": amount_rial}


def _recover(client, attempt_id, headers, *, reason="پرداخت واقعی مشتری تأیید شد", confirm=True):
    return client.post(
        RECOVER_TMPL.format(attempt_id=attempt_id),
        json={"confirm_legacy_recovery": confirm, "reason": reason},
        headers=headers,
    )


def _audit_rows(**filters):
    from app.models import AuditLog
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        query = db.query(AuditLog)
        for key, value in filters.items():
            query = query.filter(getattr(AuditLog, key) == value)
        return query.all()
    finally:
        db.close()


def _order_count(invoice_id):
    from app.models import CommerceInvoice, Order
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        invoice = db.get(CommerceInvoice, invoice_id)
        return 0 if invoice.order_id is None else db.query(Order).filter(Order.id == invoice.order_id).count()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Access control — never public, admin only
# ══════════════════════════════════════════════════════════════════════

def test_recovery_is_not_public(client, auth_headers, fake_bitpay):
    """Anonymous callers are refused and nothing is settled."""
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=_invoice_amount_rial(invoice_id))

    r = client.post(RECOVER_TMPL.format(attempt_id=attempt_id), json={"reason": "x", "confirm_legacy_recovery": True})
    assert r.status_code in (401, 403), r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"
    assert fake_bitpay.verify_calls == []


def test_recovery_denied_for_employee(client, auth_headers, employee_headers, fake_bitpay):
    """An employee is not an admin: refused, and never settled."""
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=_invoice_amount_rial(invoice_id))

    r = _recover(client, attempt_id, employee_headers)
    assert r.status_code == 403, r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"
    assert fake_bitpay.verify_calls == []


def test_recovery_requires_explicit_reason_and_affirmation(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=_invoice_amount_rial(invoice_id))

    # no affirmation
    assert _recover(client, attempt_id, auth_headers, confirm=False).status_code == 422
    # blank reason
    blank = client.post(
        RECOVER_TMPL.format(attempt_id=attempt_id),
        json={"confirm_legacy_recovery": True, "reason": ""},
        headers=auth_headers,
    )
    assert blank.status_code == 422
    assert invoice_state(invoice_id) == "approved"
    assert fake_bitpay.verify_calls == []


def test_recovery_unknown_attempt_is_404(client, auth_headers, fake_bitpay):
    assert _recover(client, 999999, auth_headers).status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Happy path — settles once, links one order, audits
# ══════════════════════════════════════════════════════════════════════

def test_recovery_settles_legacy_payment_and_audits(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "verified"
    assert body["reconciliation_required"] is False

    # verified server-to-server through the injected provider, using the
    # attempt's OWN persisted id_get + trans_id (never request-supplied values)
    assert fake_bitpay.verify_calls == [{"trans_id": 12345, "id_get": fake_bitpay.id_get}]

    assert invoice_state(invoice_id) == "paid"
    order = order_for(invoice_id)
    assert order is not None
    assert order.paid_amount == 312000
    assert order.status == "new"
    assert "بیت‌پی" in order.notes

    refreshed = latest_attempt(invoice_id)
    assert refreshed.state == "verified"
    assert refreshed.tracking_code == str(fake_bitpay.id_get)

    # audited in the same transaction as the settlement
    rows = _audit_rows(entity="commerce_payment_attempt", entity_id=attempt_id)
    assert len(rows) == 1
    assert rows[0].action == "recover_legacy_bitpay"
    assert rows[0].user == "admin"
    assert "بیت‌پی" in rows[0].summary


def test_recovery_payload_never_leaks_card_or_pii(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 200, r.text
    assert FAKE_CARD not in r.text
    assert FAKE_CARD not in (latest_attempt(invoice_id).last_error or "")


def test_recovery_accepts_already_verified_status_11(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)
    fake_bitpay.verify_status = 11

    assert _recover(client, attempt_id, auth_headers).status_code == 200
    assert invoice_state(invoice_id) == "paid"


# ══════════════════════════════════════════════════════════════════════
# Eligibility — only a legacy alnum attempt on its current payable invoice
# ══════════════════════════════════════════════════════════════════════

def test_recovery_rejects_modern_numeric_factor_attempt(client, auth_headers, fake_bitpay):
    """A post-fix attempt has a numeric factorId: it must settle through the
    ordinary path, never this weaker zero-factor recovery."""
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, provider_id="4242"
    )
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=_invoice_amount_rial(invoice_id))

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"
    assert fake_bitpay.verify_calls == []


def test_recovery_rejects_non_bitpay_attempt(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, provider="digipay", provider_id="INV7-R1-cafe"
    )

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert fake_bitpay.verify_calls == []


def test_recovery_rejects_non_unknown_state(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, state="pending"
    )
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=_invoice_amount_rial(invoice_id))

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert fake_bitpay.verify_calls == []


def test_recovery_requires_persisted_id_get_and_trans_id(client, auth_headers, fake_bitpay):
    # Two separate invoices: one in-flight attempt per invoice (partial unique
    # index), so each missing-evidence case gets its own payable invoice.
    inv_a, _ = make_approved(client, auth_headers)
    no_id_get = _make_elder_bitpay_attempt(inv_a, id_get=None)
    assert _recover(client, no_id_get, auth_headers).status_code == 409

    inv_b, _ = make_approved(client, auth_headers)
    no_trans = _make_elder_bitpay_attempt(
        inv_b, id_get=fake_bitpay.id_get, trans_id=None, provider_id="INV4-R1-deadbeef"
    )
    assert _recover(client, no_trans, auth_headers).status_code == 409

    assert fake_bitpay.verify_calls == []
    assert invoice_state(inv_a) == "approved"
    assert invoice_state(inv_b) == "approved"


def test_recovery_rejects_revision_mismatch(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(
        invoice_id, id_get=fake_bitpay.id_get, revision=99
    )
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert invoice_state(invoice_id) == "approved"
    assert fake_bitpay.verify_calls == []


def test_recovery_rejects_non_payable_invoice(client, auth_headers, fake_bitpay):
    from app.models import CommerceInvoice
    from tests.conftest import TestSessionLocal

    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)

    db = TestSessionLocal()
    try:
        db.get(CommerceInvoice, invoice_id).state = "revoked"
        db.commit()
    finally:
        db.close()

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert fake_bitpay.verify_calls == []


# ══════════════════════════════════════════════════════════════════════
# Provider mismatch — never settle, never release the lock (no unsafe abandon)
# ══════════════════════════════════════════════════════════════════════

def test_recovery_amount_mismatch_keeps_lock(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=1)  # wrong amount

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert invoice_state(invoice_id) == "approved"
    held = latest_attempt(invoice_id)
    assert held.state == "unknown"                      # lock held, never failed
    assert held.reconciliation_required is False
    assert _order_count(invoice_id) == 0
    # a refused recovery is never audited as a settlement
    assert _audit_rows(entity="commerce_payment_attempt", entity_id=attempt_id) == []


def test_recovery_nonzero_factor_keeps_lock(client, auth_headers, fake_bitpay):
    """A numeric (non-artifact) factorId must not pass the zero-factor check."""
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial, factor_id="7")

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"


def test_recovery_missing_factor_echo_keeps_lock(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial, factor_id=None)

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert latest_attempt(invoice_id).state == "unknown"


def test_recovery_non_success_status_keeps_lock(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)
    fake_bitpay.verify_status = -4

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 409, r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"


def test_recovery_provider_unreachable_keeps_lock(client, auth_headers, fake_bitpay):
    from app.services.bitpay import BitPayError

    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)
    fake_bitpay.verify_error = BitPayError("timeout")

    r = _recover(client, attempt_id, auth_headers)
    assert r.status_code == 502, r.text
    assert invoice_state(invoice_id) == "approved"
    assert latest_attempt(invoice_id).state == "unknown"


# ══════════════════════════════════════════════════════════════════════
# Lock-safe idempotency — a replay never creates a second order
# ══════════════════════════════════════════════════════════════════════

def test_recovery_replay_is_idempotent_single_order(client, auth_headers, fake_bitpay):
    invoice_id, _ = make_approved(client, auth_headers)
    amount_rial = _invoice_amount_rial(invoice_id)
    attempt_id = _make_elder_bitpay_attempt(invoice_id, id_get=fake_bitpay.id_get)
    _legacy_session(fake_bitpay, id_get=fake_bitpay.id_get, amount_rial=amount_rial)

    first = _recover(client, attempt_id, auth_headers)
    assert first.status_code == 200, first.text
    calls = list(fake_bitpay.verify_calls)

    second = _recover(client, attempt_id, auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["state"] == "verified"

    assert invoice_state(invoice_id) == "paid"
    assert _order_count(invoice_id) == 1                 # never a second order
    # the replay short-circuits on the terminal state: no extra provider query
    assert fake_bitpay.verify_calls == calls
    # and exactly one audit entry for the single real recovery
    assert len(_audit_rows(entity="commerce_payment_attempt", entity_id=attempt_id)) == 1
