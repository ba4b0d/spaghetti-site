"""High-fidelity Persian PDF invoice generator for Spaghetti Print.

Renders A4 PDF invoices using ReportLab, arabic_reshaper, python-bidi, and qrcode.
Features:
- Spaghetti Print brand header with orange accent
- Official Vazirmatn typography (Regular & Bold)
- Iranian Jalali date conversion (pure algorithmic, zero external dep)
- Seller details: "تهران، شهرک امید"
- Buyer details with full delivery address
- Itemized pricing table (Row, Description, Qty, Unit Price, Total)
- Shipping fee and payable grand total
- Dynamic QR code linking to private payment/verification page
- Paid / Pending state badge
"""
import io
import os
import qrcode
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import arabic_reshaper
from bidi.algorithm import get_display

# ── Typography & Fonts ───────────────────────────────────────────────────────

_FONTS_REGISTERED = False
FONT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
)
FONT_REGULAR_PATH = os.path.join(FONT_DIR, "Vazirmatn-Regular.ttf")
FONT_BOLD_PATH = os.path.join(FONT_DIR, "Vazirmatn-Bold.ttf")

FONT_NAME = "Vazirmatn"
FONT_BOLD_NAME = "Vazirmatn-Bold"


def _ensure_fonts_registered() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    if os.path.exists(FONT_REGULAR_PATH):
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_REGULAR_PATH))
    else:
        # Fallback to Helvetica if TTF is somehow absent (in test mocks)
        pdfmetrics.registerFont(TTFont(FONT_NAME, "Helvetica"))

    if os.path.exists(FONT_BOLD_PATH):
        pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, FONT_BOLD_PATH))
    else:
        pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, "Helvetica-Bold"))

    _FONTS_REGISTERED = True


# ── Farsi & BiDi Text Shaping ────────────────────────────────────────────────

_RESHAPER = arabic_reshaper.ArabicReshaper(
    {
        "delete_harakat": True,
        "support_ligatures": True,
        "support_zwj": True,
    }
)

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_fa_digits(s: str | int | float) -> str:
    """Convert ASCII digits 0-9 to Persian digits ۰-۹."""
    return str(s).translate(FA_DIGITS)


def format_price_fa(amount: int | float | None) -> str:
    """Format monetary integer Toman into Persian comma-separated digits."""
    if amount is None:
        return "۰"
    val = int(amount)
    return to_fa_digits(f"{val:,}")


def farsi(text: str | None) -> str:
    """Reshape and reorder a single line of Persian text for PDF rendering."""
    if not text:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    reshaped = _RESHAPER.reshape(s)
    return get_display(reshaped)


def wrap_farsi_text(
    text: str | None,
    font_name: str,
    font_size: float,
    max_width: float,
) -> str:
    """Word-wrap Persian text based on exact stringWidth in points before BiDi.

    Prevents ReportLab's multi-line inverted word order bug by shaping and
    reordering each wrapped line individually, joined by HTML line-break <br/>.
    """
    if not text:
        return ""
    s = str(text).strip()
    if not s:
        return ""

    words = s.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        # Measure unshaped/unreversed text width accurately with the target TTF
        w = stringWidth(candidate, font_name, font_size)
        if w <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
                current = [word]
            else:
                lines.append(word)
                current = []
    if current:
        lines.append(" ".join(current))

    # Reshape and BiDi each line independently
    reshaped_lines = [get_display(_RESHAPER.reshape(line)) for line in lines]
    return "<br/>".join(reshaped_lines)


# ── Jalali Date Conversion ───────────────────────────────────────────────────


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Pure mathematical Gregorian to Jalali converter."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_d_m[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return (jy, jm, jd)


def format_jalali_date(dt: datetime | None) -> str:
    """Format datetime into Jalali YYYY/MM/DD with Persian digits."""
    if not dt:
        dt = datetime.now(timezone.utc)
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return to_fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")


# ── QR Code Flowable ─────────────────────────────────────────────────────────


