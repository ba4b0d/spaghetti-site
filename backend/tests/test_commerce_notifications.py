"""Task 4 — admin Telegram / SMS.ir / SMTP notifications (backend only).

Covered here:

* The three independent channels, their environment configuration and the
  "credentials absent => skip" rule (no network call is ever made).
* Per-channel failure isolation: one channel raising never raises out of
  ``notify_admin`` and never rolls back a committed order/invoice.
* Content safety: HTML escaping of user text, PII minimization (masked phone,
  no address) and a hard rule that a private invoice bearer token / share link
  never appears in an admin broadcast.
* The after-commit event wiring (``request_created`` / ``invoice_approved`` /
  ``payment_verified``) and the duplicate-callback rule: a replayed DigiPay
  callback emits the paid alert exactly once.

Nothing here talks to a live provider: every transport (``requests`` session,
SMTP client, Telegram sender) is replaced by a fake.
"""
import pytest

from app.services import commerce_notifications as cn

BASE = "/api/v1/commerce"

# Every env var the notification module consults; cleared before each test so a
# developer's real .env can never make these tests send anything.
NOTIFY_ENV_VARS = (
    "COMMERCE_NOTIFY_TELEGRAM",
    "COMMERCE_NOTIFY_SMS",
    "SMS_IR_API_KEY",
    "SMS_IR_TEMPLATE_ID",
    "SMS_IR_ADMIN_MOBILE",
    "COMMERCE_NOTIFY_SMTP",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_ADMIN_TO",
    "SMTP_TLS",
)


@pytest.fixture(autouse=True)
def _clean_notify_env(client, monkeypatch):
    for var in NOTIFY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Telegram config is also read from the Settings table of the *real*
    # database, so neutralise it here: the "absent credentials" tests must not
    # depend on whether a developer has a real bot configured.
    monkeypatch.setattr(cn, "get_telegram_config", lambda: ("", [], None))
    from app.main import app

    app.state.limiter._limiter.storage.reset()
    yield


def _configure_sms(monkeypatch, *, key="k", template="100", mobile="09120000000"):
    monkeypatch.setenv("SMS_IR_API_KEY", key)
    monkeypatch.setenv("SMS_IR_TEMPLATE_ID", template)
    monkeypatch.setenv("SMS_IR_ADMIN_MOBILE", mobile)


def _configure_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("SMTP_ADMIN_TO", "owner@example.com")
    monkeypatch.setenv("SMTP_TLS", "starttls")


# ══════════════════════════════════════════════════════════════════════
# Fake transports (no network)
# ══════════════════════════════════════════════════════════════════════


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


class _FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)


def _smtp_factory(instances):
    def factory(host, port, timeout=None):
        smtp = _FakeSMTP(host, port, timeout=timeout)
        instances.append(smtp)
        return smtp

    return factory


# ══════════════════════════════════════════════════════════════════════
# Skip / configure / isolation — notify_admin
# ══════════════════════════════════════════════════════════════════════


def test_notify_skips_every_channel_when_unconfigured(monkeypatch):
    """No credentials => every channel is skipped and no transport is touched."""
    calls = {"sms": 0, "smtp": 0}

    monkeypatch.setattr(cn, "post_sms_ir_verify", lambda **kw: calls.__setitem__("sms", calls["sms"] + 1) or True)
    monkeypatch.setattr(cn, "send_smtp_mail", lambda **kw: calls.__setitem__("smtp", calls["smtp"] + 1) or True)
    # Telegram is unconfigured: the existing sender returns False.
    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": False)

    class _Subject:
        receipt_id = "REQ-ABCDEF"
        customer_name = "رضا"
        mobile = "09123456789"
        messenger = "telegram"
        messenger_handle = "@r"
        address = "تهران"
        state = "pending_review"
        items = []

    result = cn.notify_admin(cn.EVENT_REQUEST_CREATED, _Subject())

    assert result == {"telegram": cn.SKIPPED, "sms": cn.SKIPPED, "email": cn.SKIPPED}
    assert calls == {"sms": 0, "smtp": 0}


