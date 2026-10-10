"""Admin notifications for commerce events — Task 4.

Emits an admin alert on three **independent** channels after a commerce state
change has been committed:

    request_created   a website cart request was submitted
    invoice_approved  staff froze/draft -> approved and issued a private link
    payment_verified  a DigiPay payment was confirmed and the invoice marked paid

Design rules enforced here (see spec "Notifications"):

* ``notify_admin`` is called *after* the DB commit and **never raises** to the
  caller: a channel failure can never roll back (or lose) a committed order.
  Network sends are dispatched through ``FastAPI`` ``BackgroundTasks`` (see
  ``schedule_admin_delivery``) so the customer/staff HTTP response is not gated
  by a slow Telegram/SMS/SMTP round-trip; the payload is snapshotted to plain
  strings **before** the task is scheduled, so no ORM object or DB session is
  touched after the request closes.
* Every channel is opt-in through its own configuration. Missing credentials or
  a disabled toggle means the channel is *skipped*, never silently "sent"
  (public launch must not imply a channel works when it does not).
* Telegram reuses the existing ``send_telegram_notification``
  (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_ADMIN_CHAT_ID``) and HTML-escapes every
  piece of user-supplied text so a crafted name/description cannot inject markup.
* SMS.ir posts to ``/v1/send/verify`` with ``x-api-key`` and a configured
  approved template id; delivery is claimed only on a provider acknowledgement
  (``status == 1``). SMS.ir substitutes template parameters by **exact,
  case-sensitive name**, so the payload must use the template's approved names
  verbatim (``EVENT`` / ``CODE`` for template ``309349``) — a differently-cased
  name is not substituted and the send is rejected.
* SMTP requires host, port, username, password, from and to plus an explicit
  TLS mode (STARTTLS or SSL). There is deliberately **no** fallback to a
  personal mailbox: incomplete config disables the channel.
* A private invoice bearer token / ``/pay/<token>`` share link is **never**
  placed in an admin broadcast or a log line. Contact detail is minimized
  (phone masked, address and staff-only notes omitted).
* No network call is made from tests: the transports (``requests``, SMTP,
  Telegram) are injectable / monkeypatchable and nothing is sent unless a
  channel is fully configured.
"""
import html
import logging
import math
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

from app.telegram_bot import get_telegram_config, send_telegram_notification

logger = logging.getLogger(__name__)

# ── Events ───────────────────────────────────────────────────────────
EVENT_REQUEST_CREATED = "request_created"
EVENT_INVOICE_APPROVED = "invoice_approved"
EVENT_PAYMENT_VERIFIED = "payment_verified"
COMMERCE_NOTIFICATION_EVENTS = (
    EVENT_REQUEST_CREATED,
    EVENT_INVOICE_APPROVED,
    EVENT_PAYMENT_VERIFIED,
)

# Per-channel result codes returned by ``notify_admin``.
SENT = "sent"
SKIPPED = "skipped"
FAILED = "failed"

_EVENT_LABELS = {
    EVENT_REQUEST_CREATED: "درخواست جدید وبسایت",
    EVENT_INVOICE_APPROVED: "تأیید فاکتور",
    EVENT_PAYMENT_VERIFIED: "پرداخت موفق فاکتور",
}
_SMS_EVENT_LABELS = {
    EVENT_REQUEST_CREATED: "درخواست",
    EVENT_INVOICE_APPROVED: "فاکتور",
    EVENT_PAYMENT_VERIFIED: "پرداخت",
}

# ── Channel configuration ────────────────────────────────────────────
FLAG_TELEGRAM = "COMMERCE_NOTIFY_TELEGRAM"
FLAG_SMS = "COMMERCE_NOTIFY_SMS"
FLAG_SMTP = "COMMERCE_NOTIFY_SMTP"

SMS_IR_VERIFY_URL = "https://api.sms.ir/v1/send/verify"
SMS_TIMEOUT = 10.0

# Approved SMS.ir template parameter names. The provider substitutes parameters
# by EXACT, case-sensitive name, so these must match the approved template's
# placeholders verbatim. Template 309349 (admin alert) is approved with
# ``#EVENT#`` / ``#CODE#`` — the names are UPPERCASE. Emitting lowercase
# ``event`` / ``code`` is not substituted and the send is rejected.
SMS_PARAM_EVENT = "EVENT"
SMS_PARAM_CODE = "CODE"

