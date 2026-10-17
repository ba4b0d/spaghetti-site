"""Redact URL credentials from uvicorn's access log.

Two different URL credentials can land in an access line, and neither may be
written to the log:

* the public commerce-invoice bearer token — a *path* segment the pay page hits
  on every load::

      GET  /api/v1/commerce/invoices/<token>
      POST /api/v1/commerce/invoices/<token>/pay

* the SnappPay onboarding *callback query string* — whose contents are unparsed
  because SnappPay has issued no protocol or credentials::

      GET|POST /api/v1/commerce/snappay/callback?<anything>

* the BitPay gateway *callback query string* — ``trans_id`` / ``id_get`` arrive
  as query params and, by the same never-log-a-callback-query rule, are dropped::

      GET /api/v1/commerce/bitpay/callback?trans_id=<n>&id_get=<n>

nginx is configured to disable its own access log for both prefixes (see
``frontend/nginx.conf``), but the backend keeps uvicorn's access log
(``docker-compose.yml``). The filters here rewrite the credential in uvicorn's
access records to ``<redacted>`` so it never lands in the log, **without**
disabling access logging for the rest of the API.

The nginx layer and these filters are deliberately independent: nginx may be
bypassed (a direct hit on the published backend port) or a future location may
re-introduce the leak, so the backend redacts on its own.
"""
from __future__ import annotations

import logging
import re

REDACTED = "<redacted>"

# The token is URL-encoded by the client, so the path segment contains no
# literal '/' and ends at '/', '?' or '#'. Only the segment AFTER the fixed
# invoice prefix is replaced; the rest of the request line is preserved. Case
# insensitive to mirror the nginx `~*` block.
_TOKEN_PATH_RE = re.compile(
    r"(/api/v1/commerce/invoices/)([^/?#\s]+)",
    re.IGNORECASE,
)


def redact_access_path(value: str) -> str:
    """Return ``value`` with any invoice token path segment redacted."""
    return _TOKEN_PATH_RE.sub(lambda m: m.group(1) + REDACTED, value)


# ── SnappPay onboarding callback (URL *query* string) ────────────────────
# The callback path itself is fixed and non-secret; only its query string is
# dropped, because no SnappPay payload contract exists yet, so any value a
# caller puts there must be assumed sensitive. Matched case-insensitively to
# mirror the nginx `~*` companion, and as a path prefix (with an optional
# trailing segment) so a query on a look-alike sub-path is still scrubbed. The
# whole query — from the first '?' to the end of the request-target (which
# cannot contain whitespace) — is replaced, never parsed.
_SNAPPAY_CALLBACK_RE = re.compile(
    r"(/api/v1/commerce/snappay/callback(?:/[^\s?]*)?)(\?[^\s]*)?",
    re.IGNORECASE,
)


def redact_snappay_query(value: str) -> str:
    """Return ``value`` with any query string on the SnappPay callback redacted."""
    return _SNAPPAY_CALLBACK_RE.sub(
        lambda m: m.group(1) + ("?" + REDACTED if m.group(2) else ""),
        value,
    )


def _redact_string_args(record: logging.LogRecord, pattern, redactor) -> None:
    """Rewrite matching string args of an access record in place.

    uvicorn logs access lines as ``'%s - "%s %s HTTP/%s" %d'`` with
    ``record.args = (client_addr, method, full_path, http_version, status_code)``;
    the full request-target (potentially carrying the credential, and any query
    string) is one of the string args. Every string arg is passed through
    ``redactor`` (a no-op when it does not match) and the record is always kept.
    """
    args = record.args
    if isinstance(args, dict):
        for key, val in args.items():
            if isinstance(val, str) and pattern.search(val):
                args[key] = redactor(val)
    elif isinstance(args, tuple):
        record.args = tuple(
            redactor(a) if isinstance(a, str) else a for a in args
        )


class RedactInvoiceTokenFilter(logging.Filter):
    """Scrub the invoice token from the request line of access-log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        _redact_string_args(record, _TOKEN_PATH_RE, redact_access_path)
        return True


class RedactSnappayCallbackFilter(logging.Filter):
    """Scrub the SnappPay callback query from the request line of access records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        _redact_string_args(record, _SNAPPAY_CALLBACK_RE, redact_snappay_query)
        return True


# ── BitPay gateway GET callback (URL *query* string) ─────────────────────
# ``trans_id`` and ``id_get`` arrive as query params on a fixed path. They are
# gateway transaction identifiers, not credentials, but the same never-log-a-
# callback-query rule applies, so only the fixed path is retained. Matched as a
# path prefix (with an optional trailing segment) so a query on a look-alike
# sub-path is still scrubbed, case-insensitively to mirror the nginx `~*`
# companion.
_BITPAY_CALLBACK_RE = re.compile(
    r"(/api/v1/commerce/bitpay/callback(?:/[^\s?]*)?)(\?[^\s]*)?",
    re.IGNORECASE,
)


def redact_bitpay_query(value: str) -> str:
    """Return ``value`` with any query string on the BitPay callback redacted."""
    return _BITPAY_CALLBACK_RE.sub(
        lambda m: m.group(1) + ("?" + REDACTED if m.group(2) else ""),
        value,
    )


class RedactBitpayCallbackFilter(logging.Filter):
    """Scrub the BitPay callback query from the request line of access records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        _redact_string_args(record, _BITPAY_CALLBACK_RE, redact_bitpay_query)
        return True


# Every credential filter, installed together (each at most once) on uvicorn.access.
_ACCESS_FILTERS = (
    RedactInvoiceTokenFilter,
    RedactSnappayCallbackFilter,
    RedactBitpayCallbackFilter,
)


def install_access_log_redaction() -> None:
    """Attach the credential filters to ``uvicorn.access``. Idempotent (safe to re-call)."""
    logger = logging.getLogger("uvicorn.access")
    for filter_cls in _ACCESS_FILTERS:
        if not any(isinstance(f, filter_cls) for f in logger.filters):
            logger.addFilter(filter_cls())
