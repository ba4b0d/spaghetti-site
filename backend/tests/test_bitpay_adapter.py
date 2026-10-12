"""Task 1 — isolated BitPay gateway adapter (backend only; no wiring).

Unit-level only: the HTTP session is always injected, so nothing in this file
can reach ``bitpay.ir``. The transport is pinned to the officially documented
v2.2 gateway contract:

    create  ``POST https://bitpay.ir/payment/gateway-send``
            form: api / amount / redirect / factorId (+ optional name, email,
            description, mobileNum); reply is a *bare* integer, not JSON —
            a value > 0 is the ``id_get`` transaction id, -1..-5 are errors.
    portal  ``https://bitpay.ir/payment/gateway-<id_get>-get``
    verify  ``POST https://bitpay.ir/payment/gateway-result-second``
            form: api / trans_id / id_get / json=1 → JSON with ``status``
            (1 = fresh success, 11 = already verified, -1..-4 = errors) plus
            ``amount`` / ``cardNum`` / ``factorId`` on success.

The documented sandbox mirrors every path under ``/payment-test/*``.

Security rules exercised here:

* credentials come from the environment only (never hardcoded, never printed);
* live vs sandbox is selected explicitly and never silently falls back;
* an arbitrary API host or a non-bitpay portal redirect is refused;
* the create body is strictly parsed as a positive transaction id;
* the verify payload is strictly parsed and the ``1`` vs ``11`` distinction is
  preserved rather than collapsed;
* the raw API key never appears in an error or a repr.
"""
import json

import pytest

# ── Documented endpoint constants (from the v2.2 PDF + test PDF) ──────
LIVE_SEND = "https://bitpay.ir/payment/gateway-send"
LIVE_RESULT = "https://bitpay.ir/payment/gateway-result-second"
TEST_SEND = "https://bitpay.ir/payment-test/gateway-send"
TEST_RESULT = "https://bitpay.ir/payment-test/gateway-result-second"
CALLBACK = "https://spaghettiprints.ir/api/v1/commerce/bitpay/callback"


# ══════════════════════════════════════════════════════════════════════
# Fake HTTP session — the only transport any test may use (no network)
# ══════════════════════════════════════════════════════════════════════

class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.headers = {}

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)

    def close(self):
        pass


def make_client(responses=None, **overrides):
    from app.services.bitpay import BitPayClient

    kwargs = dict(
        api_key="K" * 52,
        env="test",
        session=FakeSession(responses or []),
    )
    kwargs.update(overrides)
    return BitPayClient(**kwargs)


# ══════════════════════════════════════════════════════════════════════
# create — gateway-send
# ══════════════════════════════════════════════════════════════════════

def test_create_posts_documented_form_and_builds_portal_redirect():
    client = make_client([FakeResponse(200, text="1200")])
    result = client.create_payment(
        amount_rial=50000,
        redirect_url=CALLBACK,
        factor_id="3300",
    )
    # The id_get is the raw positive integer body; the payer portal is built
    # by us, never taken from a provider payload.
    assert result.id_get == 1200
    assert result.redirect_url == "https://bitpay.ir/payment-test/gateway-1200-get"

    call = client._session.calls[0]
    assert call["url"] == TEST_SEND
    assert call["data"]["api"] == "K" * 52
    assert call["data"]["amount"] == 50000
    assert call["data"]["redirect"] == CALLBACK
    assert call["data"]["factorId"] == "3300"
    assert call["timeout"] is not None


def test_create_live_env_uses_payment_paths():
    client = make_client([FakeResponse(200, text="77")], env="production")
    result = client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    assert client.env == "production"
    assert client.send_url == LIVE_SEND
    assert result.redirect_url == "https://bitpay.ir/payment/gateway-77-get"
    assert client._session.calls[0]["url"] == LIVE_SEND


def test_create_accepts_documented_optional_fields_when_supplied():
    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(
        amount_rial=5000,
        redirect_url=CALLBACK,
        factor_id="2",
        name="رضا",
        email="r@example.com",
        description="invoice",
        mobile="09123456789",
    )
    data = client._session.calls[0]["data"]
    assert data["name"] == "رضا"
    assert data["email"] == "r@example.com"
    assert data["description"] == "invoice"
    assert data["mobileNum"] == "09123456789"