# ── Customer checkout OTP (storefront cart) ──────────────────────────
# The one-time code sent to a *customer's own* mobile at checkout is a
# FUNCTIONAL delivery, independent of the admin-alert channel above: it needs
# only the API key and its own approved template, never the admin recipient or
# the COMMERCE_NOTIFY_SMS flag.
#
# Customer template 337011 is approved with the placeholders ``#OTP#`` (the
# one-time code) and ``#TIME#`` (validity in whole minutes). SMS.ir substitutes
# by EXACT, case-sensitive name — sending any other name leaves the placeholder
# literal in the delivered SMS (a real customer received "#OTP#" / "#TIME#"), so
# these names must match the approved template verbatim.
OTP_TEMPLATE_ID = 337011
OTP_PARAM_OTP = "OTP"
OTP_PARAM_TIME = "TIME"

SMTP_TIMEOUT = 15.0
TLS_STARTTLS = "starttls"
TLS_SSL = "ssl"
DEFAULT_SMTP_PORT = 587

# Never render more than this many line items into a broadcast.
MAX_ITEM_LINES = 20
_MAX_DETAIL = 300


def _safe(value) -> str:
    """Truncate an error string for logging without leaking a whole payload."""
    return str(value)[:_MAX_DETAIL]


def _flag_enabled(name: str, *, default: bool = True) -> bool:
    """Read a boolean feature toggle; unset/blank keeps the default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "disabled")


def _clean(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def sms_config() -> dict | None:
    """SMS.ir config, or None when disabled/incomplete (channel is skipped).

    Requires the API key, an approved template id and the admin recipient
    together: any missing piece disables the channel rather than sending an
    untemplated message.
    """
    if not _flag_enabled(FLAG_SMS):
        return None
    api_key = _clean("SMS_IR_API_KEY")
    template_raw = _clean("SMS_IR_TEMPLATE_ID")
    mobile = _clean("SMS_IR_ADMIN_MOBILE")
    if not (api_key and template_raw and mobile):
        return None
    try:
        template_id = int(template_raw)
    except ValueError:
        return None
    if template_id <= 0:
        return None
    return {"api_key": api_key, "template_id": template_id, "mobile": mobile}


def customer_otp_config() -> dict | None:
    """SMS.ir config for the CUSTOMER OTP template only: api_key + template id.

    No admin recipient, no admin-notify flag — this is functional delivery of a
    one-time code to a customer's own mobile, not an alert. ``sms_config`` above
    must NOT be reused for it: that one is gated on the ``COMMERCE_NOTIFY_SMS``
    toggle and requires ``SMS_IR_ADMIN_MOBILE``, neither of which applies here.
    """
    api_key = _clean("SMS_IR_API_KEY")
    template_raw = _clean("SMS_IR_OTP_TEMPLATE_ID", str(OTP_TEMPLATE_ID))
    if not (api_key and template_raw):
        return None
    try:
        template_id = int(template_raw)
    except ValueError:
        return None
    return {"api_key": api_key, "template_id": template_id} if template_id > 0 else None


def smtp_config() -> dict | None:
    """SMTP config, or None when disabled/incomplete (channel is skipped).

    A personal/derived mailbox is never assumed: host, username, password,
    sender and recipient must all be provided explicitly, with a TLS mode of
    ``starttls`` (default) or ``ssl``.
    """
    if not _flag_enabled(FLAG_SMTP):
        return None
    host = _clean("SMTP_HOST")
    username = _clean("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD") or ""
    sender = _clean("SMTP_FROM")
    recipient = _clean("SMTP_ADMIN_TO")
    tls = (_clean("SMTP_TLS", TLS_STARTTLS) or TLS_STARTTLS).lower()
    if tls not in (TLS_STARTTLS, TLS_SSL):
        return None
    if not (host and username and password and sender and recipient):
        return None
    port_raw = _clean("SMTP_PORT", str(DEFAULT_SMTP_PORT))
    try:
        port = int(port_raw)
    except ValueError:
        return None
    if not (0 < port < 65536):
        return None
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "sender": sender,
        "recipient": recipient,
        "tls": tls,
    }


# ── Render a broadcast ───────────────────────────────────────────────
def mask_mobile(mobile: str) -> str:
    """Reduce a contact phone to a staff-recognisable masked form.

    Only the first 4 and last 2 digits are kept so the admin can recognise a
    customer without the full number being broadcast or logged.
    """
    value = (mobile or "").strip()
    if len(value) < 7:
        return "—"
    return value[:4] + "*" * (len(value) - 6) + value[-2:]


def _esc(value) -> str:
    """HTML-escape untrusted text for the Telegram HTML broadcast."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _is_invoice(subject) -> bool:
    """Duck-typed distinction: invoices carry a ``total_toman``."""
    return hasattr(subject, "total_toman")


