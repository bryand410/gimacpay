"""Resolving a payment to a terminal state.

``send_and_resolve`` is the safe default for anything that moves money. It
composes ``send_payment`` and ``await_state``, and it covers the case the
specification warns about: a response that says nothing about the payment's
fate.
"""

from __future__ import annotations

import time

import pytest
from conftest import (
    PAYMENT_ACCEPTED,
    PAYMENT_PENDING,
    PAYMENT_REJECTED,
    wallet_to_wallet_payload,
)

from gimacpay import PaymentState


class TestAwaitState:
    def test_it_polls_until_the_state_is_terminal(self, client, mock):
        mock.inquiry_returns(PAYMENT_ACCEPTED)
        payment = client.await_state("ORD-2026-0001", timeout=2, interval=0.01)
        assert payment.state == PaymentState.ACCEPTED
        assert payment.is_terminal

    def test_a_rejected_payment_is_terminal_too(self, client, mock):
        mock.inquiry_returns(PAYMENT_REJECTED)
        payment = client.await_state("ORD-2026-0001", timeout=2, interval=0.01)
        assert payment.state == PaymentState.REJECTED
        assert payment.is_terminal

    def test_it_keeps_polling_while_the_state_is_pending(self, client, mock):
        """The first inquiry is PENDING, so a second call must happen."""
        calls = {"n": 0}
        original = mock.inquiry_returns

        def pending_then_accepted():
            calls["n"] += 1
            if calls["n"] < 3:
                mock._inquiry_results = [PAYMENT_PENDING]
            else:
                mock._inquiry_results = [PAYMENT_ACCEPTED]

        # Drive the mock through two pending answers, then a terminal one.
        mock.inquiry_returns(PAYMENT_PENDING)
        threading_timer = None
        try:
            import threading

            def flip():
                time.sleep(0.05)
                original(PAYMENT_ACCEPTED)

            threading_timer = threading.Timer(0.05, flip)
            threading_timer.start()
            payment = client.await_state("ORD-2026-0001", timeout=2, interval=0.02)
        finally:
            if threading_timer:
                threading_timer.cancel()

        assert payment.is_accepted
        _ = pending_then_accepted

    def test_a_timeout_is_not_a_failure(self, client, mock):
        """Still pending when time ran out means: poll again. Not: it failed."""
        mock.inquiry_returns(PAYMENT_PENDING)
        with pytest.raises(TimeoutError) as excinfo:
            client.await_state("ORD-2026-0001", timeout=0.15, interval=0.02)

        message = str(excinfo.value)
        assert "not failed" in message
        assert "poll again" in message

    def test_it_only_matches_the_reference_it_was_given(self, client, mock):
        """A page of results must not resolve the wrong payment."""
        other = {**PAYMENT_ACCEPTED, "issuertrxref": "SOMEONE-ELSE"}
        mock.inquiry_returns(other, PAYMENT_ACCEPTED)
        payment = client.await_state("ORD-2026-0001", timeout=2, interval=0.01)
        assert payment.issuertrxref == "ORD-2026-0001"

    def test_it_asks_as_issuer_by_default(self, client, mock):
        mock.inquiry_returns(PAYMENT_ACCEPTED)
        client.await_state("ORD-2026-0001", timeout=2, interval=0.01)
        _method, _path, body, _headers = mock.last_request()
        assert body["asissuer"] is True
        assert body["issuertrxref"] == "ORD-2026-0001"


class TestSendAndResolve:
    def test_a_terminal_send_answer_needs_no_inquiry(self, client, mock):
        mock.send_returns(200, PAYMENT_ACCEPTED)
        mock.inquiry_returns(PAYMENT_ACCEPTED)

        payment = client.send_and_resolve(wallet_to_wallet_payload(), timeout=2)

        assert payment.is_accepted
        paths = [path for _m, path, _b, _h in mock.requests]
        assert not any(p.endswith("/payment/inquiry") for p in paths)

    def test_a_pending_send_answer_is_followed_up(self, client, mock):
        """The spec's own 200 description is "ACCEPTED or PENDING payment"."""
        mock.send_returns(200, PAYMENT_PENDING)
        mock.inquiry_returns(PAYMENT_ACCEPTED)

        payment = client.send_and_resolve(wallet_to_wallet_payload(), timeout=2, interval=0.01)

        assert payment.is_accepted
        paths = [path for _m, path, _b, _h in mock.requests]
        assert any(p.endswith("/payment/inquiry") for p in paths)

    def test_an_unknown_send_outcome_falls_through_to_inquiry(self, client, mock):
        """The case the specification describes in words. This is the whole point."""
        mock.send_returns(500, {"error": "500", "error_description": "gateway"})
        mock.inquiry_returns(PAYMENT_ACCEPTED)

        payment = client.send_and_resolve(wallet_to_wallet_payload(), timeout=2, interval=0.01)

        assert payment.is_accepted, "an unknown send must not be reported as a failure"

    def test_an_unknown_send_outcome_can_resolve_as_rejected(self, client, mock):
        """...and the inquiry is the authority, in either direction."""
        mock.send_returns(503, {"error": "503"})
        mock.inquiry_returns(PAYMENT_REJECTED)

        payment = client.send_and_resolve(wallet_to_wallet_payload(), timeout=2, interval=0.01)

        assert payment.is_rejected

    def test_an_explicit_rejection_is_raised_immediately(self, client, mock):
        """A 400 is definite: no inquiry, and the money did not move."""
        from gimacpay import PaymentRejected

        mock.script(400, {"error": "404", "error_description": "Wallet not found"})

        with pytest.raises(PaymentRejected):
            client.send_and_resolve(wallet_to_wallet_payload(), timeout=2)

    def test_a_request_without_a_reference_is_refused_before_sending(self, client, mock):
        """Nothing can be resolved without issuertrxref, so do not send at all."""
        from gimacpay import GimacPayConfigError

        with pytest.raises(GimacPayConfigError, match="issuertrxref"):
            client.send_and_resolve({"intent": "mobile_transfer", "amount": 500}, timeout=2)

        assert not mock.requests or all(
            p.endswith("/oauth/token") for _m, p, _b, _h in mock.requests
        ), "no payment should have been sent"

    def test_a_timeout_propagates_rather_than_being_swallowed(self, client, mock):
        mock.send_returns(200, PAYMENT_PENDING)
        mock.inquiry_returns(PAYMENT_PENDING)

        with pytest.raises(TimeoutError):
            client.send_and_resolve(wallet_to_wallet_payload(), timeout=0.15, interval=0.02)