def test_create_accepts_documented_card_num_when_supplied():
    """`cardNum` is a documented optional create field (v2.2 param table)."""
    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(
        amount_rial=5000,
        redirect_url=CALLBACK,
        card_num="6362125414435432",
    )
    assert client._session.calls[0]["data"]["cardNum"] == "6362125414435432"


def test_create_omits_unset_optional_fields():
    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    data = client._session.calls[0]["data"]
    for optional in ("name", "email", "description", "mobileNum", "cardNum", "factorId"):
        assert optional not in data


@pytest.mark.parametrize(
    "value,expected",
    [(3300, "3300"), ("3300", "3300"), ("  3300  ", "3300"), ("0007", "0007")],
)
def test_create_sends_latin_decimal_factor_id(value, expected):
    """The documented gateway needs a Latin-integer ``factorId``; a numeric
    string/int is forwarded verbatim (after trimming)."""
    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(amount_rial=5000, redirect_url=CALLBACK, factor_id=value)
    assert client._session.calls[0]["data"]["factorId"] == expected


@pytest.mark.parametrize(
    "bad",
    [
        "INV-1-R1",        # the pre-fix alnum merchant reference
        "INV3-R1-deadbeef",
        "abc",
        "12.3",
        "12a",
        "١٢",              # Arabic-Indic digits are NOT Latin decimals
        "+5",
        "-5",
        "1 2",
    ],
)
def test_create_refuses_non_latin_integer_factor_id(bad):
    """A non-integer ``factorId`` is silently coerced to ``0`` by the gateway,
    which is exactly the bug that broke matching — so it is refused up front,
    before any transport call ever leaves the process."""
    from app.services.bitpay import BitPayError

    client = make_client([FakeResponse(200, text="9")])
    with pytest.raises(BitPayError):
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK, factor_id=bad)
    assert client._session.calls == []


@pytest.mark.parametrize("blank", [None, "", "   ", "\t\n"])
def test_create_treats_blank_factor_id_as_absent(blank):
    """An unset/blank ``factorId`` is omitted, never sent as an empty value."""
    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(amount_rial=5000, redirect_url=CALLBACK, factor_id=blank)
    assert "factorId" not in client._session.calls[0]["data"]


def test_create_strips_surrounding_whitespace_in_body():
    client = make_client([FakeResponse(200, text=" 1200\n")])
    assert client.create_payment(amount_rial=5000, redirect_url=CALLBACK).id_get == 1200


@pytest.mark.parametrize("body", ["", "   ", "nope", "<html>", "{\"id\":1}", "1.5"])
def test_create_rejects_non_integer_body(body):
    from app.services.bitpay import BitPayResponseError

    client = make_client([FakeResponse(200, text=body)])
    with pytest.raises(BitPayResponseError):
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK)


@pytest.mark.parametrize("code", [-1, -2, -3, -4, -5])
def test_create_documented_error_codes_are_refused(code):
    from app.services.bitpay import BitPayResponseError

    client = make_client([FakeResponse(200, text=str(code))])
    with pytest.raises(BitPayResponseError) as exc:
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    # The documented code is surfaced for staff diagnostics, not swallowed.
    assert str(code) in str(exc.value)


def test_create_rejects_zero_id():
    from app.services.bitpay import BitPayResponseError

    client = make_client([FakeResponse(200, text="0")])
    with pytest.raises(BitPayResponseError):
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK)


def test_create_rejects_http_error_status():
    from app.services.bitpay import BitPayError

    client = make_client([FakeResponse(500, text="boom")])
    with pytest.raises(BitPayError):
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK)


@pytest.mark.parametrize("bad", [0, -1, 4999, "5000", 5000.0, True])
def test_create_rejects_invalid_amount(bad):
    from app.services.bitpay import BitPayError

    client = make_client([FakeResponse(200, text="1")])
    with pytest.raises(BitPayError):
        client.create_payment(amount_rial=bad, redirect_url=CALLBACK)


