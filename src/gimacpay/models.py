"""Typed views of the objects GIMACPay returns.

These are plain :mod:`dataclasses`, not a validation framework. The SDK keeps
zero runtime dependencies (see ``SECURITY.md``), so parsing is explicit and
tolerant: unknown fields are preserved in :attr:`Payment.raw` rather than
dropped, because GIMACPay may add fields and a client that silently discards
them is a client that lies about what it received.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import GimacPayProtocolError

__all__ = [
    "PaymentState",
    "TERMINAL_STATES",
    "AccountInfo",
    "CustomerData",
    "Bill",
    "Payment",
]


class PaymentState:
    """The values of ``Payment.state``, as defined by the specification.

    ``PENDING`` is the only non-terminal state. That is the whole point of the
    class: the specification requires a participant to keep a payment PENDING
    and inquire until it leaves that state, and never to guess.
    """

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


#: States after which no further change is possible, so inquiry can stop.
TERMINAL_STATES = frozenset(
    {
        PaymentState.ACCEPTED,
        PaymentState.REJECTED,
        PaymentState.REVERSED,
        PaymentState.EXPIRED,
        PaymentState.CANCELLED,
    }
)


@dataclass(frozen=True)
class AccountInfo:
    """An account, card or wallet identified by ``iden`` and ``type``.

    ``type`` is one of ``ACCOUNT``, ``CARD``, ``WALLET`` in the specification's
    examples.
    """

    iden: str
    type: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AccountInfo:
        return cls(iden=str(data.get("iden", "")), type=_opt_str(data.get("type")))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"iden": self.iden}
        if self.type is not None:
            out["type"] = self.type
        return out


@dataclass(frozen=True)
class CustomerData:
    """Sender or receiver identity attached to a remittance.

    The specification's examples carry ``firstname``, ``secondname`` and
    optionally ``idnumber``, ``idtype``, ``merchantid``. The field set is open,
    so anything else is kept in :attr:`extra`.
    """

    firstname: str | None = None
    secondname: str | None = None
    idnumber: str | None = None
    idtype: str | None = None
    merchantid: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    _KNOWN = ("firstname", "secondname", "idnumber", "idtype", "merchantid")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CustomerData:
        known = {k: _opt_str(data.get(k)) for k in cls._KNOWN}
        extra = {k: v for k, v in data.items() if k not in cls._KNOWN}
        return cls(extra=extra, **known)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.extra)
        for key in self._KNOWN:
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True)
class Bill:
    """A bill returned by a ``bill_inquiry``.

    ``status`` is ``U`` (unpaid) or ``P`` (paid), per the specification's enum.
    """

    billRef: str | None = None
    createtime: str | None = None
    dueTime: str | None = None
    dueAmount: float | None = None
    currency: str | None = None
    status: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Bill:
        return cls(
            billRef=_opt_str(data.get("billRef")),
            createtime=_opt_str(data.get("createtime")),
            dueTime=_opt_str(data.get("dueTime")),
            dueAmount=_opt_float(data.get("dueAmount")),
            currency=_opt_str(data.get("currency")),
            status=_opt_str(data.get("status")),
        )


@dataclass(frozen=True)
class Payment:
    """A payment as GIMACPay describes it.

    Attributes:
        issuertrxref: Your own reference. **This is the field you use to inquire
            about the payment later**, so it must be unique and you must keep it.
        state: One of the :class:`PaymentState` values.
        amount: Amount in the minor unit of :attr:`currency`.
        intent: The discriminator that says what kind of payment this is.
        rejectmessage: Present when the payment was rejected.
        raw: The decoded response, untouched. Always available, so nothing the
            server sent is lost even if this version of the SDK does not model it.
    """

    issuertrxref: str | None = None
    acquirertrxref: str | None = None
    state: str | None = None
    intent: str | None = None
    amount: float | None = None
    currency: str | None = None
    tomember: str | None = None
    frommember: str | None = None
    description: str | None = None
    rejectmessage: str | None = None
    vouchercode: str | None = None
    pointofservice: str | None = None
    teller: str | None = None
    createtime: str | None = None
    dstaccounts: list[AccountInfo] = field(default_factory=list)
    srcaccounts: list[AccountInfo] = field(default_factory=list)
    sendercustomerdata: CustomerData | None = None
    receivercustomerdata: CustomerData | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Payment:
        """Parse one payment.

        Raises:
            GimacPayProtocolError: if *data* is not a mapping, or carries no
                ``issuertrxref``. Both mean the response cannot be acted on,
                and guessing would be worse than failing.
        """
        if not isinstance(data, Mapping):
            raise GimacPayProtocolError(f"expected a payment object, got {type(data).__name__}")

        issuertrxref = _opt_str(data.get("issuertrxref"))
        if not issuertrxref:
            raise GimacPayProtocolError(
                "payment object has no 'issuertrxref'; cannot be matched to a "
                f"request. Received keys: {sorted(data.keys())}"
            )

        return cls(
            issuertrxref=issuertrxref,
            acquirertrxref=_opt_str(data.get("acquirertrxref")),
            state=_opt_str(data.get("state")),
            intent=_opt_str(data.get("intent")),
            amount=_opt_float(data.get("amount")),
            currency=_opt_str(data.get("currency")),
            tomember=_opt_str(data.get("tomember")),
            frommember=_opt_str(data.get("frommember")),
            description=_opt_str(data.get("description")),
            rejectmessage=_opt_str(data.get("rejectmessage")),
            vouchercode=_opt_str(data.get("vouchercode")),
            pointofservice=_opt_str(data.get("pointofservice")),
            teller=_opt_str(data.get("teller")),
            createtime=_opt_str(data.get("createtime")),
            dstaccounts=_accounts(data.get("dstaccounts")),
            srcaccounts=_accounts(data.get("srcaccounts")),
            sendercustomerdata=_customer(data.get("sendercustomerdata")),
            receivercustomerdata=_customer(data.get("receivercustomerdata")),
            raw=dict(data),
        )

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #

    @property
    def is_terminal(self) -> bool:
        """Whether the payment can no longer change.

        A ``None`` or unrecognised state is **not** terminal -- the spec's rule
        is that an unknown state means keep inquiring, not give up.
        """
        return self.state in TERMINAL_STATES

    @property
    def is_accepted(self) -> bool:
        return self.state == PaymentState.ACCEPTED

    @property
    def is_rejected(self) -> bool:
        return self.state == PaymentState.REJECTED

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Payment {self.issuertrxref} {self.state} {self.amount} {self.currency}>"


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #


def _opt_str(value: Any) -> str | None:
    """Coerce to ``str``, mapping ``None`` to ``None``.

    The specification is not consistent about types: ``issuertrxref`` is
    declared ``integer`` in ``Payment`` but every example sends a string, and
    ``iden`` appears both quoted and unquoted. Coercing to ``str`` at the edge
    means callers compare like with like.
    """
    if value is None:
        return None
    return str(value)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _accounts(value: Any) -> list[AccountInfo]:
    if not isinstance(value, list):
        return []
    return [AccountInfo.from_dict(item) for item in value if isinstance(item, Mapping)]


def _customer(value: Any) -> CustomerData | None:
    # The spec's examples send this as a one-element array, but the schema says
    # object. Accept both rather than fail on a discrepancy that is not ours.
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, Mapping):
        return CustomerData.from_dict(value)
    return None
