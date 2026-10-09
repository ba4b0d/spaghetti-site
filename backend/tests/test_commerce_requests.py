"""Task 1 — public cart request intake and staff request listing.

Covers the public ``POST /api/v1/commerce/requests`` endpoint and the
staff-only ``GET /api/v1/commerce/staff/requests`` listing from the approved
commerce plan (docs/superpowers/plans/2026-10-10-order-invoice-payments.md).
"""
import pytest


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


def test_price_tampering_is_ignored(client, auth_headers):
    """A client-supplied price must never be trusted or stored."""
    product = _create_product(client, auth_headers, name="کالای قیمتی", price=75000)

    payload = _valid_payload(product["id"], qty=2)
    payload["items"][0]["unit_price"] = 1
    payload["items"][0]["unit_toman"] = 1
    payload["total"] = 1

    r = client.post("/api/v1/commerce/requests", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "pending_review"

    # Server snapshots the catalogue indicative price, not the tampered value.
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
    payload = _valid_payload(product["id"])
    statuses = [client.post("/api/v1/commerce/requests", json=payload).status_code for _ in range(6)]
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