def _item_label(item) -> str:
    label = getattr(item, "display_name", None)
    if label is None:
        label = getattr(item, "description", "")
    return label


def _render_items_telegram(items) -> list[str]:
    lines = [
        f"• {_esc(_item_label(i))} × {getattr(i, 'qty', 1)}"
        for i in items[:MAX_ITEM_LINES]
    ]
    if len(items) > MAX_ITEM_LINES:
        lines.append(f"… و {len(items) - MAX_ITEM_LINES} آیتم دیگر")
    return lines or ["—"]


def build_payload(event: str, subject) -> dict:
    """Build the per-channel content for an event.

    The returned dict never contains a private token/share link; contact detail
    is minimized (masked phone, no address, no staff-only notes).
    """
    label = _EVENT_LABELS.get(event, event)
    invoice = _is_invoice(subject)

    if invoice:
        code = f"#{getattr(subject, 'id', '?')}"
        name = getattr(subject, "customer_name", "")
        mobile = mask_mobile(getattr(subject, "mobile", ""))
        channel = getattr(subject, "messenger", "")
        total = getattr(subject, "total_toman", None)
        order_id = getattr(subject, "order_id", None)
        items = list(getattr(subject, "items", []) or [])
    else:
        code = getattr(subject, "receipt_id", None) or f"#{getattr(subject, 'id', '?')}"
        name = getattr(subject, "customer_name", "")
        mobile = mask_mobile(getattr(subject, "mobile", ""))
        channel = getattr(subject, "messenger", "")
        total = None
        order_id = None
        items = list(getattr(subject, "items", []) or [])

    # ── Telegram (HTML) ──
    tg_lines = [
        f"🔔 <b>{_esc(label)}</b>",
        f"کد: <b>{_esc(code)}</b>",
        f"مشتری: {_esc(name)}",
        f"موبایل: <code>{_esc(mobile)}</code>",
        f"کانال: {_esc(channel)}",
    ]
    if total is not None:
        tg_lines.append(f"مبلغ: {int(total):,} تومان")
    tg_lines.append("آیتمها:")
    tg_lines.extend(_render_items_telegram(items))
    if order_id is not None:
        tg_lines.append(f"سفارش: #{order_id}")

    # ── Email (plain text) ──
    email_lines = [
        label,
        f"کد: {code}",
        f"مشتری: {name}",
        f"موبایل: {mobile}",
        f"کانال: {channel}",
    ]
    if total is not None:
        email_lines.append(f"مبلغ: {int(total):,} تومان")
    email_lines.append("آیتمها:")
    for item in items[:MAX_ITEM_LINES]:
        email_lines.append(f"- {_item_label(item)} × {getattr(item, 'qty', 1)}")
    if len(items) > MAX_ITEM_LINES:
        email_lines.append(f"... و {len(items) - MAX_ITEM_LINES} آیتم دیگر")
    if order_id is not None:
        email_lines.append(f"سفارش: #{order_id}")

    # ── SMS (approved template parameters, no PII) ──
    # Exact, case-sensitive names matching the approved template placeholders.
    sms_parameters = [
        {"name": SMS_PARAM_EVENT, "value": _SMS_EVENT_LABELS.get(event, event)},
        {"name": SMS_PARAM_CODE, "value": code},
    ]

    return {
        "telegram": "\n".join(tg_lines),
        "email_subject": f"[Spaghetti Print] {label} {code}",
        "email_body": "\n".join(email_lines),
        "sms": sms_parameters,
    }