def test_create_accepts_documented_minimum_amount():
    from app.services.bitpay import MIN_AMOUNT_RIAL

    assert MIN_AMOUNT_RIAL == 5000
    client = make_client([FakeResponse(200, text="1")])
    client.create_payment(amount_rial=MIN_AMOUNT_RIAL, redirect_url=CALLBACK)
    assert client._session.calls[0]["data"]["amount"] == 5000


@pytest.mark.parametrize(
    "redirect",
    [
        "http://spaghettiprints.ir/cb",          # plaintext
        "https://user:pw@spaghettiprints.ir/cb",  # embedded credentials
        "spaghettiprints.ir/cb",                 # not absolute
        "",
    ],
)
def test_create_refuses_unsafe_callback_url(redirect):
    from app.services.bitpay import BitPayConfigError

    client = make_client([FakeResponse(200, text="1")])
    with pytest.raises(BitPayConfigError):
        client.create_payment(amount_rial=5000, redirect_url=redirect)


def test_create_does_not_call_out_when_amount_invalid():
    client = make_client([FakeResponse(200, text="1")])
    with pytest.raises(Exception):
        client.create_payment(amount_rial=1, redirect_url=CALLBACK)
    assert client._session.calls == []          # rejected before any transport


# ══════════════════════════════════════════════════════════════════════
# portal redirect allowlist
# ══════════════════════════════════════════════════════════════════════

def test_assert_portal_redirect_accepts_documented_live_shape():
    from app.services.bitpay import assert_portal_redirect

    url = assert_portal_redirect(
        "https://bitpay.ir/payment/gateway-1200-get", env="production"
    )
    assert url == "https://bitpay.ir/payment/gateway-1200-get"


def test_assert_portal_redirect_accepts_documented_test_shape():
    from app.services.bitpay import assert_portal_redirect

    url = assert_portal_redirect(
        "https://bitpay.ir/payment-test/gateway-12234-get", env="test"
    )
    assert url.endswith("/payment-test/gateway-12234-get")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/payment/gateway-1-get",
        "http://bitpay.ir/payment/gateway-1-get",
        "https://bitpay.ir.evil.example/payment/gateway-1-get",
        "https://bitpay.ir/payment/gateway-abc-get",
        "https://bitpay.ir/payment/gateway--get",
        "https://bitpay.ir/payment/other-1-get",
        "https://bitpay.ir/payment/gateway-1-get?next=https://evil.example",
        "https://user:pw@bitpay.ir/payment/gateway-1-get",
        "//bitpay.ir/payment/gateway-1-get",
    ],
)
def test_assert_portal_redirect_refuses_anything_else(url):
    from app.services.bitpay import BitPayResponseError, assert_portal_redirect

    with pytest.raises(BitPayResponseError):
        assert_portal_redirect(url, env="production")


def test_portal_redirect_is_environment_scoped():
    """A live client never hands the browser a test portal (and vice versa)."""
    from app.services.bitpay import BitPayResponseError, assert_portal_redirect

    with pytest.raises(BitPayResponseError):
        assert_portal_redirect("https://bitpay.ir/payment-test/gateway-1-get", env="production")
    with pytest.raises(BitPayResponseError):
        assert_portal_redirect("https://bitpay.ir/payment/gateway-1-get", env="test")


# ══════════════════════════════════════════════════════════════════════
# verify — gateway-result-second
# ══════════════════════════════════════════════════════════════════════

def test_verify_posts_documented_form_with_json_flag():
    client = make_client([FakeResponse(200, json_data={"status": 1})])
    client.verify(trans_id=123, id_get=1200)
    call = client._session.calls[0]
    assert call["url"] == TEST_RESULT
    assert call["data"]["api"] == "K" * 52
    assert call["data"]["trans_id"] == 123
    assert call["data"]["id_get"] == 1200
    assert str(call["data"]["json"]) == "1"
    assert call["timeout"] is not None


def test_verify_status_one_is_fresh_success_with_identity():
    client = make_client([
        FakeResponse(200, json_data={
            "status": 1,
            "amount": 50000,
            "cardNum": "6037****1234",
            "factorId": "INV-1-R1",
        })
    ])
    v = client.verify(trans_id=123, id_get=1200)
    assert v.status == 1
    assert v.is_success is True
    assert v.already_verified is False
    assert v.amount_rial == 50000
    assert v.card_num == "6037****1234"
    assert v.factor_id == "INV-1-R1"