def _generate_qr_flowable(url: str, size: float = 65) -> Image:
    """Generate in-memory QR code ReportLab Flowable."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    flowable = Image(buf, width=size, height=size)
    flowable.hAlign = "CENTER"
    return flowable


# ── Invoice PDF Builder ──────────────────────────────────────────────────────


def generate_invoice_pdf(
    invoice,
    raw_token: str | None = None,
    base_url: str = "https://spaghettiprints.ir",
) -> bytes:
    """Generate high-fidelity Persian PDF invoice bytes.

    Args:
        invoice: CommerceInvoice model instance or compatible object.
        raw_token: One-time private token if available for direct QR pay link.
        base_url: Storefront base URL.

    Returns:
        bytes: Binary PDF stream.
    """
    _ensure_fonts_registered()

    buf = io.BytesIO()
    # A4: 595.27 x 841.89 pt. 28 pt margins leaves 539.27 pt printable width.
    printable_width = 539.0
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=28,
        rightMargin=28,
        topMargin=26,
        bottomMargin=26,
    )

    # Palette
    c_orange = colors.HexColor("#ea580c")
    c_navy = colors.HexColor("#0f172a")
    c_dark = colors.HexColor("#1e293b")
    c_muted = colors.HexColor("#64748b")
    c_border = colors.HexColor("#e2e8f0")
    c_card = colors.HexColor("#f8fafc")
    c_paid_bg = colors.HexColor("#dcfce7")
    c_paid_text = colors.HexColor("#15803d")
    c_pending_bg = colors.HexColor("#fef3c7")
    c_pending_text = colors.HexColor("#b45309")

    # Typography styles
    style_brand_title = ParagraphStyle(
        "BrandTitle",
        fontName=FONT_BOLD_NAME,
        fontSize=18,
        leading=22,
        alignment=2,  # Right
        textColor=c_orange,
    )
    style_brand_sub = ParagraphStyle(
        "BrandSub",
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=12,
        alignment=2,
        textColor=c_muted,
    )
    style_badge_paid = ParagraphStyle(
        "BadgePaid",
        fontName=FONT_BOLD_NAME,
        fontSize=9,
        leading=13,
        alignment=2,
        textColor=c_paid_text,
    )
    style_badge_pending = ParagraphStyle(
        "BadgePending",
        fontName=FONT_BOLD_NAME,
        fontSize=9,
        leading=13,
        alignment=2,
        textColor=c_pending_text,
    )
    style_meta_label = ParagraphStyle(
        "MetaLabel",
        fontName=FONT_NAME,
        fontSize=8,
        leading=12,
        alignment=0,  # Left
        textColor=c_muted,
    )
    style_meta_val = ParagraphStyle(
        "MetaVal",
        fontName=FONT_BOLD_NAME,
        fontSize=9,
        leading=13,
        alignment=0,  # Left
        textColor=c_navy,
    )

    style_panel_header = ParagraphStyle(
        "PanelHeader",
        fontName=FONT_BOLD_NAME,
        fontSize=9.5,
        leading=13,
        alignment=2,
        textColor=c_navy,
    )
    style_panel_body = ParagraphStyle(
        "PanelBody",
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=13,
        alignment=2,
        textColor=c_dark,
    )

    style_th = ParagraphStyle(
        "TableTh",
        fontName=FONT_BOLD_NAME,
        fontSize=8.5,
        leading=12,
        alignment=1,  # Center
        textColor=colors.white,
    )
    style_td_center = ParagraphStyle(
        "TableTdCenter",
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=12,
        alignment=1,
        textColor=c_dark,
    )
    style_td_right = ParagraphStyle(
        "TableTdRight",
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=12,
        alignment=2,
        textColor=c_dark,
    )

    style_total_label = ParagraphStyle(
        "TotalLabel",
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=12,
        alignment=2,
        textColor=c_muted,
    )
    style_total_val = ParagraphStyle(
        "TotalVal",
        fontName=FONT_BOLD_NAME,
        fontSize=9,
        leading=13,
        alignment=0,
        textColor=c_dark,
    )
    style_grand_label = ParagraphStyle(
        "GrandLabel",
        fontName=FONT_BOLD_NAME,
        fontSize=10,
        leading=14,
        alignment=2,
        textColor=c_orange,
    )
    style_grand_val = ParagraphStyle(
        "GrandVal",
        fontName=FONT_BOLD_NAME,
        fontSize=11,
        leading=15,
        alignment=0,
        textColor=c_orange,
    )

    elements = []

    # 1. Top Header Bar (Brand on right, Meta & QR on left)
    invoice_id_str = f"INV-{invoice.id:04d}" if hasattr(invoice, "id") and invoice.id else "INV-0000"
    created_date = getattr(invoice, "created_at", None)
    jalali_str = format_jalali_date(created_date)

    is_paid = getattr(invoice, "state", "") == "paid"
    if is_paid:
        status_text = f"وضعیت: پرداخت‌شده (تأیید نهایی)"
        status_style = style_badge_paid
    else:
        status_text = f"وضعیت: در انتظار پرداخت"
        status_style = style_badge_pending

    # QR URL
    if raw_token:
        qr_url = f"{base_url}/pay/{raw_token}"
    else:
        qr_url = f"{base_url}/my-orders"
    qr_flowable = _generate_qr_flowable(qr_url, size=62)

    brand_html = (
        f"<b>{farsi('اسپاگتی پرینت | چاپ سه‌بعدی')}</b><br/>"
        f"{farsi('طراحی، نمونه‌سازی و تولید قطعات سفارشی FDM')}<br/>"
        f"<font size='7.5' color='#64748b'>{farsi('spaghettiprints.ir')}</font>"
    )
    brand_p = Paragraph(brand_html, style_brand_title)

    meta_html = (
        f"{farsi('شماره فاکتور:')} <b>{to_fa_digits(invoice_id_str)}</b><br/>"
        f"{farsi('تاریخ صدور:')} <b>{jalali_str}</b><br/>"
        f"{farsi(status_text)}"
    )
    meta_p = Paragraph(meta_html, style_meta_val)

    header_table = Table(
        [
            [qr_flowable, meta_p, brand_p]
        ],
        colWidths=[70, 180, 289],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("ALIGN", (1, 0), (1, 0), "LEFT"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # Divider line with brand orange dot
    elements.append(
        HRFlowable(
            width="100%",
            thickness=1.5,
            color=c_orange,
            spaceBefore=2,
            spaceAfter=10,
        )
    )

    # 2. Seller and Buyer Information Boxes
    # Seller info
    seller_body = (
        f"{farsi('نام: اسپاگتی پرینت (Spaghetti Print)')}<br/>"
        f"{farsi('نشانی: تهران، شهرک امید')}<br/>"
        f"{farsi('وب‌سایت: spaghettiprints.ir')}<br/>"
        f"{farsi('پشتیبانی: پیام‌رسان تلگرام و بله spaghetti_prints@')}"
    )

    # Buyer info with full address
    cust_name = getattr(invoice, "customer_name", "") or "-"
    mobile = getattr(invoice, "mobile", "") or "-"
    messenger = getattr(invoice, "messenger", "") or "telegram"
    handle = getattr(invoice, "messenger_handle", "") or ""
    messenger_display = f"{messenger} ({handle})" if handle else messenger
    address = getattr(invoice, "address", "") or "تحویل حضوری / نامشخص"

    # Wrap the full address cleanly to prevent line-overflow
    address_wrapped = wrap_farsi_text(
        f"نشانی تحویل: {address}",
        FONT_NAME,
        8.5,
        250,  # Half page width in points
    )

    buyer_body = (
        f"{farsi('نام خریدار:')} <b>{farsi(cust_name)}</b><br/>"
        f"{farsi('شماره تماس:')} {to_fa_digits(mobile)}<br/>"
        f"{farsi('پیام‌رسان:')} {messenger_display}<br/>"
        f"{address_wrapped}"
    )

    party_table = Table(
        [
            [
                Paragraph(f"<b>{farsi('مشخصات فروشنده')}</b>", style_panel_header),
                Paragraph(f"<b>{farsi('مشخصات و نشانی خریدار')}</b>", style_panel_header),
            ],
            [
                Paragraph(seller_body, style_panel_body),
                Paragraph(buyer_body, style_panel_body),
            ],
        ],
        colWidths=[264.5, 274.5],
    )
    party_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), c_card),
                ("BOX", (0, 0), (-1, -1), 0.75, c_border),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(party_table)
    elements.append(Spacer(1, 12))

    # 3. Itemized Products/Services Table
    # Table headers: Row, Description, Qty, Unit Price (Toman), Total (Toman)
    table_data = [
        [
            Paragraph(f"<b>{farsi('مبلغ کل (تومان)')}</b>", style_th),
            Paragraph(f"<b>{farsi('قیمت واحد (تومان)')}</b>", style_th),
            Paragraph(f"<b>{farsi('تعداد')}</b>", style_th),
            Paragraph(f"<b>{farsi('شرح کالا یا خدمات')}</b>", style_th),
            Paragraph(f"<b>{farsi('ردیف')}</b>", style_th),
        ]
    ]

    items = getattr(invoice, "items", []) or []
    items_subtotal = 0
    row_idx = 1

    for it in items:
        desc = getattr(it, "description", "") or "کالای سفارشی"
        qty = int(getattr(it, "qty", 1) or 1)
        unit = int(getattr(it, "unit_toman", 0) or 0)
        line_total = int(getattr(it, "line_total_toman", 0) or (qty * unit))
        items_subtotal += line_total

        desc_wrapped = wrap_farsi_text(desc, FONT_NAME, 8.5, 220)

        table_data.append(
            [
                Paragraph(format_price_fa(line_total), style_td_center),
                Paragraph(format_price_fa(unit), style_td_center),
                Paragraph(to_fa_digits(qty), style_td_center),
                Paragraph(desc_wrapped, style_td_right),
                Paragraph(to_fa_digits(row_idx), style_td_center),
            ]
        )
        row_idx += 1

    if not items:
        table_data.append(
            [
                Paragraph("-", style_td_center),
                Paragraph("-", style_td_center),
                Paragraph("-", style_td_center),
                Paragraph(farsi("آیتمی در این فاکتور ثبت نشده است"), style_td_right),
                Paragraph(to_fa_digits(1), style_td_center),
            ]
        )

    # Column widths summing to 539 pt:
    # Total(95) + Unit(90) + Qty(40) + Desc(284) + Row(30) = 539
    items_table = Table(table_data, colWidths=[95, 90, 40, 284, 30])
    items_style = [
        ("BACKGROUND", (0, 0), (-1, 0), c_navy),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    # Alternating row background
    for r in range(1, len(table_data)):
        if r % 2 == 0:
            items_style.append(("BACKGROUND", (0, r), (-1, r), c_card))

    items_table.setStyle(TableStyle(items_style))
    elements.append(items_table)
    elements.append(Spacer(1, 10))

    # 4. Summary & Specifications (Two Column Layout)
    shipping_toman = int(getattr(invoice, "shipping_toman", 0) or 0)
    total_toman = int(getattr(invoice, "total_toman", 0) or (items_subtotal + shipping_toman))
    spec = getattr(invoice, "specification", "") or ""

    spec_wrapped = wrap_farsi_text(
        f"مشخصات و توضیحات نهایی سفارش: {spec}" if spec else "توضیحات: قطعات بر اساس مشخصات توافق‌شده چاپ و آماده‌سازی می‌شوند.",
        FONT_NAME,
        8.0,
        280,
    )

    spec_p = Paragraph(spec_wrapped, style_panel_body)

    shipping_label = farsi("رایگان") if shipping_toman == 0 else f"{format_price_fa(shipping_toman)} {farsi('تومان')}"

    totals_table = Table(
        [
            [
                Paragraph(f"{format_price_fa(items_subtotal)} {farsi('تومان')}", style_total_val),
                Paragraph(farsi("جمع اقلام:"), style_total_label),
            ],
            [
                Paragraph(shipping_label, style_total_val),
                Paragraph(farsi("هزینه ارسال:"), style_total_label),
            ],
            [
                Paragraph(f"{format_price_fa(total_toman)} {farsi('تومان')}", style_grand_val),
                Paragraph(farsi("مبلغ قابل پرداخت:"), style_grand_label),
            ],
        ],
        colWidths=[120, 110],
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 1), 0.5, c_border),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#fff7ed")),
                ("BOX", (0, 2), (-1, 2), 1, c_orange),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    summary_panel = Table(
        [
            [
                totals_table,
                spec_p,
            ]
        ],
        colWidths=[239, 300],
    )
    summary_panel.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )
    elements.append(summary_panel)
    elements.append(Spacer(1, 14))

    # 5. Footer with Trust & Instructions
    elements.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=c_border,
            spaceBefore=4,
            spaceAfter=6,
        )
    )
    footer_text = (
        f"<font size='8' color='#64748b'>"
        f"{farsi('با اسکن کیوآرکد بالای فاکتور، می‌توانید مستقیماً به صفحه پرداخت امن و پیگیری سفارش وارد شوید.')}<br/>"
        f"{farsi('از انتخاب و اعتماد شما به اسپاگتی پرینت سپاسگزاریم | پشتیبانی تلگرام و بله: spaghetti_prints@')}"
        f"</font>"
    )
    elements.append(Paragraph(footer_text, ParagraphStyle("Footer", alignment=1, leading=12)))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()
