"""Public payment-method readiness endpoint (Task 3 + Task 4 hardening).

The storefront pay page must never render a usable gateway CTA it cannot
actually pay through. It learns what is selectable from
``GET /api/v1/commerce/payment-methods`` — a *non-secret* capability snapshot.

Task 4 raised the bar for surfacing BitPay. A test key plus ``BITPAY_ENV=test``
is far too easy to copy onto the production host by accident, which would show
real customers a sandbox checkout. So ``bitpay.enabled`` now requires ALL of:

* a merchant key (``BITPAY_API_KEY``);
* an explicit **test** deployment (``BITPAY_ENV`` = test);
* a **dedicated opt-in flag** (``BITPAY_ENABLE_TEST_CHECKOUT``); and
* a validated ``PUBLIC_SITE_ORIGIN`` that is provably **non-production**
  (the production hosts are never allowed, even with the key + flag).

``digipay`` is parked and ``snapppay`` onboarding is non-settling, so both are
always reported disabled. The API key and every other credential are never
included, and a misconfigured environment fails closed.

A **live** checkout is a separate risk surface, so it gets its own gate: a
production ``BITPAY_ENV``, the production origin, a merchant key AND the
dedicated ``BITPAY_ENABLE_LIVE_CHECKOUT`` opt-in — the sandbox opt-in never
enables it, and a staging / localhost / malformed origin keeps it off.
"""
import pytest

BASE = "/api/v1/commerce"
# A clearly-fake, offline credential value: set as ``BITPAY_API_KEY`` only to
# prove the readiness snapshot reports "configured" WITHOUT ever echoing it.
SECRET_KEY = "offline-fake-bitpay-key-not-a-real-credential"

FLAG = "BITPAY_ENABLE_TEST_CHECKOUT"
LIVE_FLAG = "BITPAY_ENABLE_LIVE_CHECKOUT"
NONPROD_ORIGIN = "https://staging.spaghettiprints.ir"
PRODUCTION_ORIGINS = ["https://spaghettiprints.ir", "https://www.spaghettiprints.ir"]
LIVE_ORIGIN = "https://spaghettiprints.ir"

_ENV_VARS = (
    "BITPAY_API_KEY",
    "BITPAY_ENV",
    FLAG,
    LIVE_FLAG,
    "PUBLIC_SITE_ORIGIN",
    "DIGIPAY_ENABLE_CHECKOUT",
    "DIGIPAY_ENABLE_LIVE_CHECKOUT",
)


def _clear_bitpay_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _opt_in_test(monkeypatch, *, origin=NONPROD_ORIGIN, flag="1"):
    """Configure a fully-formed non-production test deployment."""
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "test")
    if flag is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, flag)
    if origin is None:
        monkeypatch.delenv("PUBLIC_SITE_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_SITE_ORIGIN", origin)


def _readiness(client, monkeypatch, **kwargs):
    _clear_bitpay_env(monkeypatch)
    _opt_in_test(monkeypatch, **kwargs)
    return client.get(f"{BASE}/payment-methods")


# ── Baseline ─────────────────────────────────────────────────────────

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


def test_bitpay_enabled_only_for_a_non_production_opted_in_test_deployment(client, monkeypatch):
    body = _readiness(client, monkeypatch).json()

    assert body["bitpay"]["enabled"] is True
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "test"
    assert body["digipay"]["enabled"] is False
    assert body["snapppay"]["enabled"] is False


# ── Task 4: the explicit, dedicated opt-in flag is mandatory ─────────

def test_bitpay_stays_disabled_without_the_explicit_opt_in_flag(client, monkeypatch):
    body = _readiness(client, monkeypatch, flag=None).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True        # key present...
    assert body["bitpay"]["environment"] == "test"     # ...and test env...


def test_opt_in_flag_must_be_truthy_not_merely_present(client, monkeypatch):
    body = _readiness(client, monkeypatch, flag="0").json()
    assert body["bitpay"]["enabled"] is False


# ── Task 4: the production origin is never allowed ───────────────────

@pytest.mark.parametrize("origin", PRODUCTION_ORIGINS)
def test_production_origin_with_test_key_and_flag_stays_disabled(
    client, monkeypatch, origin
):
    body = _readiness(client, monkeypatch, origin=origin).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "test"


@pytest.mark.parametrize(
    "origin",
    ["https://spaghettiprints.ir.", "https://www.spaghettiprints.ir."],
)
def test_trailing_dot_production_origin_stays_disabled(client, monkeypatch, origin):
    # A trailing-dot FQDN is the same host to every resolver (and to urlsplit,
    # which keeps the dot); it must not evade the production check.
    body = _readiness(client, monkeypatch, origin=origin).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "test"


def test_default_origin_is_production_so_bitpay_stays_disabled(client, monkeypatch):
    # No PUBLIC_SITE_ORIGIN → the shared helper defaults to the production site,
    # so even a key + flag + test env cannot surface a sandbox checkout.
    body = _readiness(client, monkeypatch, origin=None).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True


def test_invalid_origin_config_fails_closed(client, monkeypatch):
    body = _readiness(
        client, monkeypatch, origin="https://evil.example/path?leak=1"
    ).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True


# ── Task 4: a live environment is always disabled ────────────────────

@pytest.mark.parametrize("env", ["production", "live", "prod"])
def test_live_environment_stays_disabled_even_when_fully_configured(
    client, monkeypatch, env
):
    _clear_bitpay_env(monkeypatch)
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", env)
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", NONPROD_ORIGIN)

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "live"