# ── Transports (the only place a network call happens) ───────────────
def post_sms_ir_verify(
    *,
    api_key: str,
    template_id: int,
    mobile: str,
    parameters: list,
    timeout: float = SMS_TIMEOUT,
    session=None,
) -> bool:
    """POST the SMS.ir verification/notification template; True only on ack.

    A non-2xx response, a non-JSON body or any ``status`` other than ``1`` is
    *not* a delivery: we never claim a send the provider did not acknowledge.
    """
    client = session if session is not None else requests
    resp = client.post(
        SMS_IR_VERIFY_URL,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"mobile": mobile, "templateId": template_id, "parameters": parameters},
        timeout=timeout,
    )
    if getattr(resp, "status_code", 0) >= 400:
        return False
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001 - a malformed body is a failed send
        return False
    if not isinstance(payload, dict):
        return False
    try:
        return int(payload.get("status")) == 1
    except (TypeError, ValueError):
        return False


def _otp_ttl_minutes() -> str:
    """The ``#TIME#`` value: the OTP lifetime as whole minutes.

    Imported locally: ``commerce_otp`` imports this module at top level, so a
    module-level import here would be circular. Rounds up so a TTL that is not
    a whole number of minutes still tells the customer how long the code lives.
    """
    from app.services.commerce_otp import OTP_TTL_SECONDS

    return str(math.ceil(OTP_TTL_SECONDS / 60))


def send_customer_otp(mobile: str, code: str) -> bool:
    """Send the storefront one-time code to the customer's own mobile.

    Functional delivery (not an admin alert): needs only the API key and the
    OTP template id. Returns ``False`` — never raises — when unconfigured or the
    provider does not acknowledge, so the caller can drop the unusable
    challenge. The ``code`` is never logged.
    """
    config = customer_otp_config()
    if config is None:
        return False
    param_otp = _clean("SMS_IR_OTP_PARAM_OTP", OTP_PARAM_OTP) or OTP_PARAM_OTP
    param_time = _clean("SMS_IR_OTP_PARAM_TIME", OTP_PARAM_TIME) or OTP_PARAM_TIME
    parameters = [
        {"name": param_otp, "value": code},
        {"name": param_time, "value": _otp_ttl_minutes()},
    ]
    try:
        acked = post_sms_ir_verify(
            api_key=config["api_key"],
            template_id=config["template_id"],
            mobile=mobile,
            parameters=parameters,
        )
    except Exception as exc:  # noqa: BLE001 - provider/network error is a failed send
        logger.warning("SMS.ir customer OTP send error: %s", _safe(exc))
        return False
    return bool(acked)


def send_smtp_mail(
    *,
    config: dict,
    subject: str,
    body: str,
    timeout: float = SMTP_TIMEOUT,
    smtp_factory=None,
) -> bool:
    """Send one admin email over STARTTLS or SSL. Returns True on completion."""
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message["Subject"] = subject
    message.set_content(body)

    host, port, tls = config["host"], config["port"], config["tls"]
    if smtp_factory is not None:
        client = smtp_factory(host, port, timeout=timeout)
    elif tls == TLS_SSL:
        client = smtplib.SMTP_SSL(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)

    with client as smtp:
        if tls == TLS_STARTTLS:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(config["username"], config["password"])
        smtp.sendmail(config["sender"], [config["recipient"]], message.as_string())
    return True


# ── Channels ─────────────────────────────────────────────────────────
def _telegram_configured() -> bool:
    """True when a bot token and at least one admin chat id are available.

    Used only to disambiguate a ``False`` from ``send_telegram_notification``:
    that helper returns ``False`` both for *unconfigured* and for a *failed*
    send, which must not be conflated (a real outage reported as a silent skip
    would hide a broken admin alert).
    """
    try:
        token, chat_ids, _proxy = get_telegram_config()
    except Exception as exc:  # noqa: BLE001 - config lookup must never raise
        logger.warning("telegram config lookup failed: %s", _safe(exc))
        return False
    return bool(token and chat_ids)


def send_telegram_message(text: str) -> str:
    """Telegram channel; SKIPPED when unconfigured, FAILED on a send error."""
    if not _flag_enabled(FLAG_TELEGRAM):
        return SKIPPED
    try:
        ok = send_telegram_notification(text)
    except Exception as exc:  # noqa: BLE001 - a channel failure is isolated
        logger.warning("telegram admin notification error: %s", _safe(exc))
        return FAILED
    if ok:
        return SENT
    # A configured-but-failing bot must be reported FAILED, not masked as a skip.
    return FAILED if _telegram_configured() else SKIPPED