def test_notify_calls_all_three_channels_once_when_configured(monkeypatch):
    _configure_sms(monkeypatch)
    _configure_smtp(monkeypatch)
    sent = {"telegram": [], "sms": [], "email": []}

    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": sent["telegram"].append(text) or True)
    monkeypatch.setattr(cn, "post_sms_ir_verify", lambda **kw: sent["sms"].append(kw) or True)
    monkeypatch.setattr(cn, "send_smtp_mail", lambda **kw: sent["email"].append(kw) or True)

    class _Subject:
        receipt_id = "REQ-ABCDEF"
        customer_name = "رضا"
        mobile = "09123456789"
        messenger = "bale"
        messenger_handle = "@r"
        address = "تهران"
        state = "pending_review"
        items = []

    result = cn.notify_admin(cn.EVENT_REQUEST_CREATED, _Subject())

    assert result == {"telegram": cn.SENT, "sms": cn.SENT, "email": cn.SENT}
    assert len(sent["telegram"]) == 1
    assert len(sent["sms"]) == 1
    assert len(sent["email"]) == 1
    # SMS reached the *configured* admin number with the approved template id.
    assert sent["sms"][0]["mobile"] == "09120000000"
    assert sent["sms"][0]["template_id"] == 100
    # Email reached the configured admin mailbox.
    assert sent["email"][0]["config"]["recipient"] == "owner@example.com"


