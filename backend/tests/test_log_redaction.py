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
    install_access_log_redaction,
    redact_access_path,
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
