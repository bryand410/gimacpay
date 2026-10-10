"""The 23 ``intent`` values defined by the GIMACPay specification.

``/payment/send`` accepts a ``oneOf`` of 24 request schemas. Which one applies
is decided by a single field, ``intent`` -- so ``intent`` is the discriminator,
and getting it wrong is the most likely way to send the wrong kind of payment.

This module exists so that the discriminator is never a bare string literal in
caller code, and so the *required* fields of each intent are declared next to
the intent itself.

Source: ``docs/reference/gimac-api-1.10.yaml``, ``/payment/send`` and
``components.schemas.Payment.intent``.
"""

from __future__ import annotations

__all__ = [
    "Intent",
    "REQUIRED_FIELDS",
    "ALL_INTENTS",
    "TRANSFER_INTENTS",
    "CASH_INTENTS",
    "BILL_INTENTS",
    "required_fields",
    "is_known",
]


class Intent:
    """The ``intent`` discriminator values, as constants.

    Use these instead of string literals::

        from gimacpay import Intent, wallet_to_wallet

        payment = client.send_payment(
            wallet_to_wallet(
                amount=500,
                walletsource="237699947943",
                walletdestination="2356789009",
                tomember="22001",
                issuertrxref="ORD-2026-0001",
            )
        )

    ``Intent`` is a namespace, not an enum, on purpose: the wire format is a
    plain string, and an ``enum.Enum`` would invite ``.value`` mistakes at the
    boundary.
    """

    # --- transfers between wallets, accounts and cards -------------------- #
    MOBILE_TRANSFER = "mobile_transfer"
    WALLET_TO_ACCOUNT = "wallet_to_account"
    ACCOUNT_TO_WALLET = "account_to_wallet"
    ACCOUNT_TRANSFER = "account_transfer"

    # --- merchant and voucher --------------------------------------------- #
    MERCHANT_PURCHASE = "merchant_purchase"
    PURCHASE_VOUCHER = "purchase_voucher"

    # --- bills -------------------------------------------------------------#
    BILL_INQUIRY = "bill_inquiry"
    BILL_PAYMENT = "bill_payment"

    # --- cash and cards ---------------------------------------------------- #
    CARDLESS_WITHDRAWAL = "cardless_withdrawal"
    CASH_OUT = "cash_out"
    CASH_DEPOSIT = "cash_deposit"
    CASH_IN = "cash_in"
    PP_RELOAD = "pp_reload"
    MOBILE_RELOAD = "mobile_reload"

    # --- remittances: direction x destination ------------------------------ #
    INC_WAL_REMIT = "inc_wal_remit"
    INC_ACC_REMIT = "inc_acc_remit"
    INC_CARD_REMIT = "inc_card_remit"
    INC_VOUCHER_REMIT = "inc_voucher_remit"
    OUTG_WAL_REMIT = "outg_wal_remit"
    OUTG_ACC_REMIT = "outg_acc_remit"
    OUTG_CARD_REMIT = "outg_card_remit"
    OUTG_VOUCHER_REMIT = "outg_voucher_remit"

    # --- pull and lookup --------------------------------------------------- #
    REQUEST_TO_PAY = "request_to_pay"
    ACCOUNT_INQUIRY = "account_inquiry"


#: Every value the specification defines for ``intent``.
#:
#: The spec's ``Payment.intent`` enum lists ``wallet_to_account`` twice and
#: omits ``outg_wal_remit`` from the request ``oneOf`` while listing it in the
#: enum. This set is the union, de-duplicated.
ALL_INTENTS: frozenset[str] = frozenset(
    value for name, value in vars(Intent).items() if not name.startswith("_")
)

#: Intents whose money ends up in a wallet, an account or a card.
TRANSFER_INTENTS: frozenset[str] = frozenset(
    {
        Intent.MOBILE_TRANSFER,
        Intent.WALLET_TO_ACCOUNT,
        Intent.ACCOUNT_TO_WALLET,
        Intent.ACCOUNT_TRANSFER,
        Intent.INC_WAL_REMIT,
        Intent.INC_ACC_REMIT,
        Intent.INC_CARD_REMIT,
        Intent.OUTG_WAL_REMIT,
        Intent.OUTG_ACC_REMIT,
        Intent.OUTG_CARD_REMIT,
    }
)

#: Intents settled in cash or at a point of service.
CASH_INTENTS: frozenset[str] = frozenset(
    {
        Intent.CARDLESS_WITHDRAWAL,
        Intent.CASH_OUT,
        Intent.CASH_DEPOSIT,
        Intent.CASH_IN,
        Intent.INC_VOUCHER_REMIT,
        Intent.OUTG_VOUCHER_REMIT,
    }
)

