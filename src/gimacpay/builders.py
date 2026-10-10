"""Request builders -- one function per ``intent`` you are likely to need.

Why these exist: ``/payment/send`` accepts a ``oneOf`` of 24 schemas selected
by the ``intent`` field. Building that dictionary by hand means remembering a
discriminator string and a set of required fields, in a system where a typo
moves money. These helpers set ``intent`` themselves, validate the amount, and
normalise phone numbers.

Every builder returns a plain ``dict``. Nothing here is opaque: you can always
print the result, amend it, and pass it to
:meth:`~gimacpay.client.GimacPayClient.send_payment` yourself.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .intents import Intent
from .money import CURRENCY_XAF, normalise_phone, validate_amount

__all__ = [
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
]


def _base(intent: str, issuertrxref: str, **rest: Any) -> dict[str, Any]:
    """Assemble a request, dropping ``None`` values.

    ``issuertrxref`` is your own reference and the only handle you have on the
    payment afterwards -- :meth:`GimacPayClient.await_state` looks it up. It is
    required on every request, so it is required here.
    """
    if not issuertrxref:
        raise ValueError(
            "issuertrxref is required: it is the only reference you can use to "
            "inquire about this payment later"
        )
    payload: dict[str, Any] = {"intent": intent, "issuertrxref": str(issuertrxref)}
    payload.update({k: v for k, v in rest.items() if v is not None})
    return payload


def _phone(value: str | None, field: str) -> str | None:
    """Normalise a phone number, refusing to guess a missing country code."""
    if value is None:
        return None
    try:
        return normalise_phone(value)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc


def wallet_to_wallet(
    *,
    amount: object,
    walletsource: str,
    walletdestination: str,
    tomember: str,
    issuertrxref: str,
    description: str | None = None,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Move money from one mobile wallet to another (``mobile_transfer``)."""
    return _base(
        Intent.MOBILE_TRANSFER,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletsource=_phone(walletsource, "walletsource"),
        walletdestination=_phone(walletdestination, "walletdestination"),
        tomember=str(tomember),
        description=description,
    )


