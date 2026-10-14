"""Clean, responsive Persian/RTL HTML email templates for Spaghetti Print.

Provides bulletproof HTML email rendering compatible with major email clients
(Gmail, Apple Mail, Outlook, mobile). Supports both admin alerts and customer-facing
transactional emails.
"""

import html
from typing import Any, Sequence

BRAND_NAME_FA = "اسپاگتی پرینت"
BRAND_NAME_EN = "Spaghetti Print"
BRAND_SITE_URL = "https://spaghettiprints.ir"
BRAND_ORANGE = "#ff9a3d"
BRAND_ORANGE_DARK = "#e07b2c"
BRAND_NAVY = "#0f172a"

# Event badge configurations: (label, background_color, text_color, border_color)
EVENT_BADGES = {
    "request_created": {
        "label": "درخواست جدید وبسایت",
        "bg": "#eff6ff",
        "text": "#1d4ed8",
        "border": "#bfdbfe",
        "icon": "🛒",
    },
    "invoice_approved": {
        "label": "تأیید فاکتور",
        "bg": "#f5f3ff",
        "text": "#6d28d9",
        "border": "#ddd6fe",
        "icon": "📄",
    },
    "payment_verified": {
        "label": "پرداخت موفق فاکتور",
        "bg": "#ecfdf5",
        "text": "#047857",
        "border": "#a7f3d0",
        "icon": "✅",
    },
}


def _esc(val: Any) -> str:
    """HTML-escape values to prevent injection in mail clients."""
    return html.escape(str(val if val is not None else ""), quote=True)


def _format_money(amount: int | float | None) -> str:
    if amount is None:
        return "—"
    try:
        return f"{int(amount):,} تومان"
    except (TypeError, ValueError):
        return str(amount)