def test_verify_status_eleven_is_already_verified_and_not_collapsed():
    """11 must stay distinct from 1 so a replay is never treated as fresh."""
    client = make_client([
        FakeResponse(200, json_data={
            "status": 11,
            "amount": 50000,
            "cardNum": "6037****1234",
            "factorId": "INV-1-R1",
        })
    ])
    v = client.verify(trans_id=123, id_get=1200)
    assert v.status == 11
    assert v.is_success is True
    assert v.already_verified is True


@pytest.mark.parametrize("code", [-1, -2, -3, -4])
def test_verify_documented_error_codes_are_not_success(code):
    client = make_client([FakeResponse(200, json_data={"status": code})])
    v = client.verify(trans_id=1, id_get=1)
    assert v.status == code
    assert v.is_success is False
    assert v.already_verified is False


@pytest.mark.parametrize(
    "payload",
    [
        None,                                   # not JSON at all
        [],                                     # not an object
        {},                                     # missing status
        {"status": None},
        {"status": ""},
        {"status": "abc"},
        {"status": 1.5},
        {"status": True},
    ],
)
def test_verify_rejects_malformed_payload(payload):
    from app.services.bitpay import BitPayResponseError

    client = make_client([FakeResponse(200, json_data=payload)])
    with pytest.raises(BitPayResponseError):
        client.verify(trans_id=1, id_get=1)


def test_verify_rejects_non_json_body():
    from app.services.bitpay import BitPayResponseError

    client = make_client([FakeResponse(200, text="<html>error</html>")])
    with pytest.raises(BitPayResponseError):
        client.verify(trans_id=1, id_get=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trans_id": 0, "id_get": 1},
        {"trans_id": -5, "id_get": 1},
        {"trans_id": 1, "id_get": 0},
        {"trans_id": 1, "id_get": -1},
        {"trans_id": "abc", "id_get": 1},
        {"trans_id": 1, "id_get": "xyz"},
        {"trans_id": None, "id_get": 1},
    ],
)
def test_verify_rejects_non_positive_ids(kwargs):
    from app.services.bitpay import BitPayError

    client = make_client([FakeResponse(200, json_data={"status": 1})])
    with pytest.raises(BitPayError):
        client.verify(**kwargs)
    assert client._session.calls == []          # rejected before any transport


# ══════════════════════════════════════════════════════════════════════
# callback query parsing (untrusted hint; Task 2 consumes it)
# ══════════════════════════════════════════════════════════════════════

def test_parse_callback_reads_positive_ids():
    from app.services.bitpay import parse_callback_query

    cb = parse_callback_query({"trans_id": "123", "id_get": "1200"})
    assert cb.trans_id == 123
    assert cb.id_get == 1200


def test_parse_callback_preserves_factor_id_as_optional_hint():
    from app.services.bitpay import parse_callback_query

    cb = parse_callback_query({"trans_id": "1", "id_get": "2", "factorId": "INV-9"})
    assert cb.factor_id == "INV-9"


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"trans_id": "123"},
        {"id_get": "1"},
        {"trans_id": "0", "id_get": "1"},
        {"trans_id": "-5", "id_get": "1"},
        {"trans_id": "abc", "id_get": "1"},
        {"trans_id": "123", "id_get": "1.5"},
        {"trans_id": "123", "id_get": ""},
    ],
)
def test_parse_callback_rejects_malformed(query):
    from app.services.bitpay import BitPayError, parse_callback_query

    with pytest.raises(BitPayError):
        parse_callback_query(query)


# ══════════════════════════════════════════════════════════════════════
# configuration — env-only credentials, explicit env, allowlisted host
# ══════════════════════════════════════════════════════════════════════

def test_resolve_env_defaults_to_production_and_is_explicit(monkeypatch):
    from app.services import bitpay

    monkeypatch.delenv("BITPAY_ENV", raising=False)
    assert bitpay.resolve_env() == "production"
    for name in ("test", "sandbox", "staging"):
        monkeypatch.setenv("BITPAY_ENV", name)
        assert bitpay.resolve_env() == "test"
    for name in ("production", "live"):
        monkeypatch.setenv("BITPAY_ENV", name)
        assert bitpay.resolve_env() == "production"
    # A typo must never silently pick live.
    monkeypatch.setenv("BITPAY_ENV", "banana")
    with pytest.raises(bitpay.BitPayConfigError):
        bitpay.resolve_env()


