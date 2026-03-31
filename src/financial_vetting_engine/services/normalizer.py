import logging
import re
from decimal import Decimal
from typing import Optional

from financial_vetting_engine.schemas.extraction import RawExtractionResult
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType
from financial_vetting_engine.utils.date_utils import looks_like_date_header, parse_date
from financial_vetting_engine.utils.money_utils import is_zero, parse_amount, to_positive

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category patterns — order matters: first match wins
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[TransactionCategory, re.Pattern]] = [
    (TransactionCategory.SALARY,       re.compile(r"PAYROLL|DIRECT\s*DEP|DDR|SALARY|GUSTO|ADP|PAYCHEX", re.I)),
    (TransactionCategory.LOAN_PAYMENT, re.compile(r"LOAN|MORTGAGE|STUDENT\s*LOAN|AUTO\s*PAY|NAVIENT|SALLIE\s*MAE|SOFI|NELNET", re.I)),
    (TransactionCategory.RENT,         re.compile(r"RENT|APARTMENT|LEASE|PROPERTY\s*MGMT|ZILLOW", re.I)),
    (TransactionCategory.UTILITIES,    re.compile(r"ELECTRIC|GAS|WATER|INTERNET|AT&T|VERIZON|COMCAST|XFINITY|T-MOBILE|UTILITY", re.I)),
    (TransactionCategory.GROCERIES,    re.compile(r"WHOLE\s*FOODS|TRADER\s*JOE|KROGER|SAFEWAY|WALMART|COSTCO|ALDI|PUBLIX|WEGMANS|GIANT|STOP\s*&\s*SHOP", re.I)),
    (TransactionCategory.DINING,       re.compile(r"RESTAURANT|DOORDASH|UBER\s*EATS|GRUBHUB|STARBUCKS|CHIPOTLE|MCDONALD|SUBWAY|DOMINO|PIZZA", re.I)),
    (TransactionCategory.GAMBLING,     re.compile(r"CASINO|DRAFTKINGS|FANDUEL|BETMGM|LOTTERY", re.I)),
    (TransactionCategory.ATM,          re.compile(r"ATM|CASH\s*WITHDRAWAL|CASHOUT", re.I)),
    (TransactionCategory.TRANSFER,     re.compile(r"ZELLE|VENMO|PAYPAL|CASHAPP|CASH\s*APP|WIRE|TRANSFER|ACH", re.I)),
]


def _categorize(description: str) -> TransactionCategory:
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(description):
            return category
    return TransactionCategory.OTHER


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

_DEBIT_COL  = re.compile(r"\bdebit\b|\bwithdrawal\b|\bdr\b", re.I)
_CREDIT_COL = re.compile(r"\bcredit\b|\bdeposit\b|\bcr\b", re.I)
_DATE_COL   = re.compile(r"\bdate\b|\bvalue\b|\bposting\b", re.I)
_BAL_COL    = re.compile(r"\bbalance\b|\bbal\b|\brunning\b", re.I)
_AMT_COL    = re.compile(r"\bamount\b|\bamt\b", re.I)
_DESC_COL   = re.compile(r"\bdescription\b|\bnarration\b|\bparticular\b|\bdetail\b|\bmemo\b|\breference\b|\bdesc\b", re.I)


def _sample_parse_rate(rows: list[dict], key: str, parser) -> float:
    values = [str(r.get(key, "") or "").strip() for r in rows if str(r.get(key, "") or "").strip()]
    if not values:
        return 0.0
    hits = sum(1 for v in values if parser(v) is not None)
    return hits / len(values)


