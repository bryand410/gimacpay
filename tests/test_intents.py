"""``intents`` and ``builders`` -- the discriminator and the required fields.

The point of these tests is that the SDK's tables agree with the specification
file shipped in ``docs/reference``. If GIMAC publishes a new intent, the test
that reads the YAML will fail, and that is the intended behaviour: a stale
table should be a red test, not a rejected payment in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gimacpay import ALL_INTENTS, Intent, build, is_known, required_fields
from gimacpay.builders import (
    account_inquiry,
    bill_inquiry,
    bill_payment,
    cash_deposit,
    cash_in,
    cash_out,
    merchant_purchase,
    mobile_reload,
    request_to_pay,
    wallet_to_wallet,
)

SPEC = Path(__file__).resolve().parent.parent / "docs" / "reference" / "gimac-api-1.10.yaml"


@pytest.fixture(scope="module")
def spec_text() -> str:
    assert SPEC.exists(), f"specification file missing: {SPEC}"
    return SPEC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def response_enum(spec_text: str) -> list:
    """The ``intent`` enum inside ``components.schemas.Payment``."""
    block = spec_text.split("    Payment:", 1)[1].split("    ApiResponse:", 1)[0]
    enum_block = block.split("intent:", 1)[1].split("createtime:", 1)[0]
    values = re.findall(r"^\s+- (\w+)\s*$", enum_block, re.MULTILINE)
    assert values, "could not parse the intent enum; the spec file changed shape"
    return values


@pytest.fixture(scope="module")
def request_one_of(spec_text: str) -> list:
    """The request schemas listed in ``/payment/send``'s ``oneOf``."""
    block = spec_text.split("  /payment/send:", 1)[1].split("      responses:", 1)[0]
    return re.findall(r"\$ref: '#/components/schemas/(\w+)'", block)


class TestAgainstTheSpecificationFile:
    """Cross-check the SDK against GIMAC's published YAML.

    Two inconsistencies in the specification are pinned here as tests rather
    than left as comments, so that if GIMAC fixes them the suite says so.
    """

    def test_the_response_enum_is_a_subset_of_the_sdk(self, response_enum):
        """Everything GIMACPay can report, the SDK knows about."""
        in_spec = set(response_enum)
        missing = in_spec - ALL_INTENTS
        assert not missing, f"intents in the spec but not in the SDK: {sorted(missing)}"

    def test_the_only_intent_missing_from_the_response_enum_is_mobile_reload(self, response_enum):
        """A real inconsistency in the specification, not a bug in the SDK.

        ``MobileReloadRequest`` is listed in ``/payment/send``'s ``oneOf`` and
        ``MobileReloadRequestExample`` is a worked example, but
        ``Payment.intent`` does not list ``mobile_reload``. A participant that
        sent an airtime purchase and then read the response enum would conclude
        the intent is impossible.

        If this test fails because the enum now contains ``mobile_reload``,
        GIMAC has fixed it: delete the extra assertion and celebrate.
        """
        extra = ALL_INTENTS - set(response_enum)
        assert extra == {"mobile_reload"}, (
            f"expected exactly one spec/SDK discrepancy (mobile_reload); got {sorted(extra)}"
        )

    def test_mobile_reload_is_reachable_through_the_request_schema(self, request_one_of):
        """Which is why the SDK keeps it despite the missing enum entry."""
        assert "MobileReloadRequest" in request_one_of

    def test_the_response_enum_lists_wallet_to_account_twice(self, response_enum):
        """A duplicate entry in the specification's own enum.

        Pinned so the next reader does not suspect the parser.
        """
        assert response_enum.count("wallet_to_account") == 2

    def test_the_sdk_deduplicates_that(self, response_enum):
        assert len(ALL_INTENTS) == len(set(response_enum)) + 1  # +1: mobile_reload

    def test_the_declared_api_version_is_still_what_we_built_against(self, spec_text):
        """A version bump means the tables need re-checking."""
        assert "version: '1.8'" in spec_text

    def test_the_spec_licence_is_still_marked_private(self, spec_text):
        """The licence is why the reference file is not redistributed.

        See the ``sdist`` exclusion in ``pyproject.toml``. If GIMAC ever changes
        this, the exclusion can be revisited -- so the assumption fails loudly
        rather than rotting quietly.
        """
        assert "name: Private" in spec_text


