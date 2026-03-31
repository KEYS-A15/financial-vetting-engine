import re
from decimal import Decimal, InvalidOperation
from typing import Optional


_STRIP_CHARS = re.compile(r"[\$,\s]")
_PARENS = re.compile(r"^\((.+)\)$")
_DR_CR = re.compile(r"(.*?)\s*(DR|CR)\s*$", re.IGNORECASE)


def parse_amount(raw: str) -> Optional[Decimal]:
    """
    Parse a raw amount string to Decimal.

    Handles:
      - Currency symbols and commas: $1,234.56 → 1234.56
      - Parentheses as negative:     (1,234.56) → -1234.56
      - DR/CR suffixes:              1234.56 DR → -1234.56, 1234.56 CR → 1234.56
      - Plain +/- signs

    Returns None if the string cannot be parsed.
    """
    if not raw or not raw.strip():
        return None

    value = raw.strip()
    negative = False

    # Parentheses → negative
    paren_match = _PARENS.match(value)
    if paren_match:
        value = paren_match.group(1)
        negative = True

    # DR/CR suffix
    dr_cr_match = _DR_CR.match(value)
    if dr_cr_match:
        value = dr_cr_match.group(1)
        suffix = dr_cr_match.group(2).upper()
        negative = suffix == "DR"

    # Strip $, commas, spaces
    value = _STRIP_CHARS.sub("", value)

    # Explicit leading minus
    if value.startswith("-"):
        negative = True
        value = value.lstrip("-")
    elif value.startswith("+"):
        value = value.lstrip("+")

    if not value:
        return None

    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None

    return -amount if negative else amount


def to_positive(amount: Decimal) -> Decimal:
    """Return the absolute value of a Decimal."""
    return amount if amount >= 0 else -amount


def is_zero(amount: Decimal) -> bool:
    return amount == Decimal("0")