def _detect_columns(rows: list[dict]) -> dict:
    if not rows:
        return {}

    keys = list(rows[0].keys())
    result: dict[str, Optional[str]] = {
        "date": None, "amount": None, "description": None,
        "balance": None, "debit": None, "credit": None,
    }

    # Pass 1: name-based hints
    for k in keys:
        if _DATE_COL.search(k) and result["date"] is None:
            result["date"] = k
        elif _DEBIT_COL.search(k) and result["debit"] is None:
            result["debit"] = k
        elif _CREDIT_COL.search(k) and result["credit"] is None:
            result["credit"] = k
        elif _BAL_COL.search(k) and result["balance"] is None:
            result["balance"] = k
        elif _AMT_COL.search(k) and result["amount"] is None:
            result["amount"] = k
        elif _DESC_COL.search(k) and result["description"] is None:
            result["description"] = k

    sample = rows[:20]

    # Pass 2: parse-rate fallback for date
    if result["date"] is None:
        best, best_rate = None, 0.0
        for k in keys:
            rate = _sample_parse_rate(sample, k, parse_date)
            if rate > best_rate:
                best_rate, best = rate, k
        if best and best_rate >= 0.5:
            result["date"] = best
        else:
            log.warning("Could not confidently detect date column (best rate=%.2f)", best_rate)

    # Pass 3: parse-rate fallback for amount / debit+credit
    if result["amount"] is None and result["debit"] is None and result["credit"] is None:
        numeric_cols = []
        for k in keys:
            if k in (result["date"], result["description"], result["balance"]):
                continue
            rate = _sample_parse_rate(sample, k, parse_amount)
            if rate >= 0.4:
                numeric_cols.append((rate, k))
        numeric_cols.sort(reverse=True)
        if numeric_cols:
            result["amount"] = numeric_cols[0][1]
            if len(numeric_cols) >= 2 and result["balance"] is None:
                result["balance"] = numeric_cols[1][1]

    # Pass 4: description = longest average text column
    if result["description"] is None:
        skip = {v for v in result.values() if v}
        best_len, best_key = 0.0, None
        for k in keys:
            if k in skip:
                continue
            vals = [str(r.get(k, "") or "") for r in sample if str(r.get(k, "") or "").strip()]
            if not vals:
                continue
            avg_len = sum(len(v) for v in vals) / len(vals)
            if avg_len > best_len:
                best_len, best_key = avg_len, k
        if best_key:
            result["description"] = best_key
        else:
            log.warning("Could not detect description column")

    return result


# ---------------------------------------------------------------------------
# Row → Transaction
# ---------------------------------------------------------------------------

def _row_to_transaction(row: dict, cols: dict) -> Optional[Transaction]:
    # Skip completely empty rows
    values = [str(v).strip() for v in row.values() if v is not None]
    if not values or all(v == "" for v in values):
        return None

    # Date
    raw_date_val = str(row.get(cols.get("date") or "", "") or "").strip()
    if looks_like_date_header(raw_date_val):
        return None
    txn_date = parse_date(raw_date_val)
    if txn_date is None:
        if raw_date_val:
            log.debug("Skipping row — unparseable date: %r", raw_date_val)
        return None

    # Description
    desc_key = cols.get("description")
    raw_desc = str(row.get(desc_key, "") or "").strip() if desc_key else ""
    description = raw_desc

    # Amount + transaction type
    debit_key  = cols.get("debit")
    credit_key = cols.get("credit")
    amt_key    = cols.get("amount")

    amount: Optional[Decimal] = None
    txn_type: TransactionType = TransactionType.DEBIT

    if debit_key or credit_key:
        debit_val  = parse_amount(str(row.get(debit_key,  "") or "")) if debit_key  else None
        credit_val = parse_amount(str(row.get(credit_key, "") or "")) if credit_key else None

        has_credit = credit_val is not None and not is_zero(credit_val)
        has_debit  = debit_val  is not None and not is_zero(debit_val)

        if has_credit and not has_debit:
            amount   = to_positive(credit_val)
            txn_type = TransactionType.CREDIT
        elif has_debit:
            amount   = to_positive(debit_val)
            txn_type = TransactionType.DEBIT
    elif amt_key:
        raw_amt = str(row.get(amt_key, "") or "").strip()
        parsed  = parse_amount(raw_amt)
        if parsed is not None:
            txn_type = TransactionType.CREDIT if parsed >= 0 else TransactionType.DEBIT
            amount   = to_positive(parsed)

    if amount is None or is_zero(amount):
        return None

    # Balance
    bal_key = cols.get("balance")
    bal_val = parse_amount(str(row.get(bal_key, "") or "")) if bal_key else None

    return Transaction(
        date=txn_date,
        description=description,
        raw_description=raw_desc,
        amount=amount,
        transaction_type=txn_type,
        category=_categorize(description),
        balance_after=bal_val,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize(raw: RawExtractionResult) -> list[Transaction]:
    """Convert a RawExtractionResult into a clean list of Transactions."""
    all_rows: list[dict] = []
    for page in raw.pages:
        if page.method == "table":
            all_rows.extend(page.rows)

    if not all_rows:
        log.warning("No table rows found in extraction — only text pages present")
        return []

    cols = _detect_columns(all_rows)
    log.debug("Detected columns: %s", cols)

    transactions: list[Transaction] = []
    for row in all_rows:
        txn = _row_to_transaction(row, cols)
        if txn:
            transactions.append(txn)

    log.info("Normalized %d transactions from %d raw rows", len(transactions), len(all_rows))
    return transactions
