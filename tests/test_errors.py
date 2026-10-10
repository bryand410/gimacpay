"""Error mapping -- the most important file in the suite.

The specification defines three error responses (400, 401, 403) and then says
this about everything else::

    For all other responses codes, participants should keep the payment in
    PENDING state and perform a payment inquiry to GET the state. Participants
    should not guess the state if it's not given by GIMACPay.

So a 500 must **not** become a rejection. A client that turns an unknown
outcome into a failure is a client that tells its operator the money did not
move when it might have. These tests exist to make that impossible to
reintroduce.
"""

from __future__ import annotations

import socket

import pytest
from conftest import wallet_to_wallet_payload

from gimacpay import (
    GimacPayAuthError,
    GimacPayClient,
    GimacPayForbiddenError,
    GimacPayTransportError,
    PaymentRejected,
    PaymentStateUnknown,
)


class TestHttp400:
    """400 means the payment was rejected, and the reason is in the body."""

    def test_the_reason_is_carried_through(self, client, mock):
        mock.script(
            400,
            {"error": "404", "error_description": "Wallet<34JDJFKDKJDF> Not Found"},
        )
        with pytest.raises(PaymentRejected) as excinfo:
            client.send_payment(wallet_to_wallet_payload())

        exc = excinfo.value
        assert exc.status == 400
        assert exc.error == "404"
        assert exc.error_description == "Wallet<34JDJFKDKJDF> Not Found"

    def test_a_rejection_is_not_a_state_unknown(self, client, mock):
        """400 is a *definite* outcome. Do not confuse the two."""
        mock.script(400, {"error": "404", "error_description": "Not found"})
        with pytest.raises(PaymentRejected):
            client.send_payment(wallet_to_wallet_payload())

    def test_a_rejection_is_not_retried(self, client, mock):
        mock.script(400, {"error": "404", "error_description": "Not found"})
        with pytest.raises(PaymentRejected):
            client.send_payment(wallet_to_wallet_payload())
        assert len(mock.requests) == 2, "one token call, one send call -- no retry"


class TestHttp403:
    """403 is the source IP, not the credentials."""

    def test_it_is_its_own_exception(self, client, mock):
        mock.script(403, {"error": "Unauthorized", "error_description": "Unauthorized access"})
        with pytest.raises(GimacPayForbiddenError) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert excinfo.value.status == 403

    def test_it_is_not_confused_with_401(self, client, mock):
        mock.script(403, {"error": "Unauthorized", "error_description": "Unauthorized access"})
        with pytest.raises(GimacPayForbiddenError):
            client.send_payment(wallet_to_wallet_payload())

    def test_it_is_not_retried(self, client, mock):
        """Refreshing a token cannot fix an IP allow-list."""
        mock.script(403, {"error": "Unauthorized", "error_description": "Unauthorized access"})
        with pytest.raises(GimacPayForbiddenError):
            client.send_payment(wallet_to_wallet_payload())
        assert mock.tokens_issued == 1

    def test_the_specifications_own_wording_is_preserved(self, client, mock):
        mock.script(403, {"error": "Unauthorized", "error_description": "Unauthorized access"})
        with pytest.raises(GimacPayForbiddenError, match="Unauthorized access"):
            client.send_payment(wallet_to_wallet_payload())


class TestUnknownOutcome:
    """Everything the specification does not define means: we do not know."""

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 418, 429, 302])
    def test_an_undefined_status_raises_state_unknown(self, client, mock, status):
        mock.script(status, {"error": str(status), "error_description": "unexpected"})
        with pytest.raises(PaymentStateUnknown) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert excinfo.value.status == status

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_an_undefined_status_is_never_a_rejection(self, client, mock, status):
        """The single most expensive mistake this SDK could make."""
        mock.script(status, {"error": str(status)})
        with pytest.raises(PaymentStateUnknown) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert not isinstance(excinfo.value, PaymentRejected)

    def test_the_reference_is_carried_so_the_caller_can_inquire(self, client, mock):
        mock.script(500, {"error": "500"})
        with pytest.raises(PaymentStateUnknown) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert excinfo.value.issuertrxref == "ORD-2026-0001"

    def test_the_body_is_carried_for_logging(self, client, mock):
        mock.script(503, {"error": "503", "error_description": "maintenance"})
        with pytest.raises(PaymentStateUnknown) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert excinfo.value.body["error_description"] == "maintenance"

    def test_the_message_tells_the_operator_what_to_do(self, client, mock):
        mock.script(500, {"error": "500"})
        with pytest.raises(PaymentStateUnknown, match="keep it PENDING"):
            client.send_payment(wallet_to_wallet_payload())

    def test_an_unparseable_200_is_also_state_unknown(self, client, mock):
        """We got a 200 but cannot tell what it says. That is still not a failure."""
        from gimacpay import GimacPayProtocolError

        mock.send_returns(200, {"amount": 500, "state": "ACCEPTED"})
        with pytest.raises(GimacPayProtocolError):
            client.send_payment(wallet_to_wallet_payload())


class TestTransportFailure:
    def _client_at_a_dead_port(self) -> GimacPayClient:
        # Bind, read the port, close: the port is almost certainly free.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        return GimacPayClient(
            base_url=f"http://127.0.0.1:{port}/stdendpointfacade/v1/external",
            client_id="i",
            client_secret="s",
            username="u",
            password="p",
            timeout=2.0,
        )

    def test_a_refused_connection_is_a_transport_error(self):
        client = self._client_at_a_dead_port()
        with pytest.raises(GimacPayTransportError):
            client.send_payment(wallet_to_wallet_payload())

    def test_the_original_exception_is_kept(self):
        client = self._client_at_a_dead_port()
        with pytest.raises(GimacPayTransportError) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert excinfo.value.original is not None

    def test_a_transport_error_does_not_claim_the_payment_failed(self):
        """A dropped connection says nothing about whether the money moved."""
        client = self._client_at_a_dead_port()
        with pytest.raises(GimacPayTransportError) as excinfo:
            client.send_payment(wallet_to_wallet_payload())
        assert not isinstance(excinfo.value, PaymentRejected)

    def test_the_url_is_named_in_the_message(self):
        client = self._client_at_a_dead_port()
        with pytest.raises(GimacPayTransportError, match="oauth/token"):
            client.send_payment(wallet_to_wallet_payload())


class TestErrorHierarchy:
    def test_every_error_shares_a_base_class(self):
        from gimacpay import GimacPayError

        for exc_type in (
            PaymentRejected,
            PaymentStateUnknown,
            GimacPayAuthError,
            GimacPayForbiddenError,
            GimacPayTransportError,
        ):
            assert issubclass(exc_type, GimacPayError)

    def test_the_two_outcomes_are_siblings_not_related(self):
        """A rejection and an unknown state must never be caught by the same clause."""
        assert not issubclass(PaymentStateUnknown, PaymentRejected)
        assert not issubclass(PaymentRejected, PaymentStateUnknown)
