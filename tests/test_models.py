"""``models`` -- parsing, terminal states, and the shapes the spec disagrees with itself about."""

from __future__ import annotations

import pytest
from conftest import PAYMENT_ACCEPTED, PAYMENT_PENDING, PAYMENT_REJECTED

from gimacpay import (
    TERMINAL_STATES,
    AccountInfo,
    Bill,
    CustomerData,
    GimacPayProtocolError,
    Payment,
    PaymentState,
)


class TestTerminalStates:
    def test_pending_is_the_only_non_terminal_state(self):
        """The whole polling design rests on this.

        The specification says to keep a payment PENDING and inquire until it
        leaves that state -- which only works if PENDING is the sole state that
        can still change.
        """
        assert PaymentState.PENDING not in TERMINAL_STATES
        for state in ("ACCEPTED", "REJECTED", "REVERSED", "EXPIRED", "CANCELLED"):
            assert state in TERMINAL_STATES

    def test_the_six_states_are_exactly_the_specifications_enum(self):
        assert TERMINAL_STATES | {PaymentState.PENDING} == {
            "ACCEPTED",
            "REJECTED",
            "PENDING",
            "REVERSED",
            "EXPIRED",
            "CANCELLED",
        }

    @pytest.mark.parametrize("state", ["ACCEPTED", "REJECTED", "REVERSED", "EXPIRED", "CANCELLED"])
    def test_a_terminal_state_reports_itself(self, state):
        assert Payment.from_dict({**PAYMENT_ACCEPTED, "state": state}).is_terminal

    def test_pending_does_not(self):
        assert not Payment.from_dict(PAYMENT_PENDING).is_terminal

    def test_an_unknown_state_is_not_treated_as_terminal(self):
        """An unrecognised state means keep asking, not give up."""
        payment = Payment.from_dict({**PAYMENT_ACCEPTED, "state": "SOMETHING_NEW"})
        assert not payment.is_terminal

    def test_a_missing_state_is_not_treated_as_terminal(self):
        payment = Payment.from_dict({**PAYMENT_ACCEPTED, "state": None})
        assert not payment.is_terminal


class TestParsing:
    def test_a_full_payment_round_trips(self):
        payment = Payment.from_dict(PAYMENT_ACCEPTED)
        assert payment.issuertrxref == "ORD-2026-0001"
        assert payment.acquirertrxref == "CI20261010.1030.ADFDF"
        assert payment.intent == "mobile_transfer"
        assert payment.amount == 500.0
        assert payment.currency == "950"
        assert payment.tomember == "22001"
        assert payment.frommember == "12001"

    def test_a_rejected_payment_carries_its_message(self):
        assert Payment.from_dict(PAYMENT_REJECTED).rejectmessage == "Wallet<2356789009> Not Found"

    def test_a_payment_without_a_reference_is_refused(self):
        with pytest.raises(GimacPayProtocolError, match="issuertrxref"):
            Payment.from_dict({"state": "ACCEPTED", "amount": 500})

    def test_the_error_names_the_keys_it_did_receive(self):
        with pytest.raises(GimacPayProtocolError, match="state"):
            Payment.from_dict({"state": "ACCEPTED"})

    def test_a_non_mapping_is_refused(self):
        with pytest.raises(GimacPayProtocolError, match="expected a payment object"):
            Payment.from_dict(["not", "a", "payment"])

    def test_unknown_top_level_fields_are_preserved(self):
        payment = Payment.from_dict({**PAYMENT_ACCEPTED, "brandnew": 1})
        assert payment.raw["brandnew"] == 1

    def test_the_raw_mapping_is_a_copy(self):
        source = dict(PAYMENT_ACCEPTED)
        payment = Payment.from_dict(source)
        source["state"] = "MUTATED"
        assert payment.raw["state"] == "ACCEPTED"

    def test_amounts_that_are_not_numbers_become_none(self):
        payment = Payment.from_dict({**PAYMENT_ACCEPTED, "amount": "cinq cents"})
        assert payment.amount is None

    def test_the_string_form_is_readable(self):
        text = str(Payment.from_dict(PAYMENT_ACCEPTED))
        assert "ORD-2026-0001" in text
        assert "ACCEPTED" in text


class TestAccountInfo:
    def test_it_parses_both_fields(self):
        account = AccountInfo.from_dict({"iden": "100297474748990", "type": "CARD"})
        assert account.iden == "100297474748990"
        assert account.type == "CARD"

    def test_type_is_optional(self):
        assert AccountInfo.from_dict({"iden": "x"}).type is None

    def test_it_serialises_back_without_none(self):
        assert AccountInfo.from_dict({"iden": "x"}).to_dict() == {"iden": "x"}
        assert AccountInfo.from_dict({"iden": "x", "type": "WALLET"}).to_dict() == {
            "iden": "x",
            "type": "WALLET",
        }


class TestCustomerData:
    def test_the_known_fields_are_parsed(self):
        customer = CustomerData.from_dict(
            {
                "firstname": "Infinte",
                "secondname": "Game machine",
                "idnumber": "10945888",
                "idtype": "National ID",
            }
        )
        assert customer.firstname == "Infinte"
        assert customer.idtype == "National ID"

    def test_an_unknown_field_goes_to_extra(self):
        customer = CustomerData.from_dict({"firstname": "A", "middlename": "B"})
        assert customer.extra == {"middlename": "B"}

    def test_it_serialises_extra_back_out(self):
        customer = CustomerData.from_dict({"firstname": "A", "middlename": "B"})
        assert customer.to_dict() == {"firstname": "A", "middlename": "B"}

    def test_the_merchant_id_is_recognised(self):
        assert CustomerData.from_dict({"merchantid": "MERCH001"}).merchantid == "MERCH001"


class TestBill:
    def test_it_parses_the_specifications_fields(self):
        bill = Bill.from_dict(
            {
                "billRef": "S-112-950-ENEO-10039-abc",
                "createtime": "1490109044",
                "dueTime": "1490109044",
                "dueAmount": 50000,
                "currency": "950",
                "status": "U",
            }
        )
        assert bill.billRef == "S-112-950-ENEO-10039-abc"
        assert bill.dueAmount == 50000.0
        assert bill.status == "U"

    def test_an_empty_bill_is_allowed(self):
        assert Bill.from_dict({}).billRef is None

    def test_a_non_numeric_amount_becomes_none(self):
        assert Bill.from_dict({"dueAmount": "?"}).dueAmount is None


class TestImmutability:
    def test_a_payment_cannot_be_mutated_in_place(self):
        """A payment record is evidence. Editing it should not be convenient."""
        import dataclasses

        payment = Payment.from_dict(PAYMENT_ACCEPTED)
        with pytest.raises(dataclasses.FrozenInstanceError):
            payment.state = "REJECTED"  # type: ignore[misc]
