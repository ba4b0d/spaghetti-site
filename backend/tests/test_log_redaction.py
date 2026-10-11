"""I3 (backend layer) — redact the invoice bearer token from uvicorn's access log.

nginx disables its own access log for the token prefix, but uvicorn keeps a
separate access log. These tests pin the filter that scrubs the token path
segment from access records (any case) while leaving ordinary access logging
intact, and pin that it is actually installed on ``uvicorn.access``.
"""
import logging

import pytest

from app.log_redaction import (
    REDACTED,
    RedactInvoiceTokenFilter,
    RedactSnappayCallbackFilter,
    install_access_log_redaction,
    redact_access_path,
    redact_snappay_query,
)

# uvicorn's access-log line shape (see uvicorn.logging.AccessFormatter).
ACCESS_MSG = '%s - "%s %s HTTP/%s" %d'


def _access_record(full_path, method="GET", status=200):
    logger = logging.getLogger("uvicorn.access")
    return logger.makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        ACCESS_MSG,
        ("1.2.3.4", method, full_path, "HTTP/1.1", status),
        None,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/commerce/invoices/AbC123token",
        "/api/v1/commerce/invoices/AbC123token/pay",
        "/API/v1/Commerce/Invoices/AbC123token",          # mixed case variant
        "/api/v1/commerce/invoices/AbC123token?x=1",      # query retained
        "http://host/api/v1/commerce/invoices/tok%2Fx",   # url-encoded token
    ],
)
def test_filter_redacts_token_and_preserves_rest(path):
    record = _access_record(path)
    RedactInvoiceTokenFilter().filter(record)
    line = record.getMessage()
    assert "AbC123token" not in line
    assert "tok%2Fx" not in line
    assert "/api/v1/commerce/invoices/" in line.lower()
    assert REDACTED in line
    # The method / HTTP version / status are untouched.
    assert "HTTP/1.1" in line and '" 200' in line


def test_filter_leaves_ordinary_paths_untouched():
    record = _access_record("/api/v1/commerce/staff/invoices")
    before = record.args
    RedactInvoiceTokenFilter().filter(record)
    assert record.args == before
    assert REDACTED not in record.getMessage()


def test_redact_access_path_unit():
    assert (
        redact_access_path("/api/v1/commerce/invoices/SEKRET/pay")
        == f"/api/v1/commerce/invoices/{REDACTED}/pay"
    )
    assert redact_access_path("/api/v1/products") == "/api/v1/products"
    # Only the token segment is replaced, not the rest of the path.
    assert (
        redact_access_path("/api/v1/commerce/invoices/SEKRET?after=1")
        == f"/api/v1/commerce/invoices/{REDACTED}?after=1"
    )


def test_filter_attached_to_uvicorn_access_and_is_idempotent():
    install_access_log_redaction()
    install_access_log_redaction()  # must not stack duplicates
    filters = [
        f for f in logging.getLogger("uvicorn.access").filters
        if isinstance(f, RedactInvoiceTokenFilter)
    ]
    assert len(filters) == 1


def test_access_log_capture_redacts_token_end_to_end():
    """Emit a real access record through a handler; assert the token is gone."""
    logger = logging.getLogger("uvicorn.access")
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):  # noqa: D401
            captured.append(record.getMessage())

    handler = _Capture()
    prev_level, prev_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    install_access_log_redaction()
    try:
        logger.info(
            ACCESS_MSG, "9.9.9.9", "POST",
            "/api/v1/commerce/invoices/SUPERSECRETTOKEN/pay", "HTTP/1.1", 200,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.propagate = prev_propagate

    assert captured, "access record was not emitted"
    line = captured[0]
    assert "SUPERSECRETTOKEN" not in line
    assert f"/api/v1/commerce/invoices/{REDACTED}/pay" in line
    assert "POST" in line and "HTTP/1.1" in line and "200" in line


def test_app_installs_redaction_at_startup():
    """Importing the app (its startup side-effect) installs the filter."""
    import app.main  # noqa: F401

    assert any(
        isinstance(f, RedactInvoiceTokenFilter)
        for f in logging.getLogger("uvicorn.access").filters
    )


def test_uvicorn_real_formatter_renders_the_redacted_line():
    """End-to-end through uvicorn's own AccessFormatter (it unpacks record.args)."""
    formatter_cls = pytest.importorskip("uvicorn.logging").AccessFormatter
    formatter = formatter_cls()
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        "uvicorn.access", logging.INFO, __file__, 0, ACCESS_MSG,
        ("1.2.3.4", "GET", "/api/v1/commerce/invoices/TOK9secret/pay", "HTTP/1.1", 200),
        None,
    )
    RedactInvoiceTokenFilter().filter(record)
    line = formatter.format(record)
    assert "TOK9secret" not in line
    assert "/api/v1/commerce/invoices/<redacted>/pay" in line