def test_default_environment_is_live_so_bitpay_is_off(client, monkeypatch):
    # With a key and the opt-in flag but no explicit BITPAY_ENV the adapter
    # resolves to production, so the public flag must stay off.
    _clear_bitpay_env(monkeypatch)
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", NONPROD_ORIGIN)

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["environment"] == "live"


def test_misconfigured_environment_fails_closed(client, monkeypatch):
    # A typo never silently means live *or* test.
    _clear_bitpay_env(monkeypatch)
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", "prodction")
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", NONPROD_ORIGIN)

    body = client.get(f"{BASE}/payment-methods").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is False


# ── No credential may ever appear in the body ────────────────────────

def test_response_never_contains_the_api_key(client, monkeypatch):
    r = _readiness(client, monkeypatch)

    assert SECRET_KEY not in r.text
    # Belt-and-braces: no field name even looks credential-shaped. Both halves
    # must hold (``and``, not ``or``) or the check is vacuous.
    assert "api" not in r.text.lower() and "api_key" not in r.text.lower()


# ── Live checkout activation: production + dedicated live opt-in ─────
# A live checkout is a different risk surface from a sandbox one, so it gets its
# own gate: a production ``BITPAY_ENV``, the production origin, a merchant key
# AND the dedicated ``BITPAY_ENABLE_LIVE_CHECKOUT`` opt-in. The sandbox opt-in
# never enables it, and any other origin (staging, localhost, malformed) keeps
# it off — exactly mirroring how a sandbox checkout can never run on production.


def _live_env(
    monkeypatch, *, origin=LIVE_ORIGIN, live_flag="1", test_flag=None, env="production"
):
    """Configure a fully-formed live production deployment (and nothing test)."""
    _clear_bitpay_env(monkeypatch)
    monkeypatch.setenv("BITPAY_API_KEY", SECRET_KEY)
    monkeypatch.setenv("BITPAY_ENV", env)
    if live_flag is None:
        monkeypatch.delenv(LIVE_FLAG, raising=False)
    else:
        monkeypatch.setenv(LIVE_FLAG, live_flag)
    if test_flag is not None:
        monkeypatch.setenv(FLAG, test_flag)
    monkeypatch.setenv("PUBLIC_SITE_ORIGIN", origin)


def _live_readiness(client, monkeypatch, **kwargs):
    _live_env(monkeypatch, **kwargs)
    return client.get(f"{BASE}/payment-methods")


def test_live_checkout_enabled_only_for_full_production_opt_in(client, monkeypatch):
    body = _live_readiness(client, monkeypatch).json()

    assert body["bitpay"]["enabled"] is True
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "live"
    assert body["digipay"]["enabled"] is False
    assert body["snapppay"]["enabled"] is False


def test_live_checkout_stays_disabled_without_the_live_opt_in(client, monkeypatch):
    body = _live_readiness(client, monkeypatch, live_flag=None).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is True
    assert body["bitpay"]["environment"] == "live"


def test_test_opt_in_flag_never_enables_a_live_checkout(client, monkeypatch):
    # The sandbox opt-in must never activate a live checkout.
    body = _live_readiness(client, monkeypatch, live_flag=None, test_flag="1").json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["environment"] == "live"


def test_live_opt_in_flag_must_be_truthy_not_merely_present(client, monkeypatch):
    body = _live_readiness(client, monkeypatch, live_flag="0").json()
    assert body["bitpay"]["enabled"] is False


def test_live_checkout_stays_disabled_when_origin_is_non_production(client, monkeypatch):
    # A live key + live opt-in on a staging origin is refused: live never runs
    # off a provably non-production origin.
    body = _live_readiness(
        client, monkeypatch, origin="https://staging.spaghettiprints.ir"
    ).json()

    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["environment"] == "live"


def test_live_checkout_stays_disabled_for_localhost_origin(client, monkeypatch):
    body = _live_readiness(
        client, monkeypatch, origin="http://localhost:5173"
    ).json()
    assert body["bitpay"]["enabled"] is False


@pytest.mark.parametrize("env", ["live", "prod"])
def test_live_checkout_env_aliases_are_accepted(client, monkeypatch, env):
    body = _live_readiness(client, monkeypatch, env=env).json()
    assert body["bitpay"]["enabled"] is True
    assert body["bitpay"]["environment"] == "live"


@pytest.mark.parametrize(
    "origin", ["https://spaghettiprints.ir.", "https://www.spaghettiprints.ir."]
)
def test_live_checkout_accepts_trailing_dot_production_origin(client, monkeypatch, origin):
    # A trailing-dot FQDN names the same production host, and it is normalised
    # before the comparison, so a live deployment using it is still production.
    body = _live_readiness(client, monkeypatch, origin=origin).json()
    assert body["bitpay"]["enabled"] is True


def test_live_checkout_malformed_origin_fails_closed(client, monkeypatch):
    body = _live_readiness(
        client, monkeypatch, origin="https://evil.example/path?leak=1"
    ).json()
    assert body["bitpay"]["enabled"] is False


def test_live_checkout_misconfigured_env_fails_closed(client, monkeypatch):
    body = _live_readiness(client, monkeypatch, env="prodction").json()
    assert body["bitpay"]["enabled"] is False
    assert body["bitpay"]["configured"] is False
