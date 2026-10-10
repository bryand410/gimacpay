"""gimacpay -- a Python client for GIMACPAY, the CEMAC interbank payment network.

GIMACPAY is operated by GIMAC (Groupement Interbancaire Monétique de l'Afrique
Centrale) and connects 59 commercial banks, six national treasuries and the
mobile-money wallets of the six CEMAC member states -- Cameroun, Tchad,
République centrafricaine, Guinée équatoriale, Gabon and Congo. Since July 2026
it also carries the BEAC's common QR code, and since July 2026 it is connected
to PAPSS for continental cross-border settlement.

This library implements the participant API as published in
``GIMACPay Swagger for payments issuers`` version 1.8 (specification file
1.10).

Zero runtime dependencies. See ``SECURITY.md`` for why that is deliberate.

Quick start::

    from gimacpay import GimacPayClient, wallet_to_wallet

    client = GimacPayClient(
        base_url="https://.../stdendpointfacade/v1/external",
        client_id="...", client_secret="...",
        username="...", password="...",
        default_dial_code="237",
    )

    payment = client.send_and_resolve(
        wallet_to_wallet(
            amount=500,
            walletsource="237699947943",
            walletdestination="2356789009",
            tomember="22001",
            issuertrxref="ORD-2026-0001",
        )
    )
    print(payment.state)   # ACCEPTED, REJECTED, ... -- never a guess

The one rule this library is built around, taken from the specification's
description of ``/payment/send``::

    Participants should not guess the state if it's not given by GIMACPay.
"""

from __future__ import annotations

from .builders import (
    account_inquiry,
    bill_inquiry,
    bill_payment,
    build,
    cash_deposit,
    cash_in,
    cash_out,
    merchant_purchase,
    mobile_reload,
    request_to_pay,
    wallet_to_wallet,
)
from .client import REFERENCE_SERVER, GimacPayClient
from .errors import (
    GimacPayAuthError,
    GimacPayConfigError,
    GimacPayError,
    GimacPayForbiddenError,
    GimacPayProtocolError,
    GimacPayTransportError,
    PaymentRejected,
    PaymentStateUnknown,
)
from .intents import ALL_INTENTS, Intent, is_known, required_fields
from .models import TERMINAL_STATES, AccountInfo, Bill, CustomerData, Payment, PaymentState
from .money import CEMAC_DIAL_CODES, CURRENCY_XAF, normalise_phone, validate_amount

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # client
    "GimacPayClient",
    "REFERENCE_SERVER",
    # builders
    "wallet_to_wallet",
    "merchant_purchase",
    "request_to_pay",
    "cash_in",
    "cash_deposit",
    "cash_out",
    "bill_inquiry",
    "bill_payment",
    "mobile_reload",
    "account_inquiry",
    "build",
    # intents
    "Intent",
    "ALL_INTENTS",
    "is_known",
    "required_fields",
    # models
    "Payment",
    "PaymentState",
    "TERMINAL_STATES",
    "AccountInfo",
    "Bill",
    "CustomerData",
    # helpers
    "CURRENCY_XAF",
    "CEMAC_DIAL_CODES",
    "normalise_phone",
    "validate_amount",
    # errors
    "GimacPayError",
    "GimacPayConfigError",
    "GimacPayTransportError",
    "GimacPayAuthError",
    "GimacPayForbiddenError",
    "PaymentRejected",
    "PaymentStateUnknown",
    "GimacPayProtocolError",
]