def send_sms_alert(parameters: list) -> str:
    """SMS.ir admin channel; SKIPPED when unconfigured, FAILED when not acked."""
    config = sms_config()
    if config is None:
        return SKIPPED
    try:
        acked = post_sms_ir_verify(
            api_key=config["api_key"],
            template_id=config["template_id"],
            mobile=config["mobile"],
            parameters=parameters,
        )
    except Exception as exc:  # noqa: BLE001 - provider/network error
        logger.warning("SMS.ir admin notification error: %s", _safe(exc))
        return FAILED
    return SENT if acked else FAILED


def send_email_alert(subject: str, body: str) -> str:
    """SMTP admin channel; SKIPPED when unconfigured, FAILED on send error."""
    config = smtp_config()
    if config is None:
        return SKIPPED
    try:
        ok = send_smtp_mail(config=config, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001 - SMTP/network error
        logger.warning("SMTP admin notification error: %s", _safe(exc))
        return FAILED
    return SENT if ok else FAILED


# ── Entry point ──────────────────────────────────────────────────────
def _run_channel(name: str, event: str, send) -> str:
    """Run one channel in isolation; never raises, never logs message content."""
    try:
        status = send()
    except Exception as exc:  # noqa: BLE001 - independent channel failure
        logger.warning(
            "commerce notification failed event=%s channel=%s: %s",
            event, name, _safe(exc),
        )
        return FAILED
    if status not in (SENT, SKIPPED, FAILED):
        status = SENT if status else SKIPPED
    logger.info("commerce notification event=%s channel=%s status=%s", event, name, status)
    return status


def deliver_payload(event: str, payload: dict) -> dict:
    """Deliver a pre-built payload; touches no DB/ORM and never raises.

    This is what actually runs (via ``BackgroundTasks``) after the response is
    sent. ``payload`` must be the plain-dict snapshot from ``build_payload`` —
    because it holds no ORM object, delivery stays valid even though the request
    (and its DB session) has already closed. Each channel is attempted
    independently and a top-level guard ensures a background task can never
    raise into the ASGI layer after the response was produced.
    """
    try:
        return {
            "telegram": _run_channel(
                "telegram", event, lambda: send_telegram_message(payload["telegram"])
            ),
            "sms": _run_channel("sms", event, lambda: send_sms_alert(payload["sms"])),
            "email": _run_channel(
                "email", event,
                lambda: send_email_alert(payload["email_subject"], payload["email_body"]),
            ),
        }
    except Exception as exc:  # noqa: BLE001 - never leak out of a background task
        logger.warning("commerce notification delivery failed event=%s: %s", event, _safe(exc))
        return {"telegram": FAILED, "sms": FAILED, "email": FAILED}


def notify_admin(event: str, subject) -> dict:
    """Fire the admin notification for ``event`` about ``subject`` synchronously.

    Call **after** the DB commit. Returns ``{channel: "sent"|"skipped"|"failed"}``
    and never raises: each channel is attempted independently, so a Telegram /
    SMS / SMTP outage neither rolls back the order nor blocks the other
    channels.

    Prefer ``schedule_admin_delivery`` on an HTTP request path: this synchronous
    form blocks the caller for the full (up to ``SMS_TIMEOUT`` / ``SMTP_TIMEOUT``)
    network round-trip and is intended for direct/service callers and staff
    retry, where the per-channel result is the response.
    """
    try:
        payload = build_payload(event, subject)
    except Exception as exc:  # noqa: BLE001 - never let rendering break the caller
        logger.warning("commerce notification build failed event=%s: %s", event, _safe(exc))
        return {"telegram": FAILED, "sms": FAILED, "email": FAILED}
    return deliver_payload(event, payload)


def schedule_admin_delivery(background_tasks, event: str, subject) -> None:
    """Snapshot the payload now and deliver it after the HTTP response.

    The payload is built *while the caller's session is still open* (so any
    lazy-loaded relationship resolves) and converted to plain strings; the
    background task therefore never touches a detached ORM object or a closed
    session. With no task runner (``background_tasks is None``) delivery falls
    back to inline so direct/service callers keep working. Never raises.
    """
    try:
        payload = build_payload(event, subject)
    except Exception as exc:  # noqa: BLE001 - rendering must never break the caller
        logger.warning("commerce notification build failed event=%s: %s", event, _safe(exc))
        return
    if background_tasks is not None:
        background_tasks.add_task(deliver_payload, event, payload)
    else:
        deliver_payload(event, payload)