def test_notify_isolates_a_failing_channel(monkeypatch):
    """SMTP raising must not stop Telegram/SMS, and must not escape notify_admin."""
    _configure_sms(monkeypatch)
    _configure_smtp(monkeypatch)
    calls = {"telegram": 0, "sms": 0}

    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": calls.__setitem__("telegram", calls["telegram"] + 1) or True)
    monkeypatch.setattr(cn, "post_sms_ir_verify", lambda **kw: calls.__setitem__("sms", calls["sms"] + 1) or True)

    def _boom(**kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(cn, "send_smtp_mail", _boom)

    class _Subject:
        receipt_id = "REQ-ABCDEF"
        customer_name = "رضا"
        mobile = "09123456789"
        messenger = "telegram"
        messenger_handle = ""
        address = ""
        state = "pending_review"
        items = []

    result = cn.notify_admin(cn.EVENT_REQUEST_CREATED, _Subject())

    assert result == {"telegram": cn.SENT, "sms": cn.SENT, "email": cn.FAILED}
    assert calls == {"telegram": 1, "sms": 1}


def test_sms_provider_non_ack_is_failed_not_sent(monkeypatch):
    """Delivery is only claimed on a provider acknowledgement (status == 1)."""
    _configure_sms(monkeypatch)
    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": True)
    monkeypatch.setattr(cn, "send_smtp_mail", lambda **kw: True)
    # SMS.ir answers without a success status.
    monkeypatch.setattr(cn, "post_sms_ir_verify", lambda **kw: False)

    class _Subject:
        receipt_id = "REQ-ABCDEF"
        customer_name = "رضا"
        mobile = "09123456789"
        messenger = "telegram"
        messenger_handle = ""
        address = ""
        state = "pending_review"
        items = []

    result = cn.notify_admin(cn.EVENT_REQUEST_CREATED, _Subject())
    assert result["sms"] == cn.FAILED
    assert result["telegram"] == cn.SENT


# ══════════════════════════════════════════════════════════════════════
# Content safety
# ══════════════════════════════════════════════════════════════════════


def _fake_invoice(**kw):
    class _Item:
        def __init__(self, description, qty, unit_toman):
            self.description = description
            self.qty = qty
            self.unit_toman = unit_toman
            self.line_total_toman = qty * unit_toman

    class _Invoice:
        id = 42
        receipt_id = None
        customer_name = "رضا <b>خطر</b>"
        mobile = "09123456789"
        messenger = "telegram"
        messenger_handle = "@r"
        address = "تهران، خیابان تست"
        specification = "<script>alert(1)</script>"
        internal_note = "private"
        shipping_toman = 12000
        total_toman = 312000
        revision = 1
        state = "approved"
        order_id = None
        token_expires_at = None

        def __init__(self):
            self.items = [_Item("قطعه <i>آبی</i> & بزرگ", 2, 150000)]

    inv = _Invoice()
    for k, v in kw.items():
        setattr(inv, k, v)
    return inv


def test_telegram_message_html_escapes_user_text():
    inv = _fake_invoice()
    payload = cn.build_payload(cn.EVENT_INVOICE_APPROVED, inv)
    text = payload["telegram"]

    assert "&lt;b&gt;خطر&lt;/b&gt;" in text
    assert "<b>خطر</b>" not in text
    assert "&lt;i&gt;آبی&lt;/i&gt; &amp; بزرگ" in text
    assert "<i>آبی</i>" not in text


def test_notifications_minimize_pii():
    inv = _fake_invoice()
    payload = cn.build_payload(cn.EVENT_INVOICE_APPROVED, inv)

    full_mobile = "09123456789"
    assert full_mobile not in payload["telegram"]
    assert full_mobile not in payload["email_body"]
    # Masked phone is allowed, the full address is not broadcast.
    assert "0912*****89" in payload["telegram"]
    assert "تهران، خیابان تست" not in payload["telegram"]
    assert "تهران، خیابان تست" not in payload["email_body"]
    # Internal st <-> staff-only note never leaks.
    assert "private" not in payload["telegram"]
    assert "private" not in payload["email_body"]


def test_no_invoice_token_or_share_link_in_broadcast():
    raw_token = "SECRETTOKEN123456"
    inv = _fake_invoice()
    payload = cn.build_payload(cn.EVENT_INVOICE_APPROVED, inv)
    blob = " ".join([payload["telegram"], payload["email_subject"], payload["email_body"], str(payload["sms"])])
    assert raw_token not in blob
    assert "/pay/" not in blob


def test_sms_parameters_use_approved_uppercase_names():
    """SMS.ir matches approved-template parameter names EXACTLY (case-sensitive).

    Template ``309349`` is approved with placeholders ``#EVENT#`` / ``#CODE#``;
    lowercase ``event`` / ``code`` are not substituted and the provider rejects
    the send. The payload must therefore carry the exact uppercase names — this
    is the contract, not a style choice.
    """
    inv = _fake_invoice()
    payload = cn.build_payload(cn.EVENT_INVOICE_APPROVED, inv)
    sms = payload["sms"]

    assert [p["name"] for p in sms] == ["EVENT", "CODE"]
    assert {p["name"]: p["value"] for p in sms} == {"EVENT": "فاکتور", "CODE": "#42"}
    # No lowercase variant may sneak back in.
    assert all(p["name"] == p["name"].upper() for p in sms)


@pytest.mark.parametrize(
    "event,expected",
    [
        (cn.EVENT_REQUEST_CREATED, "درخواست"),
        (cn.EVENT_INVOICE_APPROVED, "فاکتور"),
        (cn.EVENT_PAYMENT_VERIFIED, "پرداخت"),
    ],
)
def test_sms_parameter_names_are_uppercase_for_every_event(event, expected):
    inv = _fake_invoice()
    sms = cn.build_payload(event, inv)["sms"]
    assert [p["name"] for p in sms] == ["EVENT", "CODE"]
    assert {p["name"]: p["value"] for p in sms}["EVENT"] == expected


# ══════════════════════════════════════════════════════════════════════
# Transport unit tests (SMS.ir / SMTP)
# ══════════════════════════════════════════════════════════════════════


def test_post_sms_ir_verify_shape_and_ack():
    session = _FakeSession([_FakeResp(200, {"status": 1, "message": "موفق", "data": {"messageId": 9}})])
    ok = cn.post_sms_ir_verify(
        api_key="KEY1",
        template_id=100,
        mobile="09120000000",
        parameters=[{"name": "EVENT", "value": "پرداخت"}],
        session=session,
    )
    assert ok is True
    call = session.calls[0]
    assert call["url"] == "https://api.sms.ir/v1/send/verify"
    assert call["headers"]["x-api-key"] == "KEY1"
    assert call["json"]["mobile"] == "09120000000"
    assert call["json"]["templateId"] == 100
    assert call["json"]["parameters"] == [{"name": "EVENT", "value": "پرداخت"}]
    assert call["timeout"] is not None


def test_post_sms_ir_verify_non_ack_returns_false():
    session = _FakeSession([_FakeResp(200, {"status": 0, "message": "خطا"})])
    assert cn.post_sms_ir_verify(
        api_key="KEY1", template_id=100, mobile="0912", parameters=[], session=session
    ) is False


def test_post_sms_ir_verify_http_error_returns_false():
    session = _FakeSession([_FakeResp(500, {"status": 0})])
    assert cn.post_sms_ir_verify(
        api_key="KEY1", template_id=100, mobile="0912", parameters=[], session=session
    ) is False


def test_smtp_starttls_login_and_send():
    instances = []
    config = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "mailer",
        "password": "secret",
        "sender": "no-reply@example.com",
        "recipient": "owner@example.com",
        "tls": "starttls",
    }
    ok = cn.send_smtp_mail(
        config=config,
        subject="Alert 42",
        body="body text",
        smtp_factory=_smtp_factory(instances),
    )
    assert ok is True
    assert len(instances) == 1
    smtp = instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.port == 587
    assert smtp.starttls_called is True
    assert smtp.login_args == ("mailer", "secret")
    sender, recipients, message = smtp.sent
    assert sender == "no-reply@example.com"
    assert recipients == ["owner@example.com"]
    assert "Alert 42" in message
    assert "body text" in message


