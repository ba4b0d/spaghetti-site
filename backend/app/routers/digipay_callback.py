"""DigiPay UPG callback — untrusted form POST, server-side verification/settlement.

DigiPay redirects the customer's browser here after the gateway step. The POST
carries ``result``, ``amount``, ``providerId``, ``trackingCode`` and ``type`` but
*no* signature and *no* invoice token, so it is treated purely as a hint:

* the attempt is resolved only through the unique ``providerId``;
* the callback amount/type are compared with the stored attempt;
* the invoice is settled only after a server-to-server ``/purchases/verify``
  confirms success.

The response is always a redirect to a public, non-secret confirmation page
(``/pay/result?payment=...``); the private bearer token is never persisted and
so is never echoed into a Location header or the access log.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import limiter
from app.services import commerce as commerce_service
from app.services import digipay

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/commerce/digipay", tags=["commerce-payments"])

RESULT_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _result_redirect(outcome: str) -> RedirectResponse:
    """Send the browser to a public result page; never include the token."""
    try:
        base = commerce_service.public_site_origin()
        location = f"{base}{commerce_service.PAYMENT_RESULT_PATH}?payment={outcome}"
    except commerce_service.CommerceConfigError:
        # Misconfigured deploy: a relative redirect still works and leaks nothing.
        location = f"{commerce_service.PAYMENT_RESULT_PATH}?payment={outcome}"
    return RedirectResponse(url=location, status_code=303, headers=dict(RESULT_HEADERS))


@router.post("/callback")
@limiter.limit("120/minute")
def digipay_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    provider_id: str | None = Form(default=None, alias="providerId"),
    amount: str | None = Form(default=None),
    tracking_code: str | None = Form(default=None, alias="trackingCode"),
    type_value: str | None = Form(default=None, alias="type"),
    result_value: str | None = Form(default=None, alias="result"),
    db: Session = Depends(get_db),
    client=Depends(digipay.client_dependency),
):
    """Consume DigiPay's form POST; settle only after server-side verify."""
    if client is None:
        try:
            client = digipay.get_client()
        except digipay.DigiPayConfigError:
            # Cannot verify → never claim success.
            return _result_redirect("failed")

    try:
        outcome = commerce_service.handle_digipay_callback(
            db,
            client,
            provider_id=provider_id,
            amount=amount,
            tracking_code=tracking_code,
            type_value=type_value,
            result_value=result_value,
            background_tasks=background_tasks,
        )
    except commerce_service.CommerceReconciliationRequiredError:
        # Provider genuinely confirmed payment but it could not be settled
        # against the current invoice (stale revision/amount, or revoked).
        # The attempt kept its verified evidence and is queued for staff; send
        # the customer to a neutral pending page and never claim paid or 500.
        outcome = "pending"
    except commerce_service.CommerceConfigError:
        # Misconfigured deploy: never claim success.
        outcome = "failed"
    except Exception:  # noqa: BLE001 - a gateway callback must ALWAYS redirect
        logger.exception("digipay callback handling raised; returning neutral result")
        outcome = "pending"
    return _result_redirect(outcome)
