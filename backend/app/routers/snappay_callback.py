"""SnappPay onboarding callback — a reachability stub, NOT a payment handler.

SnappPay's onboarding checklist requires the merchant callback URL to be
reachable *before* the provider registers the merchant and issues protocol
details or credentials. The academy article
(https://academy.snapppay.ir/2026/03/18/...) says only that the callback URL
must be active on a real HTTPS host; it does **not** specify the callback
transport, payload shape, signature scheme or settlement flow. This deployment
has received no SnappPay credentials and no protocol documentation.

This router therefore exposes the fixed, registered URL
``/api/v1/commerce/snappay/callback`` purely so the onboarding probe sees an
HTTP-reachable endpoint:

* ``GET``  returns a neutral "route active" health document;
* ``POST`` returns a neutral ``202`` acknowledgement.

Hard guarantees (pinned by ``tests/test_snappay_callback.py``):

* **No state mutation.** No database session is opened; nothing is read from or
  written to the store.
* **No success assertion.** Neither method ever claims a payment succeeded or
  failed — the POST is explicitly ``pending``.
* **No callback body/query logging.** The request body and query string are
  never read, parsed or logged, so nothing a caller sends can leak.
* **No payment evidence acceptance.** No caller field is parsed, echoed or
  persisted, and no provider call is made. SnappPay stays disabled and
  unintegrated — this is not a gateway.

This is deliberately *not* built on the DigiPay adapter and does not touch its
settlement code. When SnappPay issues the real protocol and credentials, a
separate, reviewed adapter must replace this stub; do not grow payment logic in
this module.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.routers.auth import limiter

router = APIRouter(prefix="/api/v1/commerce/snappay", tags=["commerce-payments"])

# The exact, fixed path SnappPay is asked to register (see the module docstring).
# Composed with the deployment origin it yields
# ``https://spaghettiprints.ir/api/v1/commerce/snappay/callback``.
CALLBACK_PATH = "/api/v1/commerce/snappay/callback"

# The stub never holds per-request state, so its answers must never be cached
# and must never be used as a referrer.
RESPONSE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@router.get("/callback")
@limiter.limit("120/minute")
def snappay_callback_reachability(request: Request) -> JSONResponse:
    """Prove the fixed callback route is active. No state, no secrets.

    The document states plainly that no payment is being processed, so a probe
    cannot mistake reachability for a working gateway.
    """
    return JSONResponse(
        status_code=200,
        content={
            "provider": "snappay",
            "status": "reachable",
            "callback_path": CALLBACK_PATH,
            "payment_enabled": False,
        },
        headers=dict(RESPONSE_HEADERS),
    )


@router.post("/callback")
@limiter.limit("120/minute")
def snappay_callback_acknowledge(request: Request) -> JSONResponse:
    """Acknowledge a callback without reading, verifying or acting on it.

    The body and query are intentionally never parsed: there is no signature
    scheme, no payload contract and no invoice to settle, so any field a caller
    sends is meaningless here. The response is a neutral ``202`` ("received,
    pending") — never a success — so nothing reaching this stub can be read as
    a settled payment.
    """
    return JSONResponse(
        status_code=202,
        content={
            "provider": "snappay",
            "status": "pending",
            "payment_enabled": False,
        },
        headers=dict(RESPONSE_HEADERS),
    )