def test_smtp_ssl_mode_uses_ssl_factory():
    instances = []
    config = {
        "host": "smtp.example.com",
        "port": 465,
        "username": "mailer",
        "password": "secret",
        "sender": "no-reply@example.com",
        "recipient": "owner@example.com",
        "tls": "ssl",
    }
    cn.send_smtp_mail(config=config, subject="s", body="b", smtp_factory=_smtp_factory(instances))
    assert instances[0].starttls_called is False  # SSL handshake replaces STARTTLS
    assert instances[0].login_args == ("mailer", "secret")


def test_configs_require_all_credentials(monkeypatch):
    monkeypatch.setenv("SMS_IR_API_KEY", "k")
    # missing template id + mobile
    assert cn.sms_config() is None
    _configure_sms(monkeypatch)
    assert cn.sms_config() == {"api_key": "k", "template_id": 100, "mobile": "09120000000"}

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    # missing username/password/from/to
    assert cn.smtp_config() is None
    _configure_smtp(monkeypatch)
    cfg = cn.smtp_config()
    assert cfg["port"] == 587 and cfg["tls"] == "starttls"


def test_env_toggle_disables_channel(monkeypatch):
    _configure_sms(monkeypatch)
    monkeypatch.setenv("COMMERCE_NOTIFY_SMS", "0")
    assert cn.sms_config() is None

    _configure_smtp(monkeypatch)
    monkeypatch.setenv("COMMERCE_NOTIFY_SMTP", "false")
    assert cn.smtp_config() is None


# ══════════════════════════════════════════════════════════════════════
# Event wiring (integration, mocked channels)
# ══════════════════════════════════════════════════════════════════════


def _record_channels(monkeypatch):
    """Patch the three channel functions on the notifications module.

    ``commerce.py`` calls the module (``commerce_notifications.notify_admin``),
    and ``notify_admin`` resolves these names at call time, so patching them
    here is seen by the real transition code.
    """
    records = {"telegram": [], "sms": [], "email": []}
    monkeypatch.setattr(cn, "send_telegram_message", lambda text: records["telegram"].append(text) or cn.SENT)
    monkeypatch.setattr(cn, "send_sms_alert", lambda parameters: records["sms"].append(parameters) or cn.SENT)
    monkeypatch.setattr(cn, "send_email_alert", lambda subject, body: records["email"].append((subject, body)) or cn.SENT)
    return records


