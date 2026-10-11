"""Public payment-method readiness endpoint (Task 3, minimal backend signal).

The storefront pay page must never render a usable gateway CTA it cannot
actually pay through. It learns what is selectable from
``GET /api/v1/commerce/payment-methods`` — a *non-secret* capability snapshot:

* ``bitpay`` is enabled only when the backend is explicitly configured for a
  **test** deployment (a merchant key present AND ``BITPAY_ENV`` = test);
* ``digipay`` is parked and ``snapppay`` onboarding is non-settling, so both are
  always reported disabled;
* the API key and every other credential are never included.

These tests prove the flags, the environment gate, the fail-closed behaviour on
a misconfigured environment and that no secret can leak into the body.
"""
BASE = "/api/v1/commerce"
SECRET_KEY = "sk_TESTKEY_do_not_leak_123456"


def _clear_bitpay_env(monkeypatch):
    monkeypatch.delenv("BITPAY_API_KEY", raising=False)
    monkeypatch.delenv("BITPAY_ENV", raising=False)


def test_all_methods_disabled_when_bitpay_unconfigured(client, monkeypatch):
    _clear_bitpay_env(monkeypatch)

    r = client.get(f"{BASE}/payment-methods")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is False
    assert body["digipay"]["enabled"] is False
    assert body["snapppay"]["enabled"] is False
    # The private bearer URL is never cached.
    assert r.headers.get("Cache-Control") == "no-store"


def test_bitpay_enabled_only_for_configured_test_deployment(client, monkeypatch):
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "test")

    r = client.get(f"{BASE}/payment-methods")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["bitpay"]["enabled"] is True
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "test"
    assert body["digipay"]["enabled"] is False
    assert body["snapppay"]["enabled"] is False


def test_bitpay_stays_disabled_in_live_even_with_a_key(client, monkeypatch):
    # A configured live deployment must NOT switch customers onto production
    # before a merchant key + controlled live payment are authorised (Task 4).
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "production")

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "live"


def test_misconfigured_environment_fails_closed(client, monkeypatch):
    # A typo never silently means live *or* test.
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "prodction")

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is False


def test_default_environment_is_live_so_bitpay_is_off(client, monkeypatch):
    # With a key but no explicit BITPAY_ENV the adapter resolves to production,
    # so the public flag must stay off.
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.delenv("BITPAY_ENV", raising=False)

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["environment"] == "live"


def test_response_never_contains_the_api_key(client, monkeypatch):
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "test")

    r = client.get(f"{BASE}/payment-methods")

    assert SECRET_KEY not in r.text
    # Belt-and-braces: no credential-looking field sneaks in.
    assert "api" not in r.text.lower() or "api_key" not in r.text.lower()
