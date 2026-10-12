"""Unit tests for the Persian invoice PDF generator."""
from datetime import datetime, timezone
from app.services.invoice_pdf import (
    generate_invoice_pdf,
    format_jalali_date,
    format_price_fa,
    farsi,
    wrap_farsi_text,
    to_fa_digits,
)


class DummyItem:
    def __init__(self, description, qty, unit_toman, line_total_toman):
        self.description = description
        self.qty = qty
        self.unit_toman = unit_toman
        self.line_total_toman = line_total_toman


class DummyInvoice:
    def __init__(
        self,
        id=12,
        customer_name="علی محمدی",
        mobile="09123456789",
        messenger="telegram",
        messenger_handle="@ali_m",
        address="تهران، خیابان آزادی، کوچه شهید صادقی، پلاک ۱۵، واحد ۳",
        specification="پرینت با متریال PLA مشکی و دقت ۰.۱۶ میلی‌متر",
        shipping_toman=35000,
        total_toman=185000,
        state="approved",
        created_at=None,
        items=None,
    ):
        self.id = id
        self.customer_name = customer_name
        self.mobile = mobile
        self.messenger = messenger
        self.messenger_handle = messenger_handle
        self.address = address
        self.specification = specification
        self.shipping_toman = shipping_toman
        self.total_toman = total_toman
        self.state = state
        self.created_at = created_at or datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
        self.items = items or [
            DummyItem("گلدان هندسی رومیزی", 1, 150000, 150000),
        ]


def test_jalali_date_conversion():
    dt = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    res = format_jalali_date(dt)
    # 2026-10-12 corresponds to 1405-07-20 in Persian calendar
    assert "۱۴۰۵/۰۷/۲۰" in res


def test_price_formatting():
    assert format_price_fa(150000) == "۱۵۰,۰۰۰"
    assert format_price_fa(0) == "۰"
    assert format_price_fa(None) == "۰"


def test_farsi_shaping():
    reshaped = farsi("اسپاگتی پرینت")
    assert len(reshaped) > 0


def test_generate_invoice_pdf_approved():
    invoice = DummyInvoice()
    pdf_bytes = generate_invoice_pdf(invoice, raw_token="test_raw_token_xyz")

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 5000  # Non-trivial PDF output


def test_generate_invoice_pdf_paid():
    invoice = DummyInvoice(state="paid")
    pdf_bytes = generate_invoice_pdf(invoice)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 5000


def test_generate_invoice_pdf_empty_items_and_address():
    invoice = DummyInvoice(items=[], address="", specification="")
    pdf_bytes = generate_invoice_pdf(invoice)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 3000