def _create_product(client, auth_headers, *, name="محصول تستی", price=50000):
    payload = {"name": name, "weight_g": 40, "print_time_hours": 1, "final_price": price}
    r = client.post("/api/v1/products", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _request_payload(product_id, qty=1):
    return {
        "customer_name": "رضا",
        "mobile": "09123456789",
        "messenger": "telegram",
        "items": [{"product_id": product_id, "qty": qty}],
    }


def test_request_submission_emits_request_created(client, auth_headers, monkeypatch):
    records = _record_channels(monkeypatch)
    product = _create_product(client, auth_headers)

    r = client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    assert r.status_code == 200, r.text
    receipt_id = r.json()["receipt_id"]

    assert len(records["telegram"]) == 1
    assert receipt_id in records["telegram"][0]
    # SMS/email got exactly one event each too.
    assert len(records["sms"]) == 1
    assert len(records["email"]) == 1


def test_invoice_approval_emits_invoice_approved(client, auth_headers, monkeypatch):
    records = _record_channels(monkeypatch)
    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "items": [{"description": "قطعه", "qty": 1, "unit_toman": 100000}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]

    # Drafting an invoice is NOT an event.
    assert records["telegram"] == []

    approved = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    token = approved.json()["share_url"].rsplit("/", 1)[-1]

    assert len(records["telegram"]) == 1
    # The admin broadcast must never carry the private bearer token / link.
    assert token not in records["telegram"][0]
    assert "/pay/" not in records["telegram"][0]


def test_notification_failure_does_not_rollback_request(client, auth_headers, monkeypatch):
    """A raising channel must not lose the committed request."""
    def _boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(cn, "send_telegram_message", _boom)

    product = _create_product(client, auth_headers)
    r = client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    assert r.status_code == 200, r.text

    listing = client.get(f"{BASE}/staff/requests", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_hard_notification_scheduling_failure_never_breaks_transition(client, auth_headers, monkeypatch):
    """Even a scheduling layer that raises must not break the DB transition."""
    def _boom(*args, **kwargs):
        raise RuntimeError("notify blew up")

    monkeypatch.setattr(cn, "schedule_admin_delivery", _boom)

    product = _create_product(client, auth_headers)
    r = client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    assert r.status_code == 200, r.text

    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "items": [{"description": "قطعه", "qty": 1, "unit_toman": 100000}],
        },
        headers=auth_headers,
    )
    invoice_id = created.json()["id"]
    approved = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"


# ══════════════════════════════════════════════════════════════════════
# Duplicate callback => exactly one paid alert
# ══════════════════════════════════════════════════════════════════════


class _FakeDigiPay:
    def __init__(self):
        self.tickets = {}
        self.verify_status = 0

    def create_ticket(self, *, amount_rial, mobile, provider_id, callback_url):
        self.tickets[provider_id] = amount_rial
        return {
            "redirect_url": "https://uatweb.mydigipay.info/web-pay/tgs/v2:fake",
            "ticket": "v2:fake",
            "provider_id": provider_id,
        }

    def verify(self, *, tracking_code, provider_id, type):
        return {
            "result": {"status": self.verify_status},
            "trackingCode": tracking_code,
            "providerId": provider_id,
            "amount": self.tickets.get(provider_id),
            "paymentGateway": 3,
        }


@pytest.fixture()
def fake_provider(client):
    from app.main import app
    from app.services import digipay

    fake = _FakeDigiPay()
    app.dependency_overrides[digipay.client_dependency] = lambda: fake
    yield fake
    app.dependency_overrides.pop(digipay.client_dependency, None)


def _latest_attempt(invoice_id):
    from app.models import CommercePaymentAttempt
    from tests.conftest import TestSessionLocal

    db = TestSessionLocal()
    try:
        return (
            db.query(CommercePaymentAttempt)
            .filter(CommercePaymentAttempt.invoice_id == invoice_id)
            .order_by(CommercePaymentAttempt.id.desc())
            .first()
        )
    finally:
        db.close()


def test_duplicate_callback_emits_paid_alert_once(client, auth_headers, fake_provider, monkeypatch):
    records = _record_channels(monkeypatch)

    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "shipping_toman": 12000,
            "items": [{"description": "قطعه", "qty": 2, "unit_toman": 150000}],
        },
        headers=auth_headers,
    )
    invoice_id = created.json()["id"]
    approved = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    token = approved.json()["share_url"].rsplit("/", 1)[-1]

    assert client.post(f"{BASE}/invoices/{token}/pay").status_code == 200
    attempt = _latest_attempt(invoice_id)

    payload = {
        "providerId": attempt.provider_id,
        "amount": str(attempt.amount_rial),
        "trackingCode": "TRK-1",
        "type": "11",
        "result": "SUCCESS",
    }

    first = client.post(f"{BASE}/digipay/callback", data=payload, follow_redirects=False)
    second = client.post(f"{BASE}/digipay/callback", data=payload, follow_redirects=False)
    assert "payment=success" in first.headers["location"]
    assert "payment=success" in second.headers["location"]

    # Exactly ONE paid alert despite two (replayed) callbacks.
    paid_alerts = [t for t in records["telegram"] if "پرداخت" in t]
    assert len(paid_alerts) == 1
    # And exactly one invoice-approved alert earlier in the flow.
    assert len([t for t in records["telegram"] if "تأیید" in t]) == 1


