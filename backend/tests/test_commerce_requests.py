"""Task 1 — public cart request intake and staff request listing.

Covers the public ``POST /api/v1/commerce/requests`` endpoint and the
staff-only ``GET /api/v1/commerce/staff/requests`` listing from the approved
commerce plan (docs/superpowers/plans/2026-10-10-order-invoice-payments.md).
"""
import pytest

from tests.otp_helpers import issue_test_otp


@pytest.fixture(autouse=True)
def _clear_rate_limiter(client):
    """Clear slowapi counters between tests.

    ``app.state.limiter`` keeps a persistent in-memory store shared by the
    whole test module. The conftest client fixture only swaps ``_storage``,
    not the strategy (``_limiter``) that actually counts hits, so reset the
    strategy's real storage directly or public POST tests trip the shared
    5/minute budget.
    """
    from app.main import app

    app.state.limiter._limiter.storage.reset()
    yield


def _create_product(client, auth_headers, *, name="محصول تستی", price=50000, **extra):
    payload = {
        "name": name,
        "weight_g": 40,
        "print_time_hours": 1,
        "final_price": price,
        **extra,
    }
    resp = client.post("/api/v1/products", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _valid_payload(product_id, qty=2, **overrides):
    payload = {
        "customer_name": "رضا",
        "mobile": "09123456789",
        "messenger": "telegram",
        "items": [{"product_id": product_id, "qty": qty}],
        # The public gate now requires a verified one-time code. Mint a live
        # challenge for the default mobile so these intake tests still exercise
        # the request contract; the OTP path itself is covered in
        # test_commerce_otp.py. No SMS is ever sent (see tests/otp_helpers.py).
        **issue_test_otp(),
    }
    payload.update(overrides)
    return payload


# ── Public submission ────────────────────────────────────────────────

def test_guest_submission_creates_pending_review_request(client, auth_headers):
    product = _create_product(client, auth_headers, name="فیگور تستی", price=120000)

    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], qty=2))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "pending_review"
    assert isinstance(body["receipt_id"], str) and body["receipt_id"]
    # Public response must never hand out a payable link before staff review.
    assert "payment_url" not in body
    assert "invoice_url" not in body


def test_guest_submission_requires_no_auth(client, auth_headers):
    product = _create_product(client, auth_headers)
    # No auth headers and no cookies on the public intake endpoint.
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"]))
    assert r.status_code == 200, r.text


def test_surplus_price_fields_are_rejected(client, auth_headers):
    """Surplus fields — including client prices — are rejected, not ignored.

    Task 1 brief Step 2: "Disallow surplus fields on the public payload to
    avoid silent price acceptance." A tampered request must fail validation
    (422) and persist nothing.
    """
    product = _create_product(client, auth_headers, name="کالای قیمتی", price=75000)

    # Surplus field nested on a line item.
    item_payload = _valid_payload(product["id"], qty=2)
    item_payload["items"][0]["unit_price"] = 1
    r = client.post("/api/v1/commerce/requests", json=item_payload)
    assert r.status_code == 422, r.text

    # Surplus field at the top level.
    top_payload = _valid_payload(product["id"], qty=2)
    top_payload["total"] = 1
    r2 = client.post("/api/v1/commerce/requests", json=top_payload)
    assert r2.status_code == 422, r2.text

    # Rejected attempts must not have stored anything.
    listing = client.get("/api/v1/commerce/staff/requests", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json() == []


def test_server_snapshots_catalogue_price(client, auth_headers):
    """The stored indicative price is the server catalogue value, never client data."""
    product = _create_product(client, auth_headers, name="کالای قیمتی", price=75000)

    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], qty=2))
    assert r.status_code == 200, r.text

    # Server snapshots the catalogue indicative price, not any client value.
    listing = client.get("/api/v1/commerce/staff/requests", headers=auth_headers)
    assert listing.status_code == 200
    requests = listing.json()
    assert len(requests) == 1
    item = requests[0]["items"][0]
    assert item["product_id"] == product["id"]
    assert item["qty"] == 2
    assert item["indicative_unit_price_toman"] == 75000


def test_item_snapshot_keeps_display_name(client, auth_headers):
    product = _create_product(client, auth_headers, name="جاکلیدی گربه", price=30000)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"]))
    assert r.status_code == 200

    listing = client.get("/api/v1/commerce/staff/requests", headers=auth_headers).json()
    assert listing[0]["items"][0]["display_name"] == "جاکلیدی گربه"