#: Intents that read or settle a bill.
BILL_INTENTS: frozenset[str] = frozenset({Intent.BILL_INQUIRY, Intent.BILL_PAYMENT})


#: Fields each intent must carry, derived from the worked examples in the
#: specification (``components.examples``).
#:
#: Only fields present in *every* example of a given intent are listed, so this
#: is a lower bound: it is safe to require, and it does not pretend to be the
#: full schema. The examples are the only normative sample payloads the spec
#: publishes, which is why they are the source here.
#:
#: Grouped by shape rather than listed one by one: the specification's 24
#: request schemas are mostly variations on five or six field sets, and seeing
#: that is more useful than reading 24 near-identical lines.
_CORE = ("issuertrxref", "amount", "currency")

# Wallet to wallet: a source, a destination, and the receiving member code.
_WALLET_PAIR = (*_CORE, "walletsource", "walletdestination", "tomember")
_WALLET_TO_DST = (*_CORE, "walletsource", "tomember", "dstaccounts")
_DST_TO_WALLET = (*_CORE, "walletdestination", "tomember", "srcaccounts")

# Remittances: the sender is identified by mobile number instead of a wallet id.
_REMIT_TO_WALLET = (*_CORE, "sendermobile", "walletdestination", "tomember")
_REMIT_TO_DST = (*_CORE, "sendermobile", "dstaccounts", "tomember")
_REMIT_VOUCHER = (*_CORE, "sendermobile", "validityduration")

# Cash at a counter or an agent.
_CASH_TO_WALLET = (*_CORE, "walletdestination", "tomember")

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    Intent.MOBILE_TRANSFER: _WALLET_PAIR,
    Intent.MERCHANT_PURCHASE: _WALLET_PAIR,
    Intent.WALLET_TO_ACCOUNT: _WALLET_TO_DST,
    Intent.ACCOUNT_TO_WALLET: _DST_TO_WALLET,
    Intent.ACCOUNT_TRANSFER: (*_CORE, "tomember", "dstaccounts", "srcaccounts"),
    Intent.BILL_INQUIRY: ("issuertrxref", "tomember", "walletsource", "billInquiryData"),
    Intent.BILL_PAYMENT: (*_CORE, "walletsource", "tomember", "service", "billList"),
    Intent.CARDLESS_WITHDRAWAL: (
        *_CORE,
        "sendermobile",
        "receivermobile",
        "validityduration",
    ),
    Intent.CASH_OUT: (*_CORE, "walletsource", "validityduration", "receivercustomerdata"),
    Intent.CASH_DEPOSIT: _CASH_TO_WALLET,
    Intent.CASH_IN: (*_CASH_TO_WALLET, "teller", "pointofservice"),
    Intent.PP_RELOAD: (*_CORE, "walletsource", "dstaccounts", "tomember"),
    Intent.MOBILE_RELOAD: (*_CORE, "sendermobile", "receivermobile", "tomember"),
    Intent.INC_WAL_REMIT: _REMIT_TO_WALLET,
    Intent.INC_ACC_REMIT: _REMIT_TO_DST,
    Intent.INC_CARD_REMIT: _REMIT_TO_DST,
    Intent.INC_VOUCHER_REMIT: _REMIT_VOUCHER,
    # The specification has no worked example for outg_wal_remit: it appears in
    # the Payment.intent enum but not in the examples block. This entry is
    # derived from its incoming counterpart, inc_wal_remit, so treat it as a
    # lower bound rather than a contract.
    Intent.OUTG_WAL_REMIT: _REMIT_TO_WALLET,
    Intent.OUTG_ACC_REMIT: _REMIT_TO_DST,
    Intent.OUTG_CARD_REMIT: _REMIT_TO_DST,
    Intent.OUTG_VOUCHER_REMIT: _REMIT_VOUCHER,
    Intent.PURCHASE_VOUCHER: (*_CORE, "walletsource", "validityduration"),
    Intent.REQUEST_TO_PAY: (*_CORE, "walletdestination", "walletsource", "tomember"),
    Intent.ACCOUNT_INQUIRY: ("issuertrxref", "tomember"),
}


def required_fields(intent: str) -> tuple[str, ...]:
    """Return the fields the specification's examples always carry for *intent*.

    Unknown intents return an empty tuple rather than raising: the SDK is
    built against spec version 1.10, and GIMACPay may add intents without
    telling us. Refusing to send a payment because *our* table is stale would
    be the wrong failure.
    """
    return REQUIRED_FIELDS.get(intent, ())


def is_known(intent: str) -> bool:
    """Whether *intent* appears in spec version 1.10."""
    return intent in ALL_INTENTS
