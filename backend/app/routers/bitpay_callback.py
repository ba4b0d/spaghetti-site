"""BitPay gateway GET callback — untrusted query, server-side verify/settlement.

BitPay redirects the payer's browser (a plain ``GET``, per gateway v2.2) to the
fixed path bundled at initiation::

    GET /api/v1/commerce/bitpay/callback?trans_id=<n>&id_get=<n>

The query carries only ``trans_id`` and ``id_get`` — **no** signature and **no**
invoice token — so it is treated purely as a hint:

* the attempt is resolved only through the persisted ``id_get`` we received from
  ``gateway-send`` at initiation (stored as ``tracking_code``);
* the query's ``trans_id`` is never trusted; the invoice is settled only after a
  server-to-server ``gateway-result-second`` verify confirms success with a
  matching ``amount`` **and** ``factorId``;
* ``settle_verified_payment`` then re-binds the attempt to the invoice's current
  revision + amount, so a late/foreign success is preserved for staff instead of
  applied.

The response is always a redirect to a public, non-secret confirmation page
(``/pay/result?payment=...``); the private bearer token is never involved and so
is never echoed into a Location header. The callback *query string* is redacted
from both the nginx access log (``frontend/nginx.conf``) and uvicorn's access
log (``app/log_redaction.py``), so ``trans_id``/``id_get`` never land in a log.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import limiter
from app.services import bitpay
from app.services import commerce as commerce_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/commerce/bitpay", tags=["commerce-payments"])

# The exact, fixed path the gateway callbacks (see the module docstring). Kept
# alongside the adapter's own constant so both agree.
CALLBACK_PATH = bitpay.CALLBACK_PATH

RESULT_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _result_redirect(outcome: str) -> RedirectResponse:
    """Send the browser to a public result page; never include a token."""
    try:
        base = commerce_service.public_site_origin()
        location = f"{base}{commerce_service.PAYMENT_RESULT_PATH}?payment={outcome}"
    except commerce_service.CommerceConfigError:
        # Misconfigured deploy: a relative redirect still works and leaks nothing.
        location = f"{commerce_service.PAYMENT_RESULT_PATH}?payment={outcome}"
    return RedirectResponse(url=location, status_code=303, headers=dict(RESULT_HEADERS))


@router.get("/callback")
@limiter.limit("120/minute")
def bitpay_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    trans_id: str | None = Query(default=None),
    id_get: str | None = Query(default=None),
    factor_id: str | None = Query(default=None, alias="factorId"),
    db: Session = Depends(get_db),
    client=Depends(bitpay.client_dependency),
):
    """Consume BitPay's GET callback; settle only after server-side verify.

    The query is read strictly as strings and re-validated inside the service;
    ``factorId`` is accepted as an optional hint but never required or trusted
    (BitPay does not echo it on the GET callback).
    """
    if client is None:
        try:
            client = bitpay.get_client()
        except bitpay.BitPayConfigError:
            # Cannot verify → never claim success.
            return _result_redirect("failed")

    try:
        outcome = commerce_service.handle_bitpay_callback(
            db,
            client,
            trans_id=trans_id,
            id_get=id_get,
            factor_id=factor_id,
            background_tasks=background_tasks,
        )
    except commerce_service.CommerceReconciliationRequiredError:
        # Provider genuinely confirmed payment but it could not be settled
        # against the current invoice (stale revision/amount, or revoked). The
        # attempt kept its verified evidence and is queued for staff; send the
        # customer to a neutral pending page and never claim paid or 500.
        outcome = "pending"
    except commerce_service.CommerceConfigError:
        # Misconfigured deploy: never claim success.
        outcome = "failed"
    except Exception:  # noqa: BLE001 - a gateway callback must ALWAYS redirect
        logger.exception("bitpay callback handling raised; returning neutral result")
        outcome = "pending"
    return _result_redirect(outcome)
