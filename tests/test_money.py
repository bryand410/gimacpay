"""``money`` -- phone normalisation and amount validation.

These two helpers exist because the specification is inconsistent about phone
number formatting and strict about amounts. Both are pure functions, so they
are tested exhaustively.
"""

from __future__ import annotations

import pytest

from gimacpay import CURRENCY_XAF, normalise_phone, validate_amount


class TestNormalisePhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+237 699 947 943", "237699947943"),
            ("237699947943", "237699947943"),
            ("00237699947943", "237699947943"),
            ("237-699-947-943", "237699947943"),
            ("+336575950505", "336575950505"),
            ("2367890899", "2367890899"),
            ("+235 66 00 00 00", "23566000000"),
        ],
    )
    def test_strips_everything_that_is_not_a_digit(self, raw, expected):
        assert normalise_phone(raw) == expected

    def test_adds_the_default_dial_code_to_a_local_number(self):
        assert normalise_phone("699947943", default_dial_code="237") == "237699947943"

    def test_does_not_double_the_code_when_one_is_already_present(self):
        assert normalise_phone("237699947943", default_dial_code="237") == "237699947943"

    def test_a_local_number_is_passed_through_unchanged(self):
        """The SDK never invents a country code.

        The specification's own ``MobileReloadRequestExample`` sends
        ``"677457857"`` -- a bare local number -- so refusing local numbers
        would reject GIMAC's own documented example. Stripping formatting and
        adding nothing is the faithful behaviour; prepending a *guessed* code
        is what would send money to a stranger.
        """
        assert normalise_phone("677457857") == "677457857"
        assert normalise_phone("677 678 789") == "677678789"

    def test_a_default_dial_code_is_used_when_asked_for(self):
        """Opt in explicitly when GIMACPay expects E.164."""
        assert normalise_phone("677457857", default_dial_code="237") == "237677457857"

    def test_a_default_dial_code_does_not_double_an_existing_one(self):
        assert normalise_phone("+237 699 947 943", default_dial_code="237") == "237699947943"

    def test_rejects_a_value_with_no_digits(self):
        with pytest.raises(ValueError, match="contains no digits"):
            normalise_phone("not a number")

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="required"):
            normalise_phone(None)  # type: ignore[arg-type]

    def test_two_digit_and_three_digit_codes_are_both_recognised(self):
        assert normalise_phone("+33 657 595 050 5") == "336575950505"
        assert normalise_phone("+237 6 99 94 79 43") == "237699947943"

    def test_every_specification_example_normalises_cleanly(self):
        """The three formats the spec actually uses, in one place."""
        assert normalise_phone("+336575950505") == "336575950505"
        assert normalise_phone("2367890899") == "2367890899"
        assert normalise_phone("2356789009") == "2356789009"


class TestValidateAmount:
    @pytest.mark.parametrize("raw,expected", [(500, 500), (1, 1), (75000, 75000)])
    def test_accepts_positive_ints(self, raw, expected):
        assert validate_amount(raw) == expected

    def test_accepts_a_whole_float(self):
        assert validate_amount(500.0) == 500

    def test_accepts_a_numeric_string(self):
        assert validate_amount(" 7500 ") == 7500

    def test_refuses_a_fractional_amount(self):
        """The specification types amount as int64: there are no decimals.

        Truncating 500.5 to 500 would move a different amount than intended.
        """
        with pytest.raises(ValueError, match="whole number"):
            validate_amount(500.5)

    @pytest.mark.parametrize("bad", [0, -1, -75000])
    def test_refuses_a_non_positive_amount(self, bad):
        with pytest.raises(ValueError, match="must be positive"):
            validate_amount(bad)

    def test_refuses_none(self):
        with pytest.raises(ValueError, match="required"):
            validate_amount(None)

    def test_refuses_a_boolean(self):
        """``True`` is an ``int`` in Python. It is never a valid amount."""
        with pytest.raises(ValueError, match="must be a number"):
            validate_amount(True)

    def test_refuses_a_non_numeric_string(self):
        with pytest.raises(ValueError, match="must be a number"):
            validate_amount("cinq cents")

    def test_uses_the_field_name_in_the_message(self):
        with pytest.raises(ValueError, match="dueAmount"):
            validate_amount(0, field_name="dueAmount")


def test_currency_constant_matches_the_specification_enum():
    """The spec's ``currency`` enum has exactly one member: the string "950".

    Not ``"XAF"``, not ``"FCFA"``. The specification file is the authority.
    """
    assert CURRENCY_XAF == "950"
