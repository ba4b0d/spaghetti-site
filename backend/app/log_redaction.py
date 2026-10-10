"""Redact the public commerce-invoice bearer token from access logs.

The public invoice token is a URL path credential, and the pay page hits it on
every load:

    GET  /api/v1/commerce/invoices/<token>
    POST /api/v1/commerce/invoices/<token>/pay

nginx is configured to disable its own access log for that prefix (see
``frontend/nginx.conf``), but the backend keeps uvicorn's access log
(``docker-compose.yml``). This filter rewrites the token in uvicorn's access
records to ``<redacted>`` so the credential never lands in the log, **without**
disabling access logging for the rest of the API.

The nginx layer and this filter are deliberately independent: nginx may be
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


class RedactInvoiceTokenFilter(logging.Filter):
    """Scrub the invoice token from the request line of access-log records.

    uvicorn logs access lines as ``'%s - "%s %s HTTP/%s" %d'`` with
    ``record.args = (client_addr, method, full_path, http_version, status_code)``;
    the full path (potentially carrying the token, and any query string) is one
    of the string args. The filter rewrites every string arg that contains the
    token and always keeps the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        args = record.args
        if isinstance(args, dict):
            for key, val in args.items():
                if isinstance(val, str) and _TOKEN_PATH_RE.search(val):
                    args[key] = redact_access_path(val)
        elif isinstance(args, tuple):
            record.args = tuple(
                redact_access_path(a) if isinstance(a, str) else a for a in args
            )
        return True


def install_access_log_redaction() -> None:
    """Attach the filter to ``uvicorn.access``. Idempotent (safe to re-call)."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactInvoiceTokenFilter) for f in logger.filters):
        logger.addFilter(RedactInvoiceTokenFilter())