def test_inactive_product_is_rejected(client, auth_headers):
    product = _create_product(client, auth_headers, name="غیرفعال")
    upd = client.put(f"/api/v1/products/{product['id']}", json={"is_active": False}, headers=auth_headers)
    assert upd.status_code in (200, 201), upd.text

    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"]))
    assert r.status_code == 400, r.text


def test_missing_product_is_rejected(client, auth_headers):
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(999999))
    assert r.status_code == 400, r.text


def test_empty_items_rejected(client):
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(1, ) | {"items": []})
    assert r.status_code == 422


def test_duplicate_product_ids_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    payload = _valid_payload(product["id"])
    payload["items"] = [
        {"product_id": product["id"], "qty": 1},
        {"product_id": product["id"], "qty": 2},
    ]
    r = client.post("/api/v1/commerce/requests", json=payload)
    assert r.status_code == 422


def test_too_many_items_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    payload = _valid_payload(product["id"])
    # 31 items exceeds the 1..30 limit (duplicate ids also invalid, so use
    # distinct fake ids to isolate the count constraint).
    payload["items"] = [{"product_id": 10_000 + i, "qty": 1} for i in range(31)]
    r = client.post("/api/v1/commerce/requests", json=payload)
    assert r.status_code == 422


# ── Payload validation ───────────────────────────────────────────────

@pytest.mark.parametrize("mobile", ["0812345678", "0912345678a", "091234567890", "9123456789", ""])
def test_invalid_mobile_rejected(client, auth_headers, mobile):
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], mobile=mobile))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "mobile",
    [
        "09١٢٣٤٥٦٧٨٩",  # Arabic-Indic digits (isdigit() is True — must be rejected)
        "0912345678۹",   # ASCII prefix + one Persian digit, correct length
        "۰۹۱۲۳۴۵۶۷۸۹",   # all Persian-Indic digits
    ],
)
def test_non_ascii_mobile_rejected(client, auth_headers, mobile):
    """Only ASCII digits are valid: mixed-script numbers are undialable."""
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], mobile=mobile))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("qty", [0, -1, 100])
def test_invalid_quantity_rejected(client, auth_headers, qty):
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], qty=qty))
    assert r.status_code == 422, r.text


def test_invalid_messenger_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], messenger="whatsapp"))
    assert r.status_code == 422


def test_empty_customer_name_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], customer_name=""))
    assert r.status_code == 422


def test_huge_note_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    r = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"], note="x" * 2001))
    assert r.status_code == 422


def test_huge_handle_and_address_rejected(client, auth_headers):
    product = _create_product(client, auth_headers)
    r1 = client.post(
        "/api/v1/commerce/requests",
        json=_valid_payload(product["id"], messenger_handle="h" * 101),
    )
    assert r1.status_code == 422
    r2 = client.post(
        "/api/v1/commerce/requests",
        json=_valid_payload(product["id"], address="a" * 501),
    )
    assert r2.status_code == 422


def test_boundary_payload_is_accepted(client, auth_headers):
    """Exactly 30 distinct products and max qty is inside the allowed envelope."""
    items = []
    for i in range(30):
        p = _create_product(client, auth_headers, name=f"محصول {i}", price=1000 + i)
        items.append({"product_id": p["id"], "qty": 99})

    payload = _valid_payload(items[0]["product_id"])
    payload["items"] = items
    r = client.post("/api/v1/commerce/requests", json=payload)
    assert r.status_code == 200, r.text


def test_public_post_is_rate_limited(client, auth_headers):
    product = _create_product(client, auth_headers)
    # A fresh challenge per POST: the OTP is single-use, so reusing one payload
    # would fail the gate (400) before the limiter is reached.
    statuses = [
        client.post(
            "/api/v1/commerce/requests", json=_valid_payload(product["id"])
        ).status_code
        for _ in range(6)
    ]
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


# ── Staff listing ────────────────────────────────────────────────────

def test_staff_listing_requires_auth(client):
    r = client.get("/api/v1/commerce/staff/requests")
    assert r.status_code in (401, 403)


