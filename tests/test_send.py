"""``send_payment`` -- the request shape and the response parsing."""

from __future__ import annotations

import json

import pytest
from conftest import PAYMENT_ACCEPTED, PAYMENT_PENDING, wallet_to_wallet_payload

from gimacpay import GimacPayProtocolError, Payment, PaymentState


class TestRequest:
    def test_the_payload_reaches_the_right_endpoint(self, client, mock):
        client.send_payment(wallet_to_wallet_payload())
        method, path, body, _headers = mock.last_request()
        assert method == "POST"
        assert path.endswith("/payment/send")
        assert body["intent"] == "mobile_transfer"
        assert body["amount"] == 500

    def test_the_intent_is_sent_verbatim(self, client, mock):
        """The discriminator selects which of the 24 schemas applies."""
        client.send_payment(wallet_to_wallet_payload(intent="request_to_pay"))
        _method, _path, body, _headers = mock.last_request()
        assert body["intent"] == "request_to_pay"


class TestResponse:
    def test_a_200_parses_into_a_payment(self, client):
        payment = client.send_payment(wallet_to_wallet_payload())
        assert isinstance(payment, Payment)
        assert payment.issuertrxref == "ORD-2026-0001"
        assert payment.state == PaymentState.ACCEPTED
        assert payment.amount == 500.0
        assert payment.currency == "950"

    def test_a_200_may_still_be_pending(self, client, mock):
        """The spec's own response description: "ACCEPTED or PENDING payment".

        A 200 is therefore not a final answer, and the SDK must not pretend it is.
        """
        mock.send_returns(200, PAYMENT_PENDING)
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.state == PaymentState.PENDING
        assert not payment.is_terminal
        assert not payment.is_accepted

    def test_a_bare_list_body_is_accepted(self, client, mock):
        """Some deployments wrap a single payment in an array."""
        mock.send_returns(200, [PAYMENT_ACCEPTED])
        assert client.send_payment(wallet_to_wallet_payload()).is_accepted

    def test_an_empty_list_is_a_protocol_error(self, client, mock):
        mock.send_returns(200, [])
        with pytest.raises(GimacPayProtocolError, match="empty list"):
            client.send_payment(wallet_to_wallet_payload())

    def test_an_empty_body_is_a_protocol_error(self, client, mock):
        mock.send_returns(200, None)
        with pytest.raises(GimacPayProtocolError, match="empty body"):
            client.send_payment(wallet_to_wallet_payload())

    def test_a_payment_without_a_reference_is_a_protocol_error(self, client, mock):
        """Without issuertrxref the payment can never be reconciled."""
        mock.send_returns(200, {"state": "ACCEPTED", "amount": 500})
        with pytest.raises(GimacPayProtocolError, match="issuertrxref"):
            client.send_payment(wallet_to_wallet_payload())

    def test_the_raw_response_is_always_kept(self, client, mock):
        """Nothing the server sent is discarded, even fields we do not model."""
        mock.send_returns(200, {**PAYMENT_ACCEPTED, "futurefield": "keep me"})
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.raw["futurefield"] == "keep me"

    def test_an_integer_issuertrxref_is_coerced_to_a_string(self, client, mock):
        """The spec declares issuertrxref as integer but every example sends a string.

        Coercing at the edge means callers compare like with like.
        """
        mock.send_returns(200, {**PAYMENT_ACCEPTED, "issuertrxref": 475214752224})
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.issuertrxref == "475214752224"

    def test_a_non_json_body_is_a_protocol_error_not_a_crash(self, client, mock):
        mock.send_returns(200, "<html>gateway</html>")
        with pytest.raises(GimacPayProtocolError):
            client.send_payment(wallet_to_wallet_payload())


