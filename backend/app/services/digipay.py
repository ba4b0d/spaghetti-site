"""DigiPay UPG (Unified Payment Gateway) adapter — Task 3.

Only the documented **IPG / Wallet direct-payment** flow is implemented in v1:

    login   ``POST {base}/oauth/token``             password grant + HTTP Basic
    ticket  ``POST {base}/tickets/business?type=11`` amount/cellNumber/providerId/callbackUrl
    verify  ``POST {base}/purchases/verify?type=11`` trackingCode/providerId

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

# Documented UPG hosts. Both the API base URL and any browser redirect must live
# under one of these suffixes.
DIGIPAY_LIVE_BASE_URL = "https://api.mydigipay.com/digipay/api"
DIGIPAY_UAT_BASE_URL = "https://uat.mydigipay.info/digipay/api"
ALLOWED_HOST_SUFFIXES = (".mydigipay.com", ".mydigipay.info")
ALLOWED_HOSTS = ("mydigipay.com", "mydigipay.info")

AGENT_HEADER = "WEB"
DIGIPAY_VERSION = "2022-02-02"
DIGIPAY_TICKET_TYPE = 11  # IPG / Wallet direct payment
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


def _host_allowed(url: str) -> bool:
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host in ALLOWED_HOSTS or host.endswith(ALLOWED_HOST_SUFFIXES)


def assert_safe_redirect(url: str) -> str:
    """Only a DigiPay-controlled HTTPS URL may reach the customer's browser."""
    if not _host_allowed(url):
        raise DigiPayResponseError("redirectUrl is not an allowed DigiPay HTTPS URL")
    return url


def resolve_base_url() -> str:
    """Explicit env selection; an arbitrary override host is refused."""
    override = (os.getenv("DIGIPAY_BASE_URL") or "").strip().rstrip("/")
    if override:
        if not _host_allowed(override):
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
        if not _host_allowed(resolved):
            raise DigiPayConfigError("DigiPay base URL is not an allowed host")
        self._base_url = resolved
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
        """Request a business ticket and return the validated ``redirect_url``."""
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
        result = payload.get("result")
        if not isinstance(result, dict):
            result = payload
        redirect = result.get("redirectUrl") or result.get("redirect_url")
        if not redirect:
            raise DigiPayResponseError("DigiPay ticket response missing redirectUrl")
        return {"redirect_url": assert_safe_redirect(str(redirect)), "provider_id": provider_id}

    def verify(self, *, tracking_code: str, provider_id: str, type: int) -> dict:
        """Server-to-server verification; returns the provider ``result`` object."""
        payload = self._authed_post(
            VERIFY_PATH,
            params={"type": type},
            json_body={"trackingCode": tracking_code, "providerId": provider_id},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise DigiPayResponseError("DigiPay verify response missing result")
        return result


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
