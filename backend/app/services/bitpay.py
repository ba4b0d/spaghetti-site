"""BitPay gateway adapter (Task 1 — isolated provider transport).

Only the officially documented **gateway v2.2** flow is implemented here, and
nothing above this layer is wired up yet (no commerce, no callback route, no
frontend). The three documented steps are:

    create  ``POST {base}/payment/gateway-send``
            form ``api`` / ``amount`` / ``redirect`` / ``factorId`` (+ optional
            ``name`` / ``email`` / ``description`` / ``mobileNum`` /
            ``cardNum``). The reply is a **bare integer**, not JSON: a value
            ``> 0`` is the ``id_get`` transaction id, while ``-1``..``-5`` are
            the documented error codes.

    portal  ``https://bitpay.ir/payment/gateway-<id_get>-get``
            where the payer is sent. We always build this URL ourselves — the
            provider never hands us a redirect target to trust.

    verify  ``POST {base}/payment/gateway-result-second``
            form ``api`` / ``trans_id`` / ``id_get`` / ``json=1`` → JSON with
            ``status`` (``1`` = fresh success, ``11`` = already verified,
            ``-1``..``-4`` = errors) and ``amount`` / ``cardNum`` / ``factorId``
            on success.

The sandbox mirrors every path under ``/payment-test/*``; there is no separate
sandbox host, so live vs. sandbox is a **path-prefix** selection driven by
``BITPAY_ENV``.

Design rules enforced here (mirroring ``app/services/digipay.py``):

* Credentials come from the environment only — never the DB, front-end or git,
  and never appear in a log line, error message or ``repr``.
* The base host is restricted to ``bitpay.ir`` over HTTPS; an arbitrary
  override host or a tampered portal redirect is refused.
* Live vs. sandbox is explicit and never falls back — a misconfigured sandbox
  refuses to build a client rather than quietly talking to production.
* Responses are strictly parsed: a non-integer create body, a non-JSON verify
  body, a missing/invalid ``status`` or a non-positive ``trans_id``/``id_get``
  is an error, and the ``1`` vs ``11`` distinction is preserved.
* Tests inject a fake HTTP session; there is no code path here that requires a
  live socket.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

# ── Documented hosts and paths ───────────────────────────────────────
# Both live and sandbox live on the SAME host; only the path prefix differs.
BITPAY_HOST = "bitpay.ir"
BITPAY_LIVE_BASE_URL = "https://bitpay.ir"
BITPAY_TEST_BASE_URL = "https://bitpay.ir"
DEFAULT_BASE_URL = "https://bitpay.ir"
ALLOWED_BASE_HOSTS = (BITPAY_HOST,)

LIVE_PATH_PREFIX = "/payment"
TEST_PATH_PREFIX = "/payment-test"
SEND_PATH_SUFFIX = "/gateway-send"
RESULT_PATH_SUFFIX = "/gateway-result-second"

ENV_PRODUCTION = "production"
ENV_TEST = "test"

# Documented lower bound for ``amount`` (5000 rial == 500 toman).
MIN_AMOUNT_RIAL = 5000

DEFAULT_TIMEOUT = 15.0
MAX_TIMEOUT = 30.0

# Documented gateway-send error codes (bare-integer reply).
SEND_ERROR_CODES = {
    -1: "api is not recognised by bitpay",
    -2: "amount is not numeric or is below 5000 rial",
    -3: "redirect is a null/empty string",
    -4: "no gateway matches the submitted data (or it is awaiting approval)",
    -5: "bitpay could not reach the gateway / transient error",
}
# Documented gateway-result-second status codes.
VERIFY_ERROR_CODES = {
    -1: "api is not recognised by bitpay",
    -2: "trans_id is not numeric",
    -3: "id_get is not numeric",
    -4: "transaction does not exist or was not successful",
}
VERIFY_SUCCESS_FRESH = 1
VERIFY_SUCCESS_ALREADY = 11
VERIFY_SUCCESS_CODES = (VERIFY_SUCCESS_FRESH, VERIFY_SUCCESS_ALREADY)

_INT_RE = re.compile(r"[+-]?\d+")
_UNSIGNED_INT_RE = re.compile(r"\d+")


class BitPayError(Exception):
    """Provider / network-layer failure (transient, recoverable)."""


class BitPayConfigError(BitPayError):
    """Missing or unsafe adapter configuration."""


class BitPayResponseError(BitPayError):
    """Provider answered, but the payload was malformed or unsafe."""


@dataclass(frozen=True)
class BitPaySession:
    """A started payment session (documented create step)."""

    id_get: int
    redirect_url: str
    factor_id: str | None = None


@dataclass(frozen=True)
class BitPayVerification:
    """A parsed ``gateway-result-second`` reply (documented verify step)."""

    status: int
    is_success: bool
    already_verified: bool
    amount_rial: int | None = None
    card_num: str | None = None
    factor_id: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BitPayCallback:
    """The two documented GET callback params (untrusted hints)."""

    trans_id: int
    id_get: int
    factor_id: str | None = None


# ── Small typed coercions ────────────────────────────────────────────

def _signed_int(value) -> int | None:
    """Coerce a documented integer field, tolerating a numeric string."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_RE.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _positive_int(value, name: str) -> int:
    """Documented ``trans_id`` / ``id_get``: a strictly positive integer."""
    if value is None or isinstance(value, bool):
        raise BitPayError(f"{name} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and _UNSIGNED_INT_RE.fullmatch(value.strip()):
        parsed = int(value.strip())
    else:
        raise BitPayError(f"{name} must be a positive integer")
    if parsed <= 0:
        raise BitPayError(f"{name} must be a positive integer")
    return parsed


def _opt_str(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


# ── URL helpers ──────────────────────────────────────────────────────

def _host_in(url: str, hosts) -> bool:
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    return parsed.hostname.lower() in hosts


def is_allowed_base_url(url: str) -> bool:
    """Only a bare ``https://bitpay.ir`` origin is an acceptable API base."""
    parsed = urlsplit(url or "")
    if not _host_in(url, ALLOWED_BASE_HOSTS):
        return False
    if parsed.query or parsed.fragment:
        return False
    if parsed.path.rstrip("/"):
        return False
    return True


def portal_redirect_pattern(env: str) -> re.Pattern:
    prefix = TEST_PATH_PREFIX if env == ENV_TEST else LIVE_PATH_PREFIX
    return re.compile(rf"^{re.escape(prefix)}/gateway-\d+-get$")


def build_portal_redirect(id_get: int, *, env: str = ENV_PRODUCTION,
                          base_url: str = DEFAULT_BASE_URL) -> str:
    """Build — and validate — the documented payer portal URL."""
    prefix = TEST_PATH_PREFIX if env == ENV_TEST else LIVE_PATH_PREFIX
    return assert_portal_redirect(
        f"{base_url.rstrip('/')}{prefix}/gateway-{int(id_get)}-get", env=env
    )


def assert_portal_redirect(url: str, *, env: str = ENV_PRODUCTION) -> str:
    """Reject anything that is not a documented BitPay HTTPS portal URL.

    The allowlist is exact: the host must be ``bitpay.ir`` over HTTPS, the path
    must match ``/payment[-test]/gateway-<digits>-get`` for the *selected*
    environment, and there must be no credentials, query or fragment. This is
    what stops a tampered response handing the customer's browser to an
    attacker-controlled host.
    """
    parsed = urlsplit(url or "")
    if parsed.scheme != "https":
        raise BitPayResponseError("portal redirect must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise BitPayResponseError("portal redirect must not embed credentials")
    if parsed.query or parsed.fragment:
        raise BitPayResponseError("portal redirect must not carry a query or fragment")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_BASE_HOSTS:
        raise BitPayResponseError("portal redirect host is not an allowed BitPay host")
    if not portal_redirect_pattern(env).match(parsed.path or ""):
        raise BitPayResponseError(
            "portal redirect path is not a documented BitPay gateway URL"
        )
    return url


def _valid_callback_url(url: str) -> str:
    """Our own return URL: an absolute, credential-free HTTPS URL."""
    parsed = urlsplit(url or "")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise BitPayConfigError(
            "BitPay redirect (callback) URL must be a bare absolute HTTPS URL"
        )
    return url


# ── Environment selection ────────────────────────────────────────────

def resolve_env(raw: str | None = None) -> str:
    """Explicit live/sandbox selection; a typo never silently means live."""
    value = (raw if raw is not None else os.getenv("BITPAY_ENV") or "").strip().lower()
    if value in ("", ENV_PRODUCTION, "live", "prod"):
        return ENV_PRODUCTION
    if value in (ENV_TEST, "sandbox", "staging", "uat"):
        return ENV_TEST
    raise BitPayConfigError(
        f"BITPAY_ENV={value!r} is not a recognised environment "
        "(use 'production' or 'test')"
    )


def resolve_base_url() -> str:
    """Explicit env selection; an arbitrary override host is refused."""
    override = (os.getenv("BITPAY_BASE_URL") or "").strip().rstrip("/")
    if override:
        if not is_allowed_base_url(override):
            raise BitPayConfigError(
                "BITPAY_BASE_URL must be an allowed BitPay HTTPS base URL"
            )
        return override
    return DEFAULT_BASE_URL


# ── Client ───────────────────────────────────────────────────────────

class BitPayClient:
    """Thin, testable BitPay gateway client. The HTTP session is injectable."""

    def __init__(
        self,
        *,
        api_key: str,
        env: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session=None,
    ):
        key = (api_key or "").strip()
        if not key:
            raise BitPayConfigError("BitPay API key is required")
        self._api_key = key
        self._env = resolve_env(env)
        resolved = (base_url or resolve_base_url()).strip().rstrip("/")
        if not is_allowed_base_url(resolved):
            raise BitPayConfigError("BitPay base URL is not an allowed HTTPS host")
        self._base_url = resolved
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not (0 < timeout <= MAX_TIMEOUT)
        ):
            raise BitPayConfigError(
                f"BitPay timeout must be between 0 and {MAX_TIMEOUT} seconds"
            )
        self._timeout = float(timeout)
        self._session = session if session is not None else requests.Session()

    # ── lifecycle / introspection ────────────────────────────────────

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    def __repr__(self) -> str:  # pragma: no cover - trivial, but must mask
        return (
            f"BitPayClient(env={self._env!r}, base_url={self._base_url!r}, "
            f"api_key='***', timeout={self._timeout!r})"
        )

    @property
    def env(self) -> str:
        return self._env

    @property
    def path_prefix(self) -> str:
        return TEST_PATH_PREFIX if self._env == ENV_TEST else LIVE_PATH_PREFIX

    @property
    def send_url(self) -> str:
        return f"{self._base_url}{self.path_prefix}{SEND_PATH_SUFFIX}"

    @property
    def result_url(self) -> str:
        return f"{self._base_url}{self.path_prefix}{RESULT_PATH_SUFFIX}"

    # ── transport ────────────────────────────────────────────────────

    def _post(self, url: str, data: dict):
        try:
            resp = self._session.post(url, data=data, timeout=self._timeout)
        except BitPayError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport failure is transient
            raise BitPayError(
                f"BitPay request to {url} failed ({exc.__class__.__name__})"
            ) from exc
        status_code = getattr(resp, "status_code", 200)
        if status_code is not None and status_code >= 400:
            raise BitPayError(f"BitPay {url} failed (HTTP {status_code})")
        return resp

    # ── create ───────────────────────────────────────────────────────

    def create_payment(
        self,
        *,
        amount_rial: int,
        redirect_url: str,
        factor_id=None,
        name=None,
        email=None,
        description=None,
        mobile=None,
        card_num=None,
    ) -> BitPaySession:
        """Start a documented transaction and return the validated portal URL.

        ``amount_rial`` and ``redirect_url`` are validated *before* any
        transport call, so a bad request never leaves the process.
        """
        if isinstance(amount_rial, bool) or not isinstance(amount_rial, int):
            raise BitPayError("amount_rial must be an integer")
        if amount_rial < MIN_AMOUNT_RIAL:
            raise BitPayError(
                f"amount_rial must be at least {MIN_AMOUNT_RIAL} rial"
            )
        redirect = _valid_callback_url(redirect_url)

        data = {"api": self._api_key, "amount": amount_rial, "redirect": redirect}
        if factor_id not in (None, ""):
            data["factorId"] = factor_id
        if name:
            data["name"] = name
        if email:
            data["email"] = email
        if description:
            data["description"] = description
        if mobile:
            data["mobileNum"] = mobile
        if card_num:
            data["cardNum"] = card_num

        resp = self._post(self.send_url, data)
        id_get = _parse_create_body(resp)
        redirect_out = build_portal_redirect(
            id_get, env=self._env, base_url=self._base_url
        )
        return BitPaySession(
            id_get=id_get, redirect_url=redirect_out, factor_id=factor_id
        )

    # ── verify ───────────────────────────────────────────────────────

    def verify(self, *, trans_id, id_get) -> BitPayVerification:
        """Server-to-server verification of a completed transaction."""
        parsed_trans = _positive_int(trans_id, "trans_id")
        parsed_id_get = _positive_int(id_get, "id_get")

        resp = self._post(
            self.result_url,
            {
                "api": self._api_key,
                "trans_id": parsed_trans,
                "id_get": parsed_id_get,
                "json": 1,
            },
        )
        return _parse_verify_body(resp)


# ── response parsers ─────────────────────────────────────────────────

def _parse_create_body(resp) -> int:
    raw = (getattr(resp, "text", "") or "").strip()
    if not _INT_RE.fullmatch(raw):
        raise BitPayResponseError("BitPay returned a non-integer gateway-send body")
    value = int(raw)
    if value > 0:
        return value
    if value in SEND_ERROR_CODES:
        raise BitPayResponseError(
            f"BitPay rejected the request (gateway-send code {value}: "
            f"{SEND_ERROR_CODES[value]})"
        )
    raise BitPayResponseError(f"BitPay returned an unusable transaction id ({value})")


def _parse_verify_body(resp) -> BitPayVerification:
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - any parse failure is a provider error
        raise BitPayResponseError("BitPay verify returned a non-JSON response") from exc
    if not isinstance(payload, dict):
        raise BitPayResponseError("BitPay verify returned an unexpected payload shape")
    status = _signed_int(payload.get("status"))
    if status is None:
        raise BitPayResponseError("BitPay verify response is missing a valid status")
    return BitPayVerification(
        status=status,
        is_success=status in VERIFY_SUCCESS_CODES,
        already_verified=status == VERIFY_SUCCESS_ALREADY,
        amount_rial=_signed_int(payload.get("amount")),
        card_num=_opt_str(payload.get("cardNum")),
        factor_id=_opt_str(payload.get("factorId")),
        raw=payload,
    )


# ── callback query parsing (untrusted hints; consumed in Task 2) ─────

def parse_callback_query(query) -> BitPayCallback:
    """Read the two documented GET params, strictly as positive integers.

    These values arrive from the customer's browser and are therefore never
    trusted: the caller must still verify server-to-server before any state
    change. ``factorId`` is carried through only as an optional hint.
    """
    query = query or {}
    return BitPayCallback(
        trans_id=_positive_int(query.get("trans_id"), "trans_id"),
        id_get=_positive_int(query.get("id_get"), "id_get"),
        factor_id=_opt_str(query.get("factorId")),
    )


# ── factory / FastAPI wiring ─────────────────────────────────────────

def get_client() -> BitPayClient:
    """Build a client from environment secrets; raise if unconfigured.

    A missing key is a hard configuration error — it never falls back to a
    different environment (e.g. sandbox → live).
    """
    api_key = (os.getenv("BITPAY_API_KEY") or "").strip()
    if not api_key:
        raise BitPayConfigError(
            "BitPay is not configured (BITPAY_API_KEY is missing)"
        )
    return BitPayClient(api_key=api_key)


def client_dependency() -> BitPayClient | None:
    """FastAPI dependency placeholder for Task 2.

    Production leaves this ``None`` so a handler resolves ``get_client()``
    lazily and a missing configuration yields a clean 503 rather than a
    startup 500. Tests override it with a fake provider.
    """
    return None