class TestNestedObjects:
    def test_accounts_are_parsed(self, client, mock):
        mock.send_returns(
            200,
            {
                **PAYMENT_ACCEPTED,
                "dstaccounts": [{"iden": "100291525478502", "type": "ACCOUNT"}],
                "srcaccounts": [{"iden": "1000149505050", "type": "ACCOUNT"}],
            },
        )
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.dstaccounts[0].iden == "100291525478502"
        assert payment.dstaccounts[0].type == "ACCOUNT"
        assert payment.srcaccounts[0].iden == "1000149505050"

    def test_a_numeric_iden_is_coerced_to_a_string(self, client, mock):
        """The spec's own examples quote it in one place and not in another."""
        mock.send_returns(200, {**PAYMENT_ACCEPTED, "dstaccounts": [{"iden": 100291525478502}]})
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.dstaccounts[0].iden == "100291525478502"

    def test_customer_data_as_a_one_element_array(self, client, mock):
        """The examples send an array; the schema says object. Accept both."""
        mock.send_returns(
            200,
            {
                **PAYMENT_ACCEPTED,
                "receivercustomerdata": [{"firstname": "Lara", "secondname": "James"}],
            },
        )
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.receivercustomerdata is not None
        assert payment.receivercustomerdata.firstname == "Lara"

    def test_customer_data_as_an_object(self, client, mock):
        mock.send_returns(
            200,
            {
                **PAYMENT_ACCEPTED,
                "sendercustomerdata": {"firstname": "Infinte", "idtype": "National ID"},
            },
        )
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.sendercustomerdata.idtype == "National ID"

    def test_an_unknown_customer_field_is_preserved(self, client, mock):
        mock.send_returns(
            200,
            {**PAYMENT_ACCEPTED, "sendercustomerdata": {"firstname": "A", "newfield": "x"}},
        )
        payment = client.send_payment(wallet_to_wallet_payload())
        assert payment.sendercustomerdata.extra["newfield"] == "x"


class TestInquiry:
    def test_inquiry_returns_a_list(self, client, mock):
        mock.inquiry_returns(PAYMENT_ACCEPTED)
        results = client.inquiry(issuertrxref="ORD-2026-0001", asissuer=True)
        assert len(results) == 1
        assert results[0].is_accepted

    def test_inquiry_filters_are_passed_through(self, client, mock):
        client.inquiry(issuertrxref="ORD-1", asissuer=True, pagesize=10, firstelement=0)
        _method, path, body, _headers = mock.last_request()
        assert path.endswith("/payment/inquiry")
        assert body == {
            "issuertrxref": "ORD-1",
            "asissuer": True,
            "pagesize": 10,
            "firstelement": 0,
        }

    def test_an_empty_result_is_not_an_error(self, client, mock):
        """The spec documents 400 for "no payment found", so an empty list is normal."""
        mock.inquiry_returns()
        assert client.inquiry(issuertrxref="nothing") == []

    def test_a_wrapped_array_is_unwrapped(self, client, mock):
        """Some deployments return {"payments": [...]} instead of a bare array."""
        mock.script(200, {"payments": [PAYMENT_ACCEPTED]})
        results = client.inquiry(issuertrxref="ORD-2026-0001")
        assert len(results) == 1

    def test_a_bare_object_is_wrapped_into_a_list(self, client, mock):
        mock.script(200, PAYMENT_ACCEPTED)
        results = client.inquiry(issuertrxref="ORD-2026-0001")
        assert len(results) == 1
        assert results[0].is_accepted


class TestUpdate:
    def test_update_returns_the_decoded_body(self, client, mock):
        """The spec types the 200 as an error object, which is probably a doc bug.

        The SDK returns it untyped rather than guessing which schema is right.
        """
        result = client.update_payment({"issuertrxref": "ORD-2026-0001"})
        assert isinstance(result, dict)

    def test_update_calls_the_right_endpoint(self, client, mock):
        client.update_payment({"issuertrxref": "ORD-2026-0001"})
        _method, path, body, _headers = mock.last_request()
        assert path.endswith("/payment/update")
        assert json.loads(json.dumps(body))["issuertrxref"] == "ORD-2026-0001"