class TestIntentTables:
    def test_all_intents_are_known(self):
        for intent in ALL_INTENTS:
            assert is_known(intent)

    def test_an_unknown_intent_is_reported_as_unknown(self):
        assert not is_known("transfer_to_the_moon")

    def test_required_fields_is_empty_for_an_unknown_intent(self):
        """Unknown intents must not raise: a stale table is our problem, not the caller's."""
        assert required_fields("some_future_intent") == ()

    def test_every_intent_has_a_required_fields_entry(self):
        """A missing entry means a builder without a validation contract."""
        from gimacpay.intents import REQUIRED_FIELDS

        missing = ALL_INTENTS - set(REQUIRED_FIELDS)
        assert not missing, f"intents with no REQUIRED_FIELDS entry: {sorted(missing)}"

    def test_no_required_fields_entry_names_an_unknown_intent(self):
        from gimacpay.intents import REQUIRED_FIELDS

        stray = set(REQUIRED_FIELDS) - ALL_INTENTS
        assert not stray, f"REQUIRED_FIELDS names unknown intents: {sorted(stray)}"

    def test_the_transfer_and_cash_sets_are_disjoint(self):
        from gimacpay.intents import CASH_INTENTS, TRANSFER_INTENTS

        assert not (TRANSFER_INTENTS & CASH_INTENTS)


class TestBuildersSetTheDiscriminator:
    """Every builder must set ``intent`` itself -- the caller never types it."""

    def test_wallet_to_wallet(self):
        payload = wallet_to_wallet(
            amount=500,
            walletsource="2356789009",
            walletdestination="237699947943",
            tomember="22001",
            issuertrxref="ORD-1",
        )
        assert payload["intent"] == Intent.MOBILE_TRANSFER
        assert payload["amount"] == 500
        assert payload["currency"] == "950"
        assert payload["issuertrxref"] == "ORD-1"

    def test_merchant_purchase_keeps_the_merchant_code_verbatim(self):
        """The spec's merchant example uses a short code, not a phone number."""
        payload = merchant_purchase(
            amount=500,
            walletsource="2356789009",
            walletdestination="768960",
            tomember="22001",
            issuertrxref="ORD-2",
        )
        assert payload["intent"] == Intent.MERCHANT_PURCHASE
        assert payload["walletdestination"] == "768960"

    def test_request_to_pay(self):
        payload = request_to_pay(
            amount=75000,
            walletsource="10001LMG",
            walletdestination="2367890899",
            tomember="22001",
            issuertrxref="ORD-3",
        )
        assert payload["intent"] == Intent.REQUEST_TO_PAY

    def test_cash_in_carries_the_teller_and_point_of_service(self):
        payload = cash_in(
            amount=75000,
            walletdestination="2367890899",
            tomember="22001",
            teller="T001",
            pointofservice="BSIC_BANGUI",
            issuertrxref="ORD-4",
        )
        assert payload["intent"] == Intent.CASH_IN
        assert payload["teller"] == "T001"
        assert payload["pointofservice"] == "BSIC_BANGUI"

    def test_cash_deposit(self):
        payload = cash_deposit(
            amount=75000,
            walletdestination="2367890899",
            tomember="22001",
            issuertrxref="ORD-5",
        )
        assert payload["intent"] == Intent.CASH_DEPOSIT

    def test_cash_out_builds_the_customer_data_array(self):
        """The spec's examples send ``receivercustomerdata`` as a one-element array."""
        payload = cash_out(
            amount=75000,
            walletsource="677457857",
            validityduration=4500,
            receiver_firstname="Lara",
            receiver_secondname="James",
            merchantid="MERCH003",
            issuertrxref="ORD-6",
        )
        assert payload["intent"] == Intent.CASH_OUT
        assert payload["receivercustomerdata"] == [
            {"firstname": "Lara", "secondname": "James", "merchantid": "MERCH003"}
        ]

    def test_bill_inquiry_has_no_amount(self):
        """The purpose of an inquiry is to discover the amount."""
        payload = bill_inquiry(
            walletsource="237699947943",
            tomember="13001",
            query_ref="CTR_REF",
            contract_ref="1248899R78FDF",
            service_ref="SRV_001",
            issuertrxref="ORD-7",
        )
        assert payload["intent"] == Intent.BILL_INQUIRY
        assert "amount" not in payload
        assert payload["billInquiryData"]["queryRef"] == "CTR_REF"

    def test_bill_payment_builds_the_bill_list(self):
        payload = bill_payment(
            amount=7500,
            walletsource="237699947943",
            tomember="13001",
            service="SRV_001",
            bill_refs=["S-112-950-ENEO-10039-abc"],
            issuertrxref="ORD-8",
        )
        assert payload["intent"] == Intent.BILL_PAYMENT
        assert payload["billList"] == [{"billRef": "S-112-950-ENEO-10039-abc"}]

    def test_bill_payment_refuses_an_empty_bill_list(self):
        with pytest.raises(ValueError, match="at least one bill reference"):
            bill_payment(
                amount=7500,
                walletsource="237699947943",
                tomember="13001",
                service="SRV_001",
                bill_refs=[],
                issuertrxref="ORD-9",
            )

    def test_mobile_reload(self):
        payload = mobile_reload(
            amount=700,
            sendermobile="677457857",
            receivermobile="677678789",
            tomember="12101",
            issuertrxref="ORD-10",
        )
        assert payload["intent"] == Intent.MOBILE_RELOAD

    def test_account_inquiry_to_a_wallet(self):
        payload = account_inquiry(
            tomember="12001", walletdestination="237699947943", issuertrxref="ORD-11"
        )
        assert payload["intent"] == Intent.ACCOUNT_INQUIRY
        assert payload["walletdestination"] == "237699947943"
        assert "dstaccounts" not in payload

    def test_account_inquiry_to_an_account(self):
        payload = account_inquiry(
            tomember="12001", dstaccount="100297474748990", issuertrxref="ORD-12"
        )
        assert payload["dstaccounts"] == [{"iden": "100297474748990", "type": "ACCOUNT"}]

    def test_account_inquiry_refuses_both_targets(self):
        with pytest.raises(ValueError, match="exactly one"):
            account_inquiry(
                tomember="12001",
                walletdestination="237699947943",
                dstaccount="100297474748990",
                issuertrxref="ORD-13",
            )

    def test_account_inquiry_refuses_neither_target(self):
        with pytest.raises(ValueError, match="exactly one"):
            account_inquiry(tomember="12001", issuertrxref="ORD-14")


