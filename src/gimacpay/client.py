"""The HTTP client.

Zero dependencies: everything below is :mod:`urllib` and :mod:`json` from the
standard library. For a payments client this is a security property, not a
style preference -- see ``SECURITY.md``.

The behaviour worth reading closely is :meth:`GimacPayClient.send_payment` and
:meth:`GimacPayClient.send_and_resolve`. They implement the one rule the
specification states in capitals:

    Participants should not guess the state if it's not given by GIMACPay.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from .errors import (
    GimacPayAuthError,
    GimacPayConfigError,
    GimacPayProtocolError,
    GimacPayTransportError,
    PaymentStateUnknown,
    _HttpError,
)
from .models import Payment
from .money import normalise_phone

__all__ = ["GimacPayClient", "REFERENCE_SERVER"]

#: The server URL published in the specification's ``servers`` block.
#:
#: It points at ``localhost`` because the specification ships inside GIMAC's
#: network: there is no public sandbox. In practice you replace this with the
#: endpoint GIMAC assigns your institution.
REFERENCE_SERVER = "http://localhost:8005/stdendpointfacade/v1/external"

#: Seconds subtracted from the token's advertised lifetime, so a token is
#: refreshed slightly before it expires rather than during a payment.
_TOKEN_SAFETY_MARGIN = 60.0

_DEFAULT_TIMEOUT = 30.0


class GimacPayClient:
    """A client for the GIMACPay participant API (specification version 1.10).

    Args:
        base_url: The ``.../external`` root GIMAC assigned you. Defaults to the
            specification's reference server, which is only reachable from
            inside GIMAC's network -- set this.
        client_id: OAuth 2.0 client identifier.
        client_secret: OAuth 2.0 client secret.
        username: Participant username for the password grant.
        password: Participant password.
        member_id: Your five-character GIMAC member code, sent as ``tomember``
            or ``frommember`` where the specification requires it. Optional at
            construction so the client can be built before the code is known.
        default_dial_code: Country code prepended by
            :func:`~gimacpay.money.normalise_phone` when a phone number has
            none. ``"237"`` for Cameroun.
        timeout: Per-request timeout in seconds.
        opener: Injection point for tests and for a custom TLS context. Defaults
            to :func:`urllib.request.urlopen`.

    Example::

        from gimacpay import GimacPayClient, wallet_to_wallet

        client = GimacPayClient(
            base_url="https://gimacpay.example.cm/stdendpointfacade/v1/external",
            client_id="...",
            client_secret="...",
            username="...",
            password="...",
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
        if payment.is_accepted:
            ...
    """

    def __init__(
        self,
        base_url: str = REFERENCE_SERVER,
        *,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        member_id: str | None = None,
        default_dial_code: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        opener: Any = None,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("base_url", base_url),
                ("client_id", client_id),
                ("client_secret", client_secret),
                ("username", username),
                ("password", password),
            )
            if not value
        ]
        if missing:
            raise GimacPayConfigError("missing required configuration: " + ", ".join(missing))

        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.member_id = member_id
        self.default_dial_code = default_dial_code
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------ #
    # authentication
    # ------------------------------------------------------------------ #

    @property
    def token_endpoint(self) -> str:
        """The OAuth 2.0 token URL, per the specification's ``securitySchemes``."""
        return f"{self.base_url}/oauth/token"

    def authenticate(self) -> str:
        """Fetch a fresh access token and cache it.

        Returns:
            The access token.

        Raises:
            GimacPayAuthError: the credentials were refused.
            GimacPayTransportError: the token endpoint could not be reached.
        """
        body = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("ascii")

        request = urllib.request.Request(
            self.token_endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

        status, payload = self._execute(request)
        if status != 200 or not isinstance(payload, Mapping):
            raise GimacPayAuthError.from_body(status, payload)

        token = payload.get("access_token")
        if not token:
            raise GimacPayProtocolError(
                f"token endpoint answered 200 without an 'access_token': {sorted(payload.keys())}"
            )

        self._access_token = str(token)
        expires_in = _as_float(payload.get("expires_in"), default=3600.0)
        self._token_expires_at = time.monotonic() + max(expires_in - _TOKEN_SAFETY_MARGIN, 1.0)
        return self._access_token

    def _token(self, *, force: bool = False) -> str:
        if force or not self._access_token or time.monotonic() >= self._token_expires_at:
            return self.authenticate()
        return self._access_token

    # ------------------------------------------------------------------ #
    # the three endpoints
    # ------------------------------------------------------------------ #

    def send_payment(self, payload: Mapping[str, Any]) -> Payment:
        """``POST /payment/send`` -- start a payment.

        Args:
            payload: A request object. Build it with one of the helpers in
                :mod:`gimacpay.builders` rather than by hand: the ``intent``
                field selects which of the specification's 24 request schemas
                applies, and the helpers set it correctly.

        Returns:
            The :class:`~gimacpay.models.Payment` as GIMACPay first describes
            it. **Its state may still be** ``PENDING`` -- a 200 here means
            accepted *or* pending, per the specification's own response
            description. Use :meth:`send_and_resolve` if you want a terminal
            state without writing the polling loop yourself.

        Raises:
            PaymentRejected: HTTP 400. The reason is in ``error_description``.
            GimacPayForbiddenError: HTTP 403. Your source IP is not authorised.
            GimacPayAuthError: HTTP 401 after a token refresh.
            PaymentStateUnknown: any other status code. **The state of the
                payment is not known.** Inquire; do not assume failure.
            GimacPayTransportError: the request never completed.
        """
        body = self._call("POST", "/payment/send", payload, issuertrxref=_ref(payload))
        return self._parse_payment(body)

    def inquiry(self, **filters: Any) -> list[Payment]:
        """``POST /payment/inquiry`` -- look up payments.

        All arguments are passed through as the request body, matching
        ``PaymentInquiryRequest``: ``issuertrxref``, ``acquirertrxref``,
        ``vouchercode``, ``asissuer``, ``asacquirer``, ``firstelement``,
        ``pagesize``, ``fromdate``, ``todate``, and so on.

        Returns:
            A list of :class:`~gimacpay.models.Payment`. Empty when nothing
            matched -- the specification documents 400 for "Invalid request or
            no payment found", so an empty list is the normal, successful
            "not found" outcome.

        Example::

            found = client.inquiry(issuertrxref="ORD-2026-0001", asissuer=True)
        """
        body = self._call("POST", "/payment/inquiry", dict(filters))
        if body is None:
            return []
        if isinstance(body, Mapping):
            # Some deployments wrap the array. Accept both rather than fail.
            for key in ("payments", "data", "items", "content"):
                if isinstance(body.get(key), list):
                    body = body[key]
                    break
            else:
                body = [body]
        if not isinstance(body, list):
            raise GimacPayProtocolError(
                f"inquiry returned {type(body).__name__}, expected a list of payments"
            )
        return [Payment.from_dict(item) for item in body if isinstance(item, Mapping)]

    def update_payment(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """``POST /payment/update`` -- amend a payment already sent.

        The specification types the request as ``UpdateRequest`` and documents
        the 200 response as an ``Http400Response`` shape (an ``error`` /
        ``error_description`` pair), which is almost certainly a documentation
        error. This method therefore returns the decoded body untyped rather
        than guessing which schema is right.

        Returns:
            The decoded response body.
        """
        body = self._call("POST", "/payment/update", payload, issuertrxref=_ref(payload))
        return body if isinstance(body, Mapping) else {}

    # ------------------------------------------------------------------ #
    # resolving an unknown state
    # ------------------------------------------------------------------ #

    def await_state(
        self,
        issuertrxref: str,
        *,
        timeout: float = 120.0,
        interval: float = 3.0,
        as_issuer: bool = True,
    ) -> Payment:
        """Poll ``/payment/inquiry`` until *issuertrxref* reaches a terminal state.

        This is the method the specification asks for. It never decides on its
        own what happened to the payment: it asks GIMACPay, repeatedly, and
        stops only when GIMACPay says the state is final.

        Args:
            issuertrxref: The reference you sent in the original request.
            timeout: Give up after this many seconds.
            interval: Seconds between polls. The specification's examples use
                ``validityduration`` values in the hundreds of seconds, so a
                few seconds between polls is appropriate.
            as_issuer: Send ``asissuer=True`` so only payments you issued match.

        Returns:
            The payment in its terminal state.

        Raises:
            TimeoutError: the state was still ``PENDING`` when *timeout* ran
                out. The payment is **not** failed -- it is still pending. Poll
                again later, or reconcile it out of band.
        """
        deadline = time.monotonic() + timeout
        last: Payment | None = None

        while True:
            results = self.inquiry(issuertrxref=issuertrxref, asissuer=as_issuer)
            for candidate in results:
                if candidate.issuertrxref == issuertrxref:
                    last = candidate
                    if candidate.is_terminal:
                        return candidate
                    break

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"payment {issuertrxref!r} is still "
                    f"{last.state if last else 'not found'} after {timeout:g}s; "
                    "it is not failed, it is unresolved -- poll again later"
                )
            time.sleep(interval)

    def send_and_resolve(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float = 120.0,
        interval: float = 3.0,
    ) -> Payment:
        """Send a payment, then follow it to a terminal state.

        The safe default for anything that moves money. It composes
        :meth:`send_payment` and :meth:`await_state`, and it handles the case
        the specification warns about: a response code that says nothing about
        the payment's fate.

        Args:
            payload: The request object.
            timeout: Total seconds allowed for the state to settle.
            interval: Seconds between inquiry calls.

        Returns:
            The payment, terminal.

        Raises:
            PaymentRejected: GIMACPay explicitly rejected it (HTTP 400). The
                money did not move, and no inquiry is needed.
            TimeoutError: still pending when time ran out. Poll again.
            GimacPayError: configuration, transport, or protocol failure.
        """
        ref = _ref(payload)
        if not ref:
            raise GimacPayConfigError(
                "the request has no 'issuertrxref'; it is required to follow the payment afterwards"
            )

        try:
            first = self.send_payment(payload)
        except PaymentStateUnknown:
            # The send did not tell us what happened. The specification's
            # instruction for exactly this case: keep it PENDING and inquire.
            pass
        else:
            if first.is_terminal:
                return first

        return self.await_state(ref, timeout=timeout, interval=interval)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def normalise_phone(self, value: str) -> str:
        """Normalise a phone number using this client's ``default_dial_code``.

        The builders are free functions and cannot see the client's
        configuration, so they strip formatting but never prepend a country
        code. Call this first when your callers type local numbers and GIMACPay
        expects E.164::

            client.normalise_phone("699947943")   # -> '237699947943'
        """
        return normalise_phone(value, default_dial_code=self.default_dial_code)

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #

    def _call(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any],
        *,
        issuertrxref: str | None = None,
    ) -> Any:
        """Issue an authenticated call, refreshing the token once on a 401."""
        for attempt in (1, 2):
            token = self._token(force=attempt == 2)
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                method=method,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            try:
                status, body = self._execute(request)
            except _Retryable:
                continue

            if status == 401 and attempt == 1:
                # Token was stale despite the cached expiry. Refresh and retry.
                continue

            return self._interpret(status, body, issuertrxref)

        # Unreachable: the loop either returns or raises.
        raise GimacPayAuthError(401, "unauthorized", "token refresh failed")

    def _interpret(self, status: int, body: Any, issuertrxref: str | None) -> Any:
        """Map an HTTP status onto a value or an exception.

        The ``else`` branch is the important one. Any status the specification
        does not define -- including a 5xx -- means we do not know what happened
        to the payment, and saying so is the only honest answer.
        """
        if status == 200:
            return body
        if status == 400:
            raise _HttpError.from_body(status, body)
        if status == 401:
            raise _HttpError.from_body(status, body)
        if status == 403:
            raise _HttpError.from_body(status, body)

        raise PaymentStateUnknown(issuertrxref or "?", status=status, body=body)

    def _execute(self, request: urllib.request.Request) -> tuple:
        """Perform one HTTP round trip.

        Returns ``(status, decoded_body)``. Non-2xx responses are returned
        rather than raised, because the body is the useful part.
        """
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, _decode(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            return exc.code, _decode(raw)
        except urllib.error.URLError as exc:
            raise GimacPayTransportError(
                f"could not reach {request.full_url}: {exc.reason}", original=exc
            ) from exc
        except TimeoutError as exc:
            raise GimacPayTransportError(
                f"timed out after {self.timeout:g}s calling {request.full_url}",
                original=exc,
            ) from exc
        except OSError as exc:
            raise GimacPayTransportError(
                f"transport failure calling {request.full_url}: {exc}", original=exc
            ) from exc

    def _parse_payment(self, body: Any) -> Payment:
        if body is None:
            raise GimacPayProtocolError("expected a payment object, got an empty body")
        if isinstance(body, list):
            if not body:
                raise GimacPayProtocolError("expected a payment object, got an empty list")
            body = body[0]
        return Payment.from_dict(body)


class _Retryable(Exception):
    """Internal signal: refresh the token and try the call once more."""


def _ref(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("issuertrxref") if isinstance(payload, Mapping) else None
    return None if value is None else str(value)


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Keep the raw text so the caller can log what the server actually said.
        return raw.decode("utf-8", errors="replace")


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