def merchant_purchase(
    *,
    amount: object,
    walletsource: str,
    walletdestination: str,
    tomember: str,
    issuertrxref: str,
    description: str | None = None,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Pay a merchant from a wallet (``merchant_purchase``).

    ``walletdestination`` is the merchant's wallet identifier, which in the
    specification's example is a short numeric code rather than a phone number
    -- so it is passed through untouched.
    """
    return _base(
        Intent.MERCHANT_PURCHASE,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletsource=_phone(walletsource, "walletsource"),
        walletdestination=str(walletdestination),
        tomember=str(tomember),
        description=description,
    )


def request_to_pay(
    *,
    amount: object,
    walletsource: str,
    walletdestination: str,
    tomember: str,
    issuertrxref: str,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Ask a payer to pay you (``request_to_pay``).

    Note the direction: ``walletsource`` is *your* identifier and
    ``walletdestination`` is the person being asked to pay.
    """
    return _base(
        Intent.REQUEST_TO_PAY,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletsource=str(walletsource),
        walletdestination=_phone(walletdestination, "walletdestination"),
        tomember=str(tomember),
    )


def cash_in(
    *,
    amount: object,
    walletdestination: str,
    tomember: str,
    teller: str,
    pointofservice: str,
    issuertrxref: str,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Credit a wallet with cash handed over at a counter (``cash_in``)."""
    return _base(
        Intent.CASH_IN,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletdestination=_phone(walletdestination, "walletdestination"),
        tomember=str(tomember),
        teller=str(teller),
        pointofservice=str(pointofservice),
    )


def cash_deposit(
    *,
    amount: object,
    walletdestination: str,
    tomember: str,
    issuertrxref: str,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Deposit cash into a wallet (``cash_deposit``)."""
    return _base(
        Intent.CASH_DEPOSIT,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletdestination=_phone(walletdestination, "walletdestination"),
        tomember=str(tomember),
    )


def cash_out(
    *,
    amount: object,
    walletsource: str,
    issuertrxref: str,
    validityduration: int,
    receiver_firstname: str,
    receiver_secondname: str,
    merchantid: str | None = None,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Withdraw cash from a wallet (``cash_out``).

    ``validityduration`` is in seconds: how long the withdrawal voucher stays
    usable. The specification's examples use 4500.
    """
    receiver: dict[str, Any] = {
        "firstname": receiver_firstname,
        "secondname": receiver_secondname,
    }
    if merchantid is not None:
        receiver["merchantid"] = str(merchantid)

    return _base(
        Intent.CASH_OUT,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletsource=str(walletsource),
        validityduration=int(validityduration),
        receivercustomerdata=[receiver],
    )


def bill_inquiry(
    *,
    walletsource: str,
    tomember: str,
    issuertrxref: str,
    query_ref: str,
    contract_ref: str,
    service_ref: str,
) -> dict[str, Any]:
    """Ask a biller what is owed, before paying (``bill_inquiry``).

    No ``amount``: the point of an inquiry is to discover it.
    """
    return _base(
        Intent.BILL_INQUIRY,
        issuertrxref,
        tomember=str(tomember),
        walletsource=str(walletsource),
        billInquiryData={
            "queryRef": str(query_ref),
            "contractRef": str(contract_ref),
            "serviceRef": str(service_ref),
        },
    )


def bill_payment(
    *,
    amount: object,
    walletsource: str,
    tomember: str,
    service: str,
    bill_refs: Sequence[str],
    issuertrxref: str,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Pay one or more bills identified by reference (``bill_payment``).

    The ``billRef`` values come from :func:`bill_inquiry` -- the specification's
    example is an ENEO reference of the form
    ``S-112-950-ENEO-10039-<hash>``.
    """
    refs: list[str] = [str(ref) for ref in bill_refs]
    if not refs:
        raise ValueError("bill_refs must contain at least one bill reference")

    return _base(
        Intent.BILL_PAYMENT,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        walletsource=str(walletsource),
        tomember=str(tomember),
        service=str(service),
        billList=[{"billRef": ref} for ref in refs],
    )


def mobile_reload(
    *,
    amount: object,
    sendermobile: str,
    receivermobile: str,
    tomember: str,
    issuertrxref: str,
    currency: str = CURRENCY_XAF,
) -> dict[str, Any]:
    """Buy airtime for a number (``mobile_reload``)."""
    return _base(
        Intent.MOBILE_RELOAD,
        issuertrxref,
        amount=validate_amount(amount),
        currency=currency,
        sendermobile=_phone(sendermobile, "sendermobile"),
        receivermobile=_phone(receivermobile, "receivermobile"),
        tomember=str(tomember),
    )


def account_inquiry(
    *,
    tomember: str,
    issuertrxref: str,
    walletdestination: str | None = None,
    dstaccount: str | None = None,
    dstaccount_type: str = "ACCOUNT",
) -> dict[str, Any]:
    """Resolve a wallet or account before sending to it (``account_inquiry``).

    Pass exactly one of ``walletdestination`` or ``dstaccount``. The
    specification has two worked examples for this intent, one for each.
    """
    if (walletdestination is None) == (dstaccount is None):
        raise ValueError("pass exactly one of walletdestination or dstaccount")

    payload = _base(Intent.ACCOUNT_INQUIRY, issuertrxref, tomember=str(tomember))
    if walletdestination is not None:
        payload["walletdestination"] = _phone(walletdestination, "walletdestination")
    else:
        payload["dstaccounts"] = [{"iden": str(dstaccount), "type": dstaccount_type}]
    return payload


def build(intent: str, /, **fields: Any) -> dict[str, Any]:
    """Build a request for any intent, including ones this module does not cover.

    Use this for the eight remittance intents and anything GIMACPay adds later.
    It validates the amount if one is supplied, but it does not know the
    required fields for an intent it has no builder for -- so it cannot protect
    you from an incomplete request. Prefer the named builders.

    Example::

        build("inc_acc_remit",
              issuertrxref="R-1", amount=750, tomember="10029",
              sendermobile="+336575950505",
              dstaccounts=[{"iden": "100291525478502", "type": "ACCOUNT"}])
    """
    if not intent:
        raise ValueError("intent is required")
    if "amount" in fields:
        fields["amount"] = validate_amount(fields["amount"])
    fields.setdefault("currency", CURRENCY_XAF)
    return _base(intent, fields.pop("issuertrxref", ""), **fields)
