import pytest
from app.services import commerce_notifications as cn
from app.services import email_templates


def test_render_commerce_email_escapes_xss():
    html_output = email_templates.render_commerce_email(
        event=cn.EVENT_REQUEST_CREATED,
        code="#101",
        customer_name="<script>alert('xss')</script>",
        mobile="0912***34",
        channel="Telegram & <b>Bale</b>",
        items=[{"name": "<img src=x onerror=alert(1)>", "qty": 2, "price": 150000}],
        total=300000,
        is_admin=True,
    )
    assert "<script>" not in html_output
    assert "&lt;script&gt;" in html_output
    assert "<img" not in html_output
    assert "&lt;img" in html_output
    assert "dir=\"rtl\"" in html_output
    assert "اسپاگتی پرینت" in html_output
    assert "300,000" in html_output


def test_render_commerce_email_events():
    for event, expected_label in [
        (cn.EVENT_REQUEST_CREATED, "درخواست جدید وبسایت"),
        (cn.EVENT_INVOICE_APPROVED, "تأیید فاکتور"),
        (cn.EVENT_PAYMENT_VERIFIED, "پرداخت موفق فاکتور"),
    ]:
        html_output = email_templates.render_commerce_email(
            event=event,
            code="#202",
            customer_name="علی رضایی",
            mobile="09121234567",
            channel="سایت",
            items=[{"name": "گلدان لوزی", "qty": 1, "price": 85000}],
            total=85000,
            is_admin=True,
        )
        assert expected_label in html_output
        assert "#202" in html_output
        assert "علی رضایی" in html_output
        assert "85,000" in html_output


def test_render_commerce_email_customer_variant():
    html_output = email_templates.render_commerce_email(
        event=cn.EVENT_INVOICE_APPROVED,
        code="#303",
        customer_name="سارا احمدی",
        mobile="09127654321",
        channel="سایت",
        items=[{"name": "استند موبایل", "qty": 1, "price": 45000}],
        total=45000,
        is_admin=False,
        action_url="https://spaghettiprints.ir/pay/test-token",
        action_label="مشاهده و پرداخت فاکتور",
    )
    assert "سارا احمدی عزیز" in html_output
    assert "https://spaghettiprints.ir/pay/test-token" in html_output
    assert "مشاهده و پرداخت فاکتور" in html_output


def test_build_payload_includes_email_html():
    class DummySubject:
        id = 99
        customer_name = "مریم"
        mobile = "09129998877"
        messenger = "بله"
        total_toman = 120000
        order_id = 12
        items = []

    payload = cn.build_payload(cn.EVENT_INVOICE_APPROVED, DummySubject())
    assert "email_html" in payload
    assert isinstance(payload["email_html"], str)
    assert "dir=\"rtl\"" in payload["email_html"]
    assert "مریم" in payload["email_html"]
    assert "#99" in payload["email_html"]


def test_send_smtp_mail_multipart():
    instances = []

    class DummySMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port
            self.starttls_called = False
            self.login_args = None
            self.sent = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, context=None):
            self.starttls_called = True

        def login(self, u, p):
            self.login_args = (u, p)

        def sendmail(self, sender, recipients, message):
            self.sent = (sender, recipients, message)

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
        subject="تست ایمیل با قالب زیبا",
        body="متن ساده پیام",
        html_body="<div dir='rtl'><h1>قالب زیبا</h1></div>",
        smtp_factory=lambda h, p, timeout=None: instances.append(DummySMTP(h, p, timeout)) or instances[-1],
    )
    assert ok is True
    assert len(instances) == 1
    sender, recipients, message = instances[0].sent
    assert sender == "no-reply@example.com"
    assert recipients == ["owner@example.com"]
    import email
    msg = email.message_from_string(message)
    assert msg.is_multipart()
    parts = {part.get_content_type(): part.get_payload(decode=True).decode("utf-8") for part in msg.walk() if not part.is_multipart()}
    assert "text/plain" in parts
    assert "متن ساده پیام" in parts["text/plain"]
    assert "text/html" in parts
    assert "<div dir='rtl'><h1>قالب زیبا</h1></div>" in parts["text/html"]