def test_staff_listing_returns_requests_with_snapshots(client, auth_headers):
    p1 = _create_product(client, auth_headers, name="الف", price=10000)
    p2 = _create_product(client, auth_headers, name="ب", price=25000)

    payload = _valid_payload(p1["id"], qty=1)
    payload["items"] = [{"product_id": p1["id"], "qty": 1}, {"product_id": p2["id"], "qty": 3}]
    assert client.post("/api/v1/commerce/requests", json=payload).status_code == 200

    r = client.get("/api/v1/commerce/staff/requests", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "pending_review"
    assert row["customer_name"] == "رضا"
    assert row["mobile"] == "09123456789"
    assert len(row["items"]) == 2
    assert {i["display_name"] for i in row["items"]} == {"الف", "ب"}


def test_staff_listing_ordered_newest_first(client, auth_headers):
    product = _create_product(client, auth_headers)
    first = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"])).json()
    second = client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"])).json()

    rows = client.get("/api/v1/commerce/staff/requests", headers=auth_headers).json()
    assert [r["receipt_id"] for r in rows] == [second["receipt_id"], first["receipt_id"]]


def test_employee_can_list_requests(client, auth_headers, employee_headers):
    product = _create_product(client, auth_headers)
    assert client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"])).status_code == 200
    r = client.get("/api/v1/commerce/staff/requests", headers=employee_headers)
    assert r.status_code == 200


def test_staff_listing_is_bounded_and_filterable(client, auth_headers):
    """The review queue is paginated/filterable but still a plain array."""
    product = _create_product(client, auth_headers)
    for _ in range(3):
        assert client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"])).status_code == 200

    # No params -> default page, still a bare JSON array (existing clients).
    all_rows = client.get("/api/v1/commerce/staff/requests", headers=auth_headers).json()
    assert isinstance(all_rows, list) and len(all_rows) == 3

    # limit caps the page size (newest first).
    capped = client.get("/api/v1/commerce/staff/requests?limit=2", headers=auth_headers).json()
    assert [r["receipt_id"] for r in capped] == [r["receipt_id"] for r in all_rows[:2]]

    # offset pages forward without overlap.
    page2 = client.get(
        "/api/v1/commerce/staff/requests?limit=2&offset=2", headers=auth_headers
    ).json()
    assert [r["receipt_id"] for r in page2] == [all_rows[2]["receipt_id"]]

    # Absurd limits are rejected rather than loading the whole table.
    assert client.get(
        "/api/v1/commerce/staff/requests?limit=100000", headers=auth_headers
    ).status_code == 422

    # state filter narrows the queue.
    pending = client.get(
        "/api/v1/commerce/staff/requests?state=pending_review", headers=auth_headers
    ).json()
    assert len(pending) == 3
    assert client.get(
        "/api/v1/commerce/staff/requests?state=cancelled", headers=auth_headers
    ).json() == []


def _session_engine():
    """Engine backing the test client's DB dependency override."""
    from app.database import get_db
    from app.main import app

    gen = app.dependency_overrides[get_db]()
    session = next(gen)
    try:
        return session.get_bind()
    finally:
        session.close()


def test_staff_listing_avoids_n_plus_one(client, auth_headers):
    """Items are eager-loaded: statement count stays flat as requests grow."""
    from sqlalchemy import event

    product = _create_product(client, auth_headers)
    for _ in range(5):
        assert client.post("/api/v1/commerce/requests", json=_valid_payload(product["id"])).status_code == 200

    engine = _session_engine()
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        r = client.get("/api/v1/commerce/staff/requests", headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert r.status_code == 200
    assert len(r.json()) == 5
    # selectinload = a constant number of statements (main + one IN load), not
    # 1 + N (which would be ~6+ here and grow with the queue).
    assert len(statements) <= 3, statements


# ── Product permanent delete preserves review snapshots ──────────────

def test_permanent_delete_preserves_request_snapshots(client, auth_headers):
    """Deleting a product detaches (does not delete) historical request items."""
    product = _create_product(client, auth_headers, name="محصول حذفی", price=42000)
    assert client.post(
        "/api/v1/commerce/requests", json=_valid_payload(product["id"], qty=3)
    ).status_code == 200

    r = client.delete(f"/api/v1/products/{product['id']}/permanent", headers=auth_headers)
    assert r.status_code == 200, r.text

    # The request and its snapshot survive; only the product link is cleared.
    rows = client.get("/api/v1/commerce/staff/requests", headers=auth_headers).json()
    assert len(rows) == 1
    item = rows[0]["items"][0]
    assert item["product_id"] is None
    assert item["display_name"] == "محصول حذفی"
    assert item["qty"] == 3
    assert item["indicative_unit_price_toman"] == 42000


def test_permanent_delete_handles_legacy_items_table(client, auth_headers):
    """Route-level unlink covers DBs whose items table predates ondelete=SET NULL.

    SQLite cannot ALTER a foreign key on an existing table, so a pre-existing
    ``commerce_request_items`` (created without ON DELETE SET NULL) would still
    raise IntegrityError on a bare product delete. Recreate that legacy shape
    and prove the explicit unlink keeps the delete succeeding and the snapshot
    intact.
    """
    from sqlalchemy import text

    product = _create_product(client, auth_headers, name="محصول قدیمی", price=42000)

    engine = _session_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE commerce_request_items"))
        conn.execute(text(
            "CREATE TABLE commerce_request_items ("
            "id INTEGER PRIMARY KEY, "
            "request_id INTEGER NOT NULL, "
            "product_id INTEGER, "
            "display_name VARCHAR(255) NOT NULL DEFAULT '', "
            "qty INTEGER NOT NULL DEFAULT 1, "
            "indicative_unit_price_toman INTEGER, "
            "FOREIGN KEY(request_id) REFERENCES commerce_requests(id) ON DELETE CASCADE, "
            "FOREIGN KEY(product_id) REFERENCES products(id))"
        ))

    assert client.post(
        "/api/v1/commerce/requests", json=_valid_payload(product["id"], qty=2)
    ).status_code == 200

    r = client.delete(f"/api/v1/products/{product['id']}/permanent", headers=auth_headers)
    assert r.status_code == 200, r.text

    rows = client.get("/api/v1/commerce/staff/requests", headers=auth_headers).json()
    assert rows[0]["items"][0]["product_id"] is None
    assert rows[0]["items"][0]["display_name"] == "محصول قدیمی"


# ── OTP consumption is atomic with request creation ──────────────────

def _otp_payload(product_id, qty=1, **overrides):
    """A payload bound to ONE explicit challenge (unlike ``_valid_payload``)."""
    payload = {
        "customer_name": "رضا",
        "mobile": "09123456789",
        "messenger": "telegram",
        "items": [{"product_id": product_id, "qty": qty}],
    }
    payload.update(overrides)
    return payload


def test_failed_creation_does_not_burn_the_otp(client, auth_headers):
    """A rejected creation (inactive product) must leave the code usable.

    The OTP is claimed in the same transaction as the request, so a validation
    failure rolls the claim back. The customer can retry with the *same* code
    instead of being stranded until the resend cooldown expires.
    """
    active = _create_product(client, auth_headers, name="فعال", price=50000)
    inactive = _create_product(client, auth_headers, name="غیرفعال", price=50000)
    upd = client.put(
        f"/api/v1/products/{inactive['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert upd.status_code in (200, 201), upd.text

    otp = issue_test_otp()  # one challenge, deliberately reused across attempts

    rejected = client.post(
        "/api/v1/commerce/requests",
        json=_otp_payload(inactive["id"], **otp),
    )
    assert rejected.status_code == 400, rejected.text
    assert client.get(
        "/api/v1/commerce/staff/requests", headers=auth_headers
    ).json() == []

    # Same challenge + code, valid cart: the failed attempt did NOT consume it.
    ok = client.post(
        "/api/v1/commerce/requests",
        json=_otp_payload(active["id"], **otp),
    )
    assert ok.status_code == 200, ok.text
    assert len(client.get(
        "/api/v1/commerce/staff/requests", headers=auth_headers
    ).json()) == 1


def test_otp_is_single_use_across_two_submissions(client, auth_headers):
    """After a successful request the challenge is consumed — no reuse."""
    product = _create_product(client, auth_headers)
    otp = issue_test_otp()

    first = client.post("/api/v1/commerce/requests", json=_otp_payload(product["id"], **otp))
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/commerce/requests", json=_otp_payload(product["id"], **otp))
    assert second.status_code == 400, second.text

    assert len(client.get(
        "/api/v1/commerce/staff/requests", headers=auth_headers
    ).json()) == 1