def test_client_refuses_arbitrary_base_host():
    from app.services.bitpay import BitPayClient, BitPayConfigError

    with pytest.raises(BitPayConfigError):
        BitPayClient(
            api_key="k" * 52,
            base_url="https://attacker.example",
            session=FakeSession([]),
        )
    with pytest.raises(BitPayConfigError):
        BitPayClient(
            api_key="k" * 52,
            base_url="http://bitpay.ir",           # plaintext refused
            session=FakeSession([]),
        )


def test_client_requires_api_key():
    from app.services.bitpay import BitPayClient, BitPayConfigError

    for bad in ("", "   ", None):
        with pytest.raises(BitPayConfigError):
            BitPayClient(api_key=bad, session=FakeSession([]))


def test_get_client_requires_env_api_key(monkeypatch):
    from app.services import bitpay

    monkeypatch.delenv("BITPAY_API_KEY", raising=False)
    monkeypatch.setenv("BITPAY_ENV", "test")
    with pytest.raises(bitpay.BitPayConfigError):
        bitpay.get_client()


def test_get_client_in_test_env_never_falls_back_to_live(monkeypatch):
    from app.services import bitpay

    # A test environment with a key stays on the sandbox paths...
    monkeypatch.setenv("BITPAY_ENV", "test")
    monkeypatch.setenv("BITPAY_API_KEY", "T" * 52)
    client = bitpay.get_client()
    assert client.env == "test"
    assert client.send_url == TEST_SEND
    assert client.result_url == TEST_RESULT

    # ...and with no key it refuses rather than building anything live.
    monkeypatch.delenv("BITPAY_API_KEY", raising=False)
    with pytest.raises(bitpay.BitPayConfigError):
        bitpay.get_client()


def test_get_client_reads_credentials_only_from_env(monkeypatch):
    from app.services import bitpay

    secret = "ENV-ONLY-SECRET-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
    monkeypatch.setenv("BITPAY_ENV", "production")
    monkeypatch.setenv("BITPAY_API_KEY", secret)
    client = bitpay.get_client()
    assert client.env == "production"
    # The api value only ever travels in the posted form, never in the repr.
    assert secret not in repr(client)


# ══════════════════════════════════════════════════════════════════════
# hardening — bounded timeout, no network, no key leakage
# ══════════════════════════════════════════════════════════════════════

def test_timeout_is_bounded_and_forwarded():
    from app.services.bitpay import DEFAULT_TIMEOUT, MAX_TIMEOUT, BitPayConfigError

    client = make_client([FakeResponse(200, text="9")])
    client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    timeout = client._session.calls[0]["timeout"]
    assert 0 < timeout <= MAX_TIMEOUT
    assert DEFAULT_TIMEOUT <= MAX_TIMEOUT

    with pytest.raises(BitPayConfigError):
        make_client([], timeout=0)
    with pytest.raises(BitPayConfigError):
        make_client([], timeout=-1)
    with pytest.raises(BitPayConfigError):
        make_client([], timeout=MAX_TIMEOUT + 1)


def test_injected_session_is_the_only_transport():
    """The client must use the injected session and open no real socket."""
    fake = FakeSession([FakeResponse(200, text="5")])
    client = make_client([], session=fake)
    assert client._session is fake
    client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    assert len(fake.calls) == 1


def test_api_key_never_appears_in_error_text():
    from app.services.bitpay import BitPayResponseError

    secret = "SENSITIVE-KEY-abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    client = make_client([FakeResponse(200, text="-1")], api_key=secret)
    with pytest.raises(BitPayResponseError) as exc:
        client.create_payment(amount_rial=5000, redirect_url=CALLBACK)
    assert secret not in str(exc.value)
    assert secret not in repr(exc.value)


def test_client_repr_masks_api_key():
    secret = "SECRET-abcdefghijklmnopqrstuvwxyz0123456789"
    client = make_client([], api_key=secret)
    rendered = repr(client)
    assert secret not in rendered
    assert "bitpay" in rendered.lower()