def test_paid_alert_carries_amount_and_order_not_token(client, auth_headers, fake_provider, monkeypatch):
    records = _record_channels(monkeypatch)

    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "items": [{"description": "قطعه", "qty": 2, "unit_toman": 150000}],
        },
        headers=auth_headers,
    )
    invoice_id = created.json()["id"]
    token = client.post(
        f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers
    ).json()["share_url"].rsplit("/", 1)[-1]
    client.post(f"{BASE}/invoices/{token}/pay")
    attempt = _latest_attempt(invoice_id)

    client.post(
        f"{BASE}/digipay/callback",
        data={
            "providerId": attempt.provider_id,
            "amount": str(attempt.amount_rial),
            "trackingCode": "TRK-1",
            "type": "11",
            "result": "SUCCESS",
        },
        follow_redirects=False,
    )

    paid = [t for t in records["telegram"] if "پرداخت" in t][0]
    assert token not in paid
    assert "300,000" in paid or "300000" in paid


# ══════════════════════════════════════════════════════════════════════
# Staff retry visibility (no durable outbox)
# ══════════════════════════════════════════════════════════════════════


def _draft_invoice(client, auth_headers):
    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "items": [{"description": "قطعه", "qty": 1, "unit_toman": 100000}],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_staff_resend_reports_per_channel_status(client, auth_headers, monkeypatch):
    records = _record_channels(monkeypatch)
    invoice_id = _draft_invoice(client, auth_headers)
    client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    records["telegram"].clear()  # drop the approval-time alert

    r = client.post(f"{BASE}/staff/invoices/{invoice_id}/notify", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"] == "invoice_approved"
    assert body["channels"] == {"telegram": "sent", "sms": "sent", "email": "sent"}
    assert len(records["telegram"]) == 1
    # A resend never re-issues or exposes the private link.
    assert "/pay/" not in records["telegram"][0]


def test_staff_resend_rejects_non_notifiable_state(client, auth_headers):
    invoice_id = _draft_invoice(client, auth_headers)
    r = client.post(f"{BASE}/staff/invoices/{invoice_id}/notify", headers=auth_headers)
    assert r.status_code == 400


def test_staff_resend_requires_staff(client):
    r = client.post(f"{BASE}/staff/invoices/1/notify")
    assert r.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════
# Background dispatch — the public/staff response is not gated by transport
# ══════════════════════════════════════════════════════════════════════


class _RecordingTasks:
    """Minimal stand-in for FastAPI ``BackgroundTasks`` (record, run on demand)."""

    def __init__(self):
        self.jobs = []

    def add_task(self, func, *args, **kwargs):
        self.jobs.append((func, args, kwargs))

    def run(self):
        jobs, self.jobs = self.jobs, []
        for func, args, kwargs in jobs:
            func(*args, **kwargs)


class _StandaloneSubject:
    receipt_id = "REQ-BGDISP"
    customer_name = "رضا"
    mobile = "09123456789"
    messenger = "telegram"
    messenger_handle = ""
    address = ""
    state = "pending_review"
    items = []


def test_delivery_is_deferred_and_payload_is_a_snapshot(monkeypatch):
    """A scheduled event is *not* delivered inline and its payload is plain data.

    Building the payload eagerly (while the session is open) and delivering it
    later from the ``BackgroundTasks`` job is what keeps the customer response
    from being gated by a slow transport — and means the delivery task never
    touches an ORM object after the request (and its session) has closed.
    """
    from app.services import commerce as commerce_service

    records = _record_channels(monkeypatch)
    tasks = _RecordingTasks()

    commerce_service._emit_admin_notification(
        cn.EVENT_REQUEST_CREATED, _StandaloneSubject(), background_tasks=tasks
    )

    # Nothing was sent while the request was still being handled.
    assert records == {"telegram": [], "sms": [], "email": []}
    assert len(tasks.jobs) == 1
    func, args, kwargs = tasks.jobs[0]
    assert func is cn.deliver_payload
    event, payload = args
    assert kwargs == {} and event == cn.EVENT_REQUEST_CREATED
    # The payload is a plain-data snapshot (string, no ORM attribute access).
    assert isinstance(payload["telegram"], str)
    assert "REQ-BGDISP" in payload["telegram"]

    # Delivery runs later, after the subject/session is gone.
    tasks.run()
    assert len(records["telegram"]) == 1
    assert len(records["sms"]) == 1
    assert len(records["email"]) == 1


def test_background_delivery_never_raises_to_the_caller(monkeypatch):
    """A transport blow-up inside the deferred job must be swallowed, not raised."""
    from app.services import commerce as commerce_service

    def _boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(cn, "send_telegram_message", _boom)
    monkeypatch.setattr(cn, "send_sms_alert", lambda parameters: cn.SENT)
    monkeypatch.setattr(cn, "send_email_alert", lambda subject, body: cn.SENT)

    tasks = _RecordingTasks()
    commerce_service._emit_admin_notification(
        cn.EVENT_REQUEST_CREATED, _StandaloneSubject(), background_tasks=tasks
    )
    # Running the job must not raise even though Telegram blew up.
    tasks.run()


def test_public_request_hands_notification_to_background_tasks(client, auth_headers, monkeypatch):
    """The public request handler must schedule (not run) the admin alert."""
    from app.services import commerce as commerce_service

    seen = {}
    real = commerce_service._emit_admin_notification

    def _spy(event, subject, background_tasks=None):
        seen["event"] = event
        seen["has_bg"] = background_tasks is not None
        return real(event, subject, background_tasks=background_tasks)

    monkeypatch.setattr(commerce_service, "_emit_admin_notification", _spy)
    records = _record_channels(monkeypatch)
    product = _create_product(client, auth_headers)

    r = client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    assert r.status_code == 200, r.text
    assert seen == {"event": cn.EVENT_REQUEST_CREATED, "has_bg": True}
    # TestClient drains background tasks, so the alert still lands exactly once.
    assert len(records["telegram"]) == 1


def test_approve_hands_notification_to_background_tasks(client, auth_headers, monkeypatch):
    """Staff approval must likewise schedule the alert rather than block on it."""
    from app.services import commerce as commerce_service

    seen = {}
    real = commerce_service._emit_admin_notification

    def _spy(event, subject, background_tasks=None):
        seen["event"] = event
        seen["has_bg"] = background_tasks is not None
        return real(event, subject, background_tasks=background_tasks)

    monkeypatch.setattr(commerce_service, "_emit_admin_notification", _spy)
    records = _record_channels(monkeypatch)
    invoice_id = _draft_invoice(client, auth_headers)

    r = client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert seen == {"event": cn.EVENT_INVOICE_APPROVED, "has_bg": True}
    assert len(records["telegram"]) == 1


def test_payment_settlement_hands_notification_to_background_tasks(
    client, auth_headers, fake_provider, monkeypatch
):
    """The DigiPay callback must settle, then schedule the paid alert."""
    from app.services import commerce as commerce_service

    seen = {}
    real = commerce_service._emit_admin_notification

    def _spy(event, subject, background_tasks=None):
        seen.setdefault(event, 0)
        seen[event] += 1
        seen.setdefault("has_bg", background_tasks is not None)
        return real(event, subject, background_tasks=background_tasks)

    monkeypatch.setattr(commerce_service, "_emit_admin_notification", _spy)
    _record_channels(monkeypatch)

    created = client.post(
        f"{BASE}/staff/invoices",
        json={
            "customer_name": "رضا", "mobile": "09123456789", "messenger": "telegram",
            "items": [{"description": "قطعه", "qty": 1, "unit_toman": 100000}],
        },
        headers=auth_headers,
    )
    invoice_id = created.json()["id"]
    token = client.post(
        f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers
    ).json()["share_url"].rsplit("/", 1)[-1]
    client.post(f"{BASE}/invoices/{token}/pay")
    attempt = _latest_attempt(invoice_id)

    r = client.post(
        f"{BASE}/digipay/callback",
        data={
            "providerId": attempt.provider_id,
            "amount": str(attempt.amount_rial),
            "trackingCode": "TRK-1",
            "type": "11",
            "result": "SUCCESS",
        },
        follow_redirects=False,
    )
    assert "payment=success" in r.headers["location"]
    assert seen.get(cn.EVENT_PAYMENT_VERIFIED) == 1
    assert seen["has_bg"] is True


def test_deferred_delivery_contacts_no_transport_without_credentials(client, auth_headers, monkeypatch):
    """With no SMS/SMTP credentials the deferred job must make no network call."""
    calls = {"sms": 0, "smtp": 0}
    monkeypatch.setattr(cn, "send_telegram_message", lambda text: cn.SKIPPED)
    monkeypatch.setattr(cn, "post_sms_ir_verify", lambda **kw: calls.__setitem__("sms", calls["sms"] + 1) or True)
    monkeypatch.setattr(cn, "send_smtp_mail", lambda **kw: calls.__setitem__("smtp", calls["smtp"] + 1) or True)

    product = _create_product(client, auth_headers)
    r = client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    assert r.status_code == 200, r.text
    assert calls == {"sms": 0, "smtp": 0}


# ══════════════════════════════════════════════════════════════════════
# Telegram: distinguish "configured but failed" from "not configured"
# ══════════════════════════════════════════════════════════════════════


def test_telegram_not_configured_is_skipped(monkeypatch):
    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": False)
    monkeypatch.setattr(cn, "get_telegram_config", lambda: ("", [], None))
    assert cn.send_telegram_message("x") == cn.SKIPPED


def test_telegram_configured_but_failed_is_failed_not_skipped(monkeypatch):
    """A configured bot whose send fails must be FAILED, never masked as a skip."""
    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": False)
    monkeypatch.setattr(cn, "get_telegram_config", lambda: ("token", ["12345"], None))
    assert cn.send_telegram_message("x") == cn.FAILED


def test_telegram_configured_success_is_sent(monkeypatch):
    monkeypatch.setattr(cn, "send_telegram_notification", lambda text, parse_mode="HTML": True)
    # get_telegram_config must not even be needed once the send succeeds.
    monkeypatch.setattr(cn, "get_telegram_config", lambda: ("", [], None))
    assert cn.send_telegram_message("x") == cn.SENT


# ══════════════════════════════════════════════════════════════════════
# Staff retry of request_created + rate limiting
# ══════════════════════════════════════════════════════════════════════


def _first_request_id(client, auth_headers):
    rows = client.get(f"{BASE}/staff/requests", headers=auth_headers).json()
    return rows[0]["id"]


def test_staff_can_resend_request_created(client, auth_headers, monkeypatch):
    records = _record_channels(monkeypatch)
    product = _create_product(client, auth_headers)
    client.post(f"{BASE}/requests", json=_request_payload(product["id"]))
    records["telegram"].clear()
    request_id = _first_request_id(client, auth_headers)

    r = client.post(f"{BASE}/staff/requests/{request_id}/notify", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"] == "request_created"
    assert body["channels"] == {"telegram": "sent", "sms": "sent", "email": "sent"}
    assert len(records["telegram"]) == 1
    assert "REQ-" in records["telegram"][0]


def test_staff_resend_request_notify_404_for_unknown(client, auth_headers):
    r = client.post(f"{BASE}/staff/requests/999999/notify", headers=auth_headers)
    assert r.status_code == 404


def test_staff_resend_request_notify_requires_staff(client):
    r = client.post(f"{BASE}/staff/requests/1/notify")
    assert r.status_code in (401, 403)


def test_staff_notify_is_rate_limited(client, auth_headers, monkeypatch):
    """The retry endpoints fan out to live transports, so they are rate-limited."""
    _record_channels(monkeypatch)
    invoice_id = _draft_invoice(client, auth_headers)
    client.post(f"{BASE}/staff/invoices/{invoice_id}/approve", headers=auth_headers)

    statuses = [
        client.post(f"{BASE}/staff/invoices/{invoice_id}/notify", headers=auth_headers).status_code
        for _ in range(13)
    ]
    assert 429 in statuses
