"""Small helpers that prevent the two most common field-level mistakes.

Both come straight from the specification's worked examples and from the
field reports collected in ``docs/``:

1. **Currency.** The spec's ``currency`` fields have a single-element enum:
   ``"950"`` -- the ISO 4217 *numeric* code for the Central African CFA franc
   (XAF). Not ``"XAF"``, not ``"FCFA"``, not a symbol. Sending the wrong form
   is a silent rejection.

2. **Phone numbers.** The specification is internally inconsistent: the
   remittance examples use ``"+336575950505"`` with a leading ``+``, while the
   ``cash_in`` and ``cash_deposit`` examples use ``"2367890899"`` without one.
   Mobile-money integrations in the region fail on this constantly, so the SDK
   normalises explicitly and lets you choose.

Nothing here performs I/O. Everything is pure, so it is trivially testable.
"""

from __future__ import annotations

import re

__all__ = [
    "CURRENCY_XAF",
    "CEMAC_DIAL_CODES",
    "normalise_phone",
    "validate_amount",
]

#: The only ``currency`` value the specification's enum allows.
CURRENCY_XAF = "950"

#: Dialling codes of the six CEMAC member states, plus the ones that appear in
#: the specification's own examples.
CEMAC_DIAL_CODES = {
    "237": "Cameroun",
    "235": "Tchad",
    "236": "République centrafricaine",
    "240": "Guinée équatoriale",
    "241": "Gabon",
    "242": "Congo",
    "229": "Bénin",
    "225": "Côte d'Ivoire",
    "228": "Togo",
    "226": "Burkina Faso",
    "227": "Niger",
    "221": "Sénégal",
    "223": "Mali",
    "33": "France",
}

_NON_DIGITS = re.compile(r"\D+")


def normalise_phone(value: str, *, default_dial_code: str | None = None) -> str:
    """Return *value* as digits only, with no ``+`` and no separators.

    The specification is inconsistent about this, so the SDK picks one canonical
    form -- digits only -- and applies it everywhere.

    A number that already carries a country code is returned as-is. A number
    that does not is returned **unchanged** unless you pass
    *default_dial_code*: the SDK never invents a country code, but it also
    never rejects one of the specification's own examples. The spec's
    ``MobileReloadRequestExample`` sends ``"677457857"`` and its
    ``CashInToWalletRequestExample`` sends ``"2367890899"``, while the
    remittance examples send ``"+336575950505"``. All three are valid.

    Args:
        value: Anything a caller might pass: ``"+237 699 947 943"``,
            ``"00237699947943"``, ``"237-699-947-943"``, ``"677457857"``.
        default_dial_code: Prepended when *value* has no country code. Pass the
            participant's home code (``"237"`` for Cameroun) when your callers
            type local numbers and GIMACPay expects E.164.

    Returns:
        A string of digits.

    Raises:
        ValueError: if *value* contains no digits at all.

    Example::

        >>> normalise_phone("+237 699 947 943")
        '237699947943'
        >>> normalise_phone("699947943", default_dial_code="237")
        '237699947943'
        >>> normalise_phone("00237699947943")
        '237699947943'
        >>> normalise_phone("677457857")   # the spec's own mobile_reload example
        '677457857'
    """
    if value is None:
        raise ValueError("phone number is required")

    digits = _NON_DIGITS.sub("", str(value))
    if not digits:
        raise ValueError(f"{value!r} contains no digits")

    # "00" is the international prefix in most of the region.
    if digits.startswith("00"):
        digits = digits[2:]

    if _has_known_dial_code(digits) or default_dial_code is None:
        return digits

    return _NON_DIGITS.sub("", default_dial_code) + digits


def _has_known_dial_code(digits: str) -> bool:
    """Whether *digits* begins with a dialling code we recognise.

    Checked longest-first so that ``"237"`` is not shadowed by a shorter code.
    A local number is 9 digits in the CEMAC zone; anything longer that starts
    with a known code is assumed to already carry one.
    """
    for code in sorted(CEMAC_DIAL_CODES, key=len, reverse=True):
        if digits.startswith(code) and len(digits) > len(code) + 4:
            return True
    return False


def validate_amount(value: object, *, field_name: str = "amount") -> int:
    """Check that *value* is a positive whole number, and return it as ``int``.

    The specification types ``amount`` as ``int64``. It is in the minor unit of
    the currency -- there is no decimal amount in the API.

    Refusing floats here is deliberate. ``500.0`` is fine and becomes ``500``;
    ``500.5`` is a bug in the caller's code, and silently truncating it would
    move a different amount of money than intended.

    Raises:
        ValueError: if the amount is missing, not a number, not whole, or not
            positive.
    """
    if value is None:
        raise ValueError(f"{field_name} is required")

    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise ValueError(f"{field_name} must be a number, got {value!r}")

    if isinstance(value, int):
        amount = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(
                f"{field_name} must be a whole number of minor units, got {value!r}; "
                "GIMACPay has no decimal amounts"
            )
        amount = int(value)
    elif isinstance(value, str):
        try:
            amount = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number, got {value!r}") from exc
    else:
        raise ValueError(f"{field_name} must be a number, got {type(value).__name__}")

    if amount <= 0:
        raise ValueError(f"{field_name} must be positive, got {amount}")

    return amount
