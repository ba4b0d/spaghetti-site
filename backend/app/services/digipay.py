"""DigiPay UPG (Unified Payment Gateway) adapter — Task 3.

Only the documented **IPG / Wallet direct-payment** flow is implemented in v1:

    login   ``POST {base}/oauth/token``             password grant + HTTP Basic
    ticket  ``POST {base}/tickets/business?type=11`` amount/cellNumber/providerId/callbackUrl
    verify  ``POST {base}/purchases/verify?type=0|11`` trackingCode/providerId

``ticket``/``redirectUrl`` come back **top-level** (only ``result.status`` signals
success) and the verify response carries top-level ``amount``/``providerId``.
The verify ``type`` is the method the customer actually used — IPG (0) or
Wallet (11) — as reported by the callback, never the UPG ticket type.

Credit / BNPL are deliberately **not** enabled here: they additionally require a
``basketDetailsDto`` on the ticket request and a post-fulfillment
``/purchases/deliver`` call. Half-implementing those would let a customer appear
paid before fulfillment, so the task report documents the limitation instead.

Design rules enforced here (see spec "Public invoice and payment"):

* Credentials come from the environment only — never the DB, front-end or git.
* The API base URL and any ``redirectUrl`` are restricted to DigiPay-controlled
  HTTPS hosts; an arbitrary or plaintext URL is refused.
* No live request is made without explicit credentials; tests inject a fake
  HTTP session.
"""
import base64
import os
import threading
from urllib.parse import urlsplit

import requests

# ── Documented hosts ─────────────────────────────────────────────────
# API base URLs (docs "UPG" → Authentication). An env override may only
# point at one of these exact hosts.
DIGIPAY_LIVE_BASE_URL = "https://api.mydigipay.com/digipay/api"
DIGIPAY_UAT_BASE_URL = "https://uat.mydigipay.info/digipay/api"
LIVE_API_HOSTS = ("api.mydigipay.com",)
UAT_API_HOSTS = ("uat.mydigipay.info",)
ALLOWED_API_HOSTS = LIVE_API_HOSTS + UAT_API_HOSTS

# Browser redirect (web-pay) hosts. The docs UAT example redirects to
# ``https://uatweb.mydigipay.info/web-pay/tgs/<ticket>``; the live web-pay app
# is ``web.mydigipay.com``. Kept as an exact allowlist (never a wildcard
# ``*.mydigipay.com`` suffix), so a typo-squatted sibling domain cannot be
# injected into the customer's browser.
LIVE_REDIRECT_HOSTS = ("web.mydigipay.com",)
UAT_REDIRECT_HOSTS = ("uatweb.mydigipay.info",)

AGENT_HEADER = "WEB"
DIGIPAY_VERSION = "2022-02-02"
DIGIPAY_TICKET_TYPE = 11  # UPG ticket type (IPG / Wallet direct payment)
TOKEN_PATH = "/oauth/token"
TICKET_PATH = "/tickets/business"
VERIFY_PATH = "/purchases/verify"
CALLBACK_PATH = "/api/v1/commerce/digipay/callback"
DEFAULT_TIMEOUT = 15.0


class DigiPayError(Exception):
    """Provider / network-layer failure (transient, recoverable)."""


class DigiPayConfigError(DigiPayError):
    """Missing or unsafe adapter configuration."""


class DigiPayAuthError(DigiPayError):
    """OAuth credentials rejected by the provider."""


class DigiPayResponseError(DigiPayError):
    """Provider answered, but the payload was malformed or unsafe."""


