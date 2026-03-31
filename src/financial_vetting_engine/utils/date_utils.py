from datetime import date
from typing import Optional

import dateparser


_DATEPARSER_SETTINGS = {
    "PREFER_DAY_OF_MONTH": "first",
    "DATE_ORDER": "MDY",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "PREFER_LOCALE_DATE_ORDER": False,
}

_HEADER_WORDS = {"date", "value date", "txn date", "transaction date", "posting date"}


def parse_date(raw: str) -> Optional[date]:
    """
    Parse a raw date string to a date object.

    Handles common US formats:
      MM/DD/YYYY, MM-DD-YYYY, MMM DD YYYY, DD MMM YYYY, YYYY-MM-DD

    Returns None if the string cannot be parsed.
    """
    if not raw or not raw.strip():
        return None

    stripped = raw.strip()

    if stripped.lower() in _HEADER_WORDS:
        return None

    parsed = dateparser.parse(stripped, settings=_DATEPARSER_SETTINGS)
    if parsed is None:
        return None

    return parsed.date()


def looks_like_date_header(value: str) -> bool:
    """Return True if the value looks like a column header, not a real date."""
    return value.strip().lower() in _HEADER_WORDS