class TestBuilderSafety:
    def test_a_builder_refuses_a_missing_reference(self):
        """Without issuertrxref the payment can never be looked up again."""
        with pytest.raises(ValueError, match="issuertrxref is required"):
            wallet_to_wallet(
                amount=500,
                walletsource="2356789009",
                walletdestination="237699947943",
                tomember="22001",
                issuertrxref="",
            )

    def test_a_builder_refuses_a_zero_amount(self):
        with pytest.raises(ValueError, match="must be positive"):
            wallet_to_wallet(
                amount=0,
                walletsource="2356789009",
                walletdestination="237699947943",
                tomember="22001",
                issuertrxref="ORD-15",
            )

    def test_a_builder_reports_which_phone_field_was_bad(self):
        with pytest.raises(ValueError, match="walletsource"):
            wallet_to_wallet(
                amount=500,
                walletsource="not a number",
                walletdestination="237699947943",
                tomember="22001",
                issuertrxref="ORD-16",
            )

    def test_none_fields_are_dropped_rather_than_sent_as_null(self):
        payload = wallet_to_wallet(
            amount=500,
            walletsource="2356789009",
            walletdestination="237699947943",
            tomember="22001",
            issuertrxref="ORD-17",
        )
        assert "description" not in payload
        assert None not in payload.values()


class TestGenericBuild:
    def test_build_handles_an_intent_with_no_dedicated_builder(self):
        """The eight remittance intents are reachable through ``build``."""
        payload = build(
            "inc_acc_remit",
            issuertrxref="ORD-18",
            amount=750,
            tomember="10029",
            sendermobile="+336575950505",
            dstaccounts=[{"iden": "100291525478502", "type": "ACCOUNT"}],
        )
        assert payload["intent"] == "inc_acc_remit"
        assert payload["amount"] == 750
        assert payload["currency"] == "950"

    def test_build_validates_the_amount(self):
        with pytest.raises(ValueError, match="must be positive"):
            build("inc_acc_remit", issuertrxref="ORD-19", amount=-5)

    def test_build_requires_an_intent(self):
        with pytest.raises(ValueError, match="intent is required"):
            build("", issuertrxref="ORD-20")