def _int_or_none(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _result_status(payload) -> int | None:
    """Read ``result.status`` from a documented DigiPay envelope (or None)."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict):
        return _int_or_none(result.get("status"))
    return None


def _host_in(url: str, hosts) -> bool:
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    return parsed.hostname.lower() in hosts


def _api_host_allowed(url: str) -> bool:
    return _host_in(url, ALLOWED_API_HOSTS)


def is_uat_base_url(base_url: str) -> bool:
    return _host_in(base_url, UAT_API_HOSTS)


def assert_safe_redirect(url: str, *, hosts) -> str:
    """Only a documented DigiPay web-pay HTTPS URL may reach the customer.

    ``hosts`` is the environment-specific redirect allowlist so a live client
    never hands the browser a UAT host (or vice versa).
    """
    if not _host_in(url, hosts):
        raise DigiPayResponseError("redirectUrl is not an allowed DigiPay HTTPS URL")
    return url


def resolve_base_url() -> str:
    """Explicit env selection; an arbitrary override host is refused."""
    override = (os.getenv("DIGIPAY_BASE_URL") or "").strip().rstrip("/")
    if override:
        if not _api_host_allowed(override):
            raise DigiPayConfigError(
                "DIGIPAY_BASE_URL must be an allowed DigiPay HTTPS base URL"
            )
        return override
    env = (os.getenv("DIGIPAY_ENV") or "production").strip().lower()
    if env in ("staging", "uat", "test"):
        return DIGIPAY_UAT_BASE_URL
    return DIGIPAY_LIVE_BASE_URL


def build_callback_url() -> str:
    """The callback the gateway posts back to — server config only."""
    raw = (os.getenv("DIGIPAY_CALLBACK_URL") or "").strip()
    if raw:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise DigiPayConfigError(
                "DIGIPAY_CALLBACK_URL must be a bare absolute HTTPS URL"
            )
        return raw
    # Fall back to the validated public site origin (HTTPS enforced there).
    from app.services.commerce import public_site_origin

    return f"{public_site_origin()}{CALLBACK_PATH}"


def _safe_json(resp):
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - any parse failure is a provider error
        raise DigiPayResponseError("DigiPay returned a non-JSON response")
    if not isinstance(data, dict):
        raise DigiPayResponseError("DigiPay returned an unexpected payload shape")
    return data


class DigiPayClient:
    """Thin, testable UPG client. The HTTP session is injectable."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session=None,
    ):
        if not all((client_id, client_secret, username, password)):
            raise DigiPayConfigError("DigiPay credentials are incomplete")
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        resolved = (base_url or resolve_base_url()).rstrip("/")
        if not _api_host_allowed(resolved):
            raise DigiPayConfigError("DigiPay base URL is not an allowed host")
        self._base_url = resolved
        # Environment-scoped redirect allowlist: a UAT client only accepts the
        # documented UAT web-pay host and a live client only the live one.
        self._redirect_hosts = (
            UAT_REDIRECT_HOSTS if is_uat_base_url(resolved) else LIVE_REDIRECT_HOSTS
        )
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._token: str | None = None
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    # ── auth ─────────────────────────────────────────────────────────

    def login(self) -> str:
        """Fetch a bearer token via the password grant (HTTP Basic auth)."""
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode("utf-8")
        ).decode("ascii")
        resp = self._session.post(
            f"{self._base_url}{TOKEN_PATH}",
            headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
            data={
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
            },
            timeout=self._timeout,
        )
        if resp.status_code == 401:
            raise DigiPayAuthError("DigiPay rejected the credentials")
        if resp.status_code >= 400:
            raise DigiPayAuthError(f"DigiPay token request failed ({resp.status_code})")
        payload = _safe_json(resp)
        token = payload.get("access_token")
        if not token:
            raise DigiPayAuthError("DigiPay token response missing access_token")
        self._token = token
        return token

    def _auth_headers(self) -> dict:
        token = self._token or self.login()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Agent": AGENT_HEADER,
            "Digipay-Version": DIGIPAY_VERSION,
        }

    def _authed_post(self, path: str, *, params: dict, json_body: dict) -> dict:
        resp = self._session.post(
            f"{self._base_url}{path}",
            headers=self._auth_headers(),
            params=params,
            json=json_body,
            timeout=self._timeout,
        )
        if resp.status_code == 401:
            # Access token expired mid-flight — refresh once, then retry.
            with self._lock:
                self.login()
            resp = self._session.post(
                f"{self._base_url}{path}",
                headers=self._auth_headers(),
                params=params,
                json=json_body,
                timeout=self._timeout,
            )
        if resp.status_code >= 400:
            raise DigiPayError(f"DigiPay {path} failed ({resp.status_code})")
        return _safe_json(resp)

    # ── UPG operations ───────────────────────────────────────────────

    def create_ticket(
        self, *, amount_rial: int, mobile: str, provider_id: str, callback_url: str
    ) -> dict:
        """Request a business ticket and return the validated ``redirect_url``.

        Documented response (docs "UPG" → ticket):

            {"result": {"status": 0, ...}, "ticket": "v2:...",
             "redirectUrl": "https://<web-pay>/web-pay/tgs/v2:..."}

        ``ticket`` and ``redirectUrl`` are **top-level**; only the outcome flag
        lives inside ``result``. (Reading the redirect out of ``result`` — the
        earlier bug — always failed for a real gateway response.)
        """
        if isinstance(amount_rial, bool) or not isinstance(amount_rial, int) or amount_rial <= 0:
            raise DigiPayError("amount_rial must be a positive integer")
        payload = self._authed_post(
            TICKET_PATH,
            params={"type": DIGIPAY_TICKET_TYPE},
            json_body={
                "amount": amount_rial,
                "cellNumber": mobile,
                "providerId": provider_id,
                "callbackUrl": callback_url,
            },
        )
        status = _result_status(payload)
        if status != 0:
            raise DigiPayResponseError(
                f"DigiPay ticket was not accepted (result.status={status})"
            )
        redirect = payload.get("redirectUrl") or payload.get("redirect_url")
        if not redirect:
            raise DigiPayResponseError("DigiPay ticket response missing redirectUrl")
        return {
            "redirect_url": assert_safe_redirect(
                str(redirect), hosts=self._redirect_hosts
            ),
            "ticket": payload.get("ticket"),
            "provider_id": provider_id,
        }

    def verify(self, *, tracking_code: str, provider_id: str, type: int) -> dict:
        """Server-to-server verification; returns the full documented payload.

        Documented response (docs "UPG" → verify)::

            {"result": {"status": 0, "message": ..., "level": "INFO"},
             "trackingCode": "...", "providerId": "...", "amount": 200000,
             "paymentGateway": 3}

        The identity/amount fields are **top-level** and must be preserved for
        the caller to match against its stored attempt; the success flag is
        ``result.status``. ``type`` is the method the customer actually used
        (IPG=0 / Wallet=11), echoed from the callback.
        """
        payload = self._authed_post(
            VERIFY_PATH,
            params={"type": type},
            json_body={"trackingCode": tracking_code, "providerId": provider_id},
        )
        if not isinstance(payload.get("result"), dict):
            raise DigiPayResponseError("DigiPay verify response missing result")
        return payload


def get_client() -> DigiPayClient:
    """Build a client from environment secrets; raise if unconfigured."""
    client_id = (os.getenv("DIGIPAY_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("DIGIPAY_CLIENT_SECRET") or "").strip()
    username = (os.getenv("DIGIPAY_USERNAME") or "").strip()
    password = (os.getenv("DIGIPAY_PASSWORD") or "").strip()
    missing = [
        name
        for name, value in (
            ("DIGIPAY_CLIENT_ID", client_id),
            ("DIGIPAY_CLIENT_SECRET", client_secret),
            ("DIGIPAY_USERNAME", username),
            ("DIGIPAY_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise DigiPayConfigError(
            "DigiPay is not configured (missing: " + ", ".join(missing) + ")"
        )
    return DigiPayClient(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
    )


def client_dependency() -> DigiPayClient | None:
    """FastAPI dependency.

    Production leaves this ``None`` so the handler resolves ``get_client()``
    lazily and a missing configuration yields a clean 503 rather than a startup
    500. Tests override it with a fake provider.
    """
    return None