def render_commerce_email(
    *,
    event: str,
    code: str,
    customer_name: str,
    mobile: str,
    channel: str,
    items: Sequence[Any],
    total: int | float | None = None,
    order_id: int | str | None = None,
    is_admin: bool = True,
    action_url: str | None = None,
    action_label: str | None = None,
    notice_text: str | None = None,
) -> str:
    """Render a fully styled responsive RTL HTML email.

    Args:
        event: The commerce event identifier (request_created, invoice_approved, payment_verified).
        code: Public code / receipt id (e.g. #102 or REQ-...).
        customer_name: Customer's display name.
        mobile: Customer's phone number (masked for admin or full).
        channel: Contact channel (Telegram, Bale, Web, etc.).
        items: List of items (dicts or objects with display_name/description/name, qty, unit_price/price).
        total: Total amount in Toman.
        order_id: Optional internal order ID.
        is_admin: True if this is an admin alert, False for customer notification.
        action_url: Optional link for the primary CTA button.
        action_label: Text for the primary CTA button.
        notice_text: Optional customized notice or instructions.
    """
    badge_info = EVENT_BADGES.get(
        event,
        {
            "label": event,
            "bg": "#f1f5f9",
            "text": "#334155",
            "border": "#cbd5e1",
            "icon": "🔔",
        },
    )

    badge_label = badge_info["label"]
    badge_bg = badge_info["bg"]
    badge_text = badge_info["text"]
    badge_border = badge_info["border"]
    badge_icon = badge_info["icon"]

    # Header title
    if is_admin:
        header_title = f"{badge_icon} اطلاع‌رسانی: {badge_label}"
        header_subtitle = f"ثبت شده در سیستم سفارشات {BRAND_NAME_FA}"
        greeting = f"سلام مدیر گرامی، یک رخداد جدید با مشخصات زیر ثبت شده است:"
    else:
        header_title = f"{badge_icon} {badge_label}"
        header_subtitle = f"خدمات پرینت سه‌بعدی و ساخت قطعات {BRAND_NAME_FA}"
        greeting = f"{_esc(customer_name)} عزیز، وضعیت سفارش شما به شرح زیر به‌روزرسانی شد:"

    # Item rows HTML
    item_rows = []
    for item in items:
        # Resolve item name
        if isinstance(item, dict):
            name = item.get("name") or item.get("display_name") or item.get("description") or "—"
            qty = item.get("qty", 1)
            price = item.get("price") or item.get("unit_price")
        else:
            name = getattr(item, "display_name", None) or getattr(item, "description", None) or getattr(item, "name", "—")
            qty = getattr(item, "qty", 1)
            price = getattr(item, "unit_price", None) or getattr(item, "price", None)

        price_str = _format_money(price) if price is not None else ""
        item_rows.append(f"""
            <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 12px 14px; text-align: right; color: #1e293b; font-size: 14px;">
                    {_esc(name)}
                </td>
                <td style="padding: 12px 14px; text-align: center; color: #475569; font-size: 14px; white-space: nowrap;">
                    <span style="background-color: #f1f5f9; border-radius: 6px; padding: 2px 8px; font-weight: 600;">{_esc(qty)} عدد</span>
                </td>
                {"<td style='padding: 12px 14px; text-align: left; color: #1e293b; font-size: 14px; direction: ltr; font-weight: 500;'>" + _esc(price_str) + "</td>" if total is not None else ""}
            </tr>
        """)

    items_table_html = ""
    if item_rows:
        items_table_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-top: 10px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
            <thead>
                <tr style="background-color: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                    <th style="padding: 10px 14px; text-align: right; font-size: 13px; font-weight: 600; color: #64748b;">نام آیتم</th>
                    <th style="padding: 10px 14px; text-align: center; font-size: 13px; font-weight: 600; color: #64748b;">تعداد</th>
                    {"<th style='padding: 10px 14px; text-align: left; font-size: 13px; font-weight: 600; color: #64748b;'>قیمت</th>" if total is not None else ""}
                </tr>
            </thead>
            <tbody>
                {''.join(item_rows)}
            </tbody>
        </table>
        """

    total_card_html = ""
    if total is not None:
        total_card_html = f"""
        <div style="background-color: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px; padding: 14px 18px; margin-top: 16px; display: flex; align-items: center; justify-content: space-between;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                <tr>
                    <td style="text-align: right; font-size: 15px; font-weight: 600; color: #9a3412;">مبلغ کل فاکتور:</td>
                    <td style="text-align: left; font-size: 18px; font-weight: 700; color: #ea580c; direction: ltr;">{_format_money(total)}</td>
                </tr>
            </table>
        </div>
        """

    # CTA Button
    cta_html = ""
    if action_url and action_label:
        cta_html = f"""
        <div style="text-align: center; margin-top: 28px; margin-bottom: 12px;">
            <a href="{_esc(action_url)}" target="_blank" style="display: inline-block; background-color: #f97316; background-image: linear-gradient(135deg, #ff9a3d 0%, #ea580c 100%); color: #ffffff; text-decoration: none; font-size: 15px; font-weight: 600; padding: 12px 28px; border-radius: 8px; box-shadow: 0 4px 10px rgba(234, 88, 12, 0.25);">
                {_esc(action_label)}
            </a>
        </div>
        """

    # Extra notice/instruction
    notice_html = ""
    if notice_text:
        notice_html = f"""
        <div style="background-color: #f8fafc; border-right: 4px solid #ff9a3d; padding: 12px 16px; margin-top: 18px; border-radius: 4px 8px 8px 4px; font-size: 13px; color: #475569; line-height: 1.6;">
            {_esc(notice_text)}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(header_title)}</title>
    <style>
        body, table, td, p, a, li {{
            font-family: 'Vazirmatn', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, Tahoma, sans-serif;
            -webkit-text-size-adjust: 100%;
            -ms-text-size-adjust: 100%;
        }}
        body {{
            margin: 0;
            padding: 0;
            background-color: #f1f5f9;
            color: #1e293b;
        }}
        @media only screen and (max-width: 620px) {{
            .email-container {{
                width: 100% !important;
                border-radius: 0 !important;
            }}
            .card-body {{
                padding: 18px !important;
            }}
        }}
    </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #f1f5f9; font-family: 'Vazirmatn', Tahoma, sans-serif;" dir="rtl">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f1f5f9;">
        <tr>
            <td align="center" style="padding: 12px;">
                <!-- Main Card -->
                <table role="presentation" class="email-container" width="600" cellpadding="0" cellspacing="0" style="width: 600px; max-width: 600px; background-color: #ffffff; border-radius: 14px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);">
                    
                    <!-- Top Brand Bar -->
                    <tr>
                        <td style="background-color: #0f172a; padding: 20px 24px; border-bottom: 3px solid #ff9a3d; text-align: center;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="text-align: right;">
                                        <a href="{BRAND_SITE_URL}" target="_blank" style="text-decoration: none; color: #ffffff; font-size: 19px; font-weight: 700; letter-spacing: -0.3px;">
                                            <span style="color: #ff9a3d;">اسپاگتی</span> پرینت
                                        </a>
                                        <div style="color: #94a3b8; font-size: 11px; margin-top: 2px;">Spaghetti Print 3D Studio</div>
                                    </td>
                                    <td style="text-align: left;">
                                        <span style="display: inline-block; background-color: {badge_bg}; color: {badge_text}; border: 1px solid {badge_border}; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 20px;">
                                            {badge_label}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td class="card-body" style="padding: 28px 26px;">
                            <!-- Greeting -->
                            <p style="margin: 0 0 16px 0; font-size: 14px; color: #334155; line-height: 1.6;">
                                {greeting}
                            </p>

                            <!-- Key Details Card -->
                            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 18px; margin-bottom: 20px;">
                                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; font-size: 14px;">
                                    <tr>
                                        <td style="padding: 6px 0; color: #64748b; width: 30%;">کد پیگیری:</td>
                                        <td style="padding: 6px 0; color: #0f172a; font-weight: 700; direction: ltr; text-align: right;">{_esc(code)}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 6px 0; color: #64748b;">نام مشتری:</td>
                                        <td style="padding: 6px 0; color: #0f172a; font-weight: 600;">{_esc(customer_name) if customer_name else "—"}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 6px 0; color: #64748b;">شماره تماس:</td>
                                        <td style="padding: 6px 0; color: #0f172a; direction: ltr; text-align: right; font-family: Tahoma, sans-serif;">{_esc(mobile) if mobile else "—"}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 6px 0; color: #64748b;">کانال ترجیحی:</td>
                                        <td style="padding: 6px 0; color: #0f172a;">{_esc(channel) if channel else "وبسایت"}</td>
                                    </tr>
                                    {"<tr><td style='padding: 6px 0; color: #64748b;'>شماره سفارش:</td><td style='padding: 6px 0; color: #0f172a; font-weight: 600;'>#" + _esc(order_id) + "</td></tr>" if order_id is not None else ""}
                                </table>
                            </div>

                            <!-- Items Section -->
                            <div style="margin-top: 10px;">
                                <div style="font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 6px;">
                                    لیست اقلام:
                                </div>
                                {items_table_html}
                            </div>

                            <!-- Total -->
                            {total_card_html}

                            <!-- Notice -->
                            {notice_html}

                            <!-- Primary Action CTA -->
                            {cta_html}
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px; text-align: center; color: #64748b; font-size: 12px; line-height: 1.7;">
                            <div>
                                <a href="{BRAND_SITE_URL}" target="_blank" style="color: #ff9a3d; text-decoration: none; font-weight: 600;">
                                    {BRAND_NAME_FA}
                                </a>
                                &nbsp;•&nbsp; پرینت سه‌بعدی صنعتی و خدمات طراحی قطعات
                            </div>
                            <div style="color: #94a3b8; margin-top: 4px;">
                                این ایمیل به‌صورت خودکار از سوی سامانه ارسال شده است.
                            </div>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
