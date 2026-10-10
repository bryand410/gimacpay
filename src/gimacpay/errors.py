"""Exceptions raised by :mod:`gimacpay`.

The hierarchy exists to make one distinction impossible to ignore: the
difference between *a payment that was rejected* and *a payment whose state is
unknown*.

The GIMACPay specification is explicit about this, in the description of
``/payment/send``::

    For all other responses codes, participants should keep the payment in
    PENDING state and perform a payment inquiry to GET the state. Participants
    should not guess the state if it's not given by GIMACPay.

Every exception below therefore answers one question: *do I know what happened
to the money?* If the answer is no, you get a
:class:`PaymentStateUnknown` -- never a success, never a failure.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "GimacPayError",
    "GimacPayConfigError",
    "GimacPayTransportError",
    "GimacPayAuthError",
    "GimacPayForbiddenError",
    "PaymentRejected",
    "PaymentStateUnknown",
    "GimacPayProtocolError",
]


class GimacPayError(Exception):
    """Base class for every error raised by this library."""


class GimacPayConfigError(GimacPayError):
    """The client was built with something missing or unusable.

    Raised before any network call, so a misconfiguration never reaches
    GIMACPay and never moves money.
    """


class GimacPayTransportError(GimacPayError):
    """The request never completed: DNS, TCP, TLS, or a timeout.

    This says nothing about whether the payment was accepted. Treat it exactly
    like :class:`PaymentStateUnknown` if a payment was in flight.
    """

    def __init__(self, message: str, *, original: BaseException | None = None) -> None:
        super().__init__(message)
        self.original = original


class _HttpError(GimacPayError):
    """An HTTP response carrying the spec's ``error`` / ``error_description`` pair."""

    def __init__(self, status: int, error: str, error_description: str) -> None:
        super().__init__(f"HTTP {status}: {error} - {error_description}")
        self.status = status
        self.error = error
        self.error_description = error_description

    @classmethod
    def from_body(cls, status: int, body: Any) -> _HttpError:
        """Build the right subclass from a decoded error body."""
        error = ""
        description = ""
        if isinstance(body, dict):
            error = str(body.get("error", "") or "")
            description = str(body.get("error_description", "") or "")
        elif body is not None:
            description = str(body)

        if status == 401:
            return GimacPayAuthError(status, error, description)
        if status == 403:
            return GimacPayForbiddenError(status, error, description)
        return PaymentRejected(status, error, description)


class GimacPayAuthError(_HttpError):
    """HTTP 401 -- the access token is missing, invalid, or expired.

    Recoverable: :class:`~gimacpay.client.GimacPayClient` refreshes the token
    once and retries before raising this.
    """


class GimacPayForbiddenError(_HttpError):
    """HTTP 403 -- the source IP is not authorised on GIMACPay's server.

    The specification is specific about the cause: *"Check if the source IP
    address is authorized on GIMACPay's server."* This is an infrastructure
    problem on your side, not a credential problem. Retrying will not help;
    contact GIMAC.
    """


class PaymentRejected(_HttpError):
    """HTTP 400 -- the payment was rejected and the reason is known.

    The spec puts the reason in ``error_description``. Example from the
    specification itself: ``Wallet<34JDJFKDKJDF> Not Found``.

    This is a *definite* outcome. The money did not move.
    """


class PaymentStateUnknown(GimacPayError):
    """The payment is in an indeterminate state. **Do not guess.**

    Raised when GIMACPay answers with a status code the specification does not
    define -- which includes a 200 whose body cannot be parsed. The spec covers
    exactly this case::

        For all other responses codes, participants should keep the payment in
        PENDING state and perform a payment inquiry to GET the state.

    The only correct reaction is to call :meth:`GimacPayClient.inquiry` with the
    ``issuertrxref`` you sent, and repeat until the state is terminal. Marking
    the payment as failed here is how double debits and orphaned transactions
    happen.

    Attributes:
        issuertrxref: The reference of the payment whose state is unknown.
        status: The HTTP status code received, if there was one.
        body: The raw response body, so the caller can log it.
    """

    def __init__(
        self,
        issuertrxref: str,
        *,
        status: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(
            f"state of payment {issuertrxref!r} is unknown "
            f"(HTTP {status if status is not None else 'n/a'}); "
            "keep it PENDING and call inquiry() until the state is terminal"
        )
        self.issuertrxref = issuertrxref
        self.status = status
        self.body = body


class GimacPayProtocolError(GimacPayError):
    """GIMACPay answered with something that is not a valid ``Payment``.

    Distinct from :class:`PaymentStateUnknown`: here we *did* get a 200 and a
    decodable body, but the body is missing fields the specification requires.
    That is a bug on one side of the wire, and it should be reported rather
    than silently coerced.
    """