# ── SnappPay onboarding callback — the fixed path is a reachability stub whose
# query string is unparsed (SnappPay issued no protocol), so the whole query
# must be scrubbed from the uvicorn access line while the fixed path, method,
# HTTP version and status survive and ordinary/invoice paths are untouched. ──

SNAPPAY_CB = "/api/v1/commerce/snappay/callback"


def test_redact_snappay_query_unit():
    assert (
        redact_snappay_query(f"{SNAPPAY_CB}?token=SEKRET&amount=1")
        == f"{SNAPPAY_CB}?{REDACTED}"
    )
    # a bare callback (no query) is unchanged
    assert redact_snappay_query(SNAPPAY_CB) == SNAPPAY_CB
    # a query on a look-alike sub-path is still scrubbed
    assert (
        redact_snappay_query(f"{SNAPPAY_CB}/extra?token=SEKRET")
        == f"{SNAPPAY_CB}/extra?{REDACTED}"
    )
    # ordinary paths and the invoice token path are untouched by this redactor
    assert redact_snappay_query("/api/v1/products?page=2") == "/api/v1/products?page=2"
    inv = "/api/v1/commerce/invoices/SEKRET/pay"
    assert redact_snappay_query(inv) == inv


@pytest.mark.parametrize(
    "path",
    [
        f"{SNAPPAY_CB}?token=SNAPPAYSENTINEL",
        f"{SNAPPAY_CB}?signature=SNAPPAYSENTINEL&result=SUCCESS",
        "/API/v1/Commerce/Snappay/Callback?token=SNAPPAYSENTINEL",  # case variant
    ],
)
def test_snappay_filter_scrubs_query_and_preserves_rest(path):
    record = _access_record(path, method="POST", status=202)
    RedactSnappayCallbackFilter().filter(record)
    line = record.getMessage()
    assert "SNAPPAYSENTINEL" not in line
    assert SNAPPAY_CB in line.lower()
    assert REDACTED in line
    # The method / HTTP version / status are untouched, and the record is kept.
    assert "POST" in line and "HTTP/1.1" in line and "202" in line


def test_snappay_filter_leaves_ordinary_and_invoice_paths_untouched():
    for path in (
        "/api/v1/products?page=2",
        "/api/v1/commerce/invoices/AbC123token/pay",
    ):
        record = _access_record(path)
        before = record.args
        RedactSnappayCallbackFilter().filter(record)
        assert record.args == before
        assert REDACTED not in record.getMessage()


def test_invoice_filter_leaves_the_snappay_callback_untouched():
    """The two filters are independent: neither redacts the other's target."""
    record = _access_record(f"{SNAPPAY_CB}?token=SEKRET")
    before = record.args
    RedactInvoiceTokenFilter().filter(record)
    assert record.args == before
    assert REDACTED not in record.getMessage()


def test_both_credential_filters_installed_and_idempotent():
    install_access_log_redaction()
    install_access_log_redaction()  # must not stack duplicates
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, RedactInvoiceTokenFilter) for f in filters) == 1
    assert sum(isinstance(f, RedactSnappayCallbackFilter) for f in filters) == 1


def test_snappay_query_redacted_end_to_end_through_access_formatter():
    """End-to-end through uvicorn's own AccessFormatter (it unpacks record.args)."""
    formatter_cls = pytest.importorskip("uvicorn.logging").AccessFormatter
    formatter = formatter_cls()
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord(
        "uvicorn.access", logging.INFO, __file__, 0, ACCESS_MSG,
        ("1.2.3.4", "POST", f"{SNAPPAY_CB}?token=SNAPPAYSENTINEL", "HTTP/1.1", 202),
        None,
    )
    RedactSnappayCallbackFilter().filter(record)
    line = formatter.format(record)
    assert "SNAPPAYSENTINEL" not in line
    assert f"{SNAPPAY_CB}?{REDACTED}" in line


def test_snappay_access_record_emitted_and_scrubbed_end_to_end():
    """A real access record emitted through a handler keeps the path, drops the query."""
    logger = logging.getLogger("uvicorn.access")
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):  # noqa: D401
            captured.append(record.getMessage())

    handler = _Capture()
    prev_level, prev_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    install_access_log_redaction()
    try:
        logger.info(
            ACCESS_MSG, "9.9.9.9", "POST",
            f"{SNAPPAY_CB}?token=SUPERSENSITIVE&amount=1", "HTTP/1.1", 202,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.propagate = prev_propagate

    assert captured, "access record was not emitted"
    line = captured[0]
    assert "SUPERSENSITIVE" not in line
    assert f"{SNAPPAY_CB}?{REDACTED}" in line
