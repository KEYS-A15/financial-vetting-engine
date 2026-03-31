from datetime import date
from decimal import Decimal

import pytest

from financial_vetting_engine.schemas.extraction import PageExtraction, RawExtractionResult
from financial_vetting_engine.schemas.transaction import TransactionCategory, TransactionType
from financial_vetting_engine.services.normalizer import _categorize, _detect_columns, normalize
from financial_vetting_engine.utils.date_utils import parse_date
from financial_vetting_engine.utils.money_utils import parse_amount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(rows: list[dict], method: str = "table") -> RawExtractionResult:
    page = PageExtraction(page_number=1, method=method, rows=rows, raw_text="")
    return RawExtractionResult(pages=[page], page_count=1, file_name="test.pdf", file_size_bytes=1024)


# ---------------------------------------------------------------------------
# date_utils
# ---------------------------------------------------------------------------

class TestParseDateFormats:
    def test_mm_slash_dd_slash_yyyy(self):
        assert parse_date("01/15/2024") == date(2024, 1, 15)

    def test_mm_dash_dd_dash_yyyy(self):
        assert parse_date("03-22-2024") == date(2024, 3, 22)

    def test_mmm_dd_yyyy(self):
        assert parse_date("Jan 15 2024") == date(2024, 1, 15)

    def test_dd_mmm_yyyy(self):
        assert parse_date("15 Jan 2024") == date(2024, 1, 15)

    def test_iso_format(self):
        assert parse_date("2024-06-30") == date(2024, 6, 30)

    def test_none_on_empty(self):
        assert parse_date("") is None

    def test_none_on_header_word(self):
        assert parse_date("Date") is None

    def test_none_on_garbage(self):
        assert parse_date("not a date at all @@##") is None


# ---------------------------------------------------------------------------
# money_utils
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_plain_decimal(self):
        assert parse_amount("1234.56") == Decimal("1234.56")

    def test_currency_symbol_and_commas(self):
        assert parse_amount("$1,234.56") == Decimal("1234.56")

    def test_parentheses_negative(self):
        assert parse_amount("(1,234.56)") == Decimal("-1234.56")

    def test_dr_suffix_negative(self):
        assert parse_amount("500.00 DR") == Decimal("-500.00")

    def test_cr_suffix_positive(self):
        assert parse_amount("500.00 CR") == Decimal("500.00")

    def test_leading_minus(self):
        assert parse_amount("-99.00") == Decimal("-99.00")

    def test_leading_plus(self):
        assert parse_amount("+250.00") == Decimal("250.00")

    def test_none_on_empty(self):
        assert parse_amount("") is None

    def test_none_on_garbage(self):
        assert parse_amount("N/A") is None

    def test_zero(self):
        assert parse_amount("0.00") == Decimal("0.00")


# ---------------------------------------------------------------------------
# Category assignment
# ---------------------------------------------------------------------------

class TestCategorize:
    def test_salary(self):
        assert _categorize("GUSTO PAYROLL DIRECT DEP") == TransactionCategory.SALARY

    def test_salary_over_transfer_for_ach(self):
        # SALARY pattern must win over TRANSFER for payroll ACH
        assert _categorize("ADP PAYROLL ACH") == TransactionCategory.SALARY

    def test_rent(self):
        assert _categorize("MONTHLY RENT PAYMENT") == TransactionCategory.RENT

    def test_utilities(self):
        assert _categorize("COMCAST INTERNET BILL") == TransactionCategory.UTILITIES

    def test_groceries(self):
        assert _categorize("WHOLE FOODS MARKET #123") == TransactionCategory.GROCERIES

    def test_dining(self):
        assert _categorize("DOORDASH CHIPOTLE ORDER") == TransactionCategory.DINING

    def test_gambling(self):
        assert _categorize("DRAFTKINGS DEPOSIT") == TransactionCategory.GAMBLING

    def test_atm(self):
        assert _categorize("ATM CASH WITHDRAWAL") == TransactionCategory.ATM

    def test_transfer(self):
        assert _categorize("ZELLE PAYMENT TO JOHN") == TransactionCategory.TRANSFER

    def test_loan_payment(self):
        assert _categorize("NAVIENT STUDENT LOAN PMT") == TransactionCategory.LOAN_PAYMENT

    def test_other(self):
        assert _categorize("MYSTERY PURCHASE XYZ") == TransactionCategory.OTHER


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

class TestDetectColumns:
    def test_detects_named_columns(self):
        rows = [{"Date": "01/01/2024", "Description": "Salary", "Amount": "5000.00"}]
        cols = _detect_columns(rows)
        assert cols["date"] == "Date"
        assert cols["description"] == "Description"
        assert cols["amount"] == "Amount"

    def test_detects_debit_credit_split(self):
        rows = [{"Date": "01/01/2024", "Narration": "ATM", "Debit": "200", "Credit": "", "Balance": "800"}]
        cols = _detect_columns(rows)
        assert cols["debit"] == "Debit"
        assert cols["credit"] == "Credit"
        assert cols["balance"] == "Balance"

    def test_fallback_date_by_parse_rate(self):
        rows = [{"col_0": "01/15/2024", "col_1": "Salary", "col_2": "5000.00"}] * 5
        cols = _detect_columns(rows)
        assert cols["date"] == "col_0"

    def test_description_is_longest_text_column(self):
        rows = [{"Date": "01/01/2024", "Ref": "TXN001", "Narration": "Payment to landlord for January rent"}] * 5
        cols = _detect_columns(rows)
        assert cols["description"] == "Narration"


# ---------------------------------------------------------------------------
# normalize() — end-to-end
# ---------------------------------------------------------------------------

class TestNormalize:
    def _std_rows(self, extra: list[dict] | None = None) -> list[dict]:
        base = [
            {"Date": "01/10/2024", "Description": "GUSTO PAYROLL",   "Amount": "5000.00", "Balance": "5500.00"},
            {"Date": "01/12/2024", "Description": "WHOLE FOODS",      "Amount": "-120.50", "Balance": "5379.50"},
            {"Date": "01/15/2024", "Description": "ATM WITHDRAWAL",   "Amount": "-200.00", "Balance": "5179.50"},
        ]
        return base + (extra or [])

    def test_returns_list_of_transactions(self):
        raw = _make_raw(self._std_rows())
        result = normalize(raw)
        assert len(result) == 3

    def test_amounts_always_positive(self):
        raw = _make_raw(self._std_rows())
        for txn in normalize(raw):
            assert txn.amount > 0

    def test_transaction_type_from_sign(self):
        raw = _make_raw(self._std_rows())
        txns = {t.description: t for t in normalize(raw)}
        assert txns["GUSTO PAYROLL"].transaction_type == TransactionType.CREDIT
        assert txns["ATM WITHDRAWAL"].transaction_type == TransactionType.DEBIT

    def test_categories_assigned(self):
        raw = _make_raw(self._std_rows())
        txns = {t.description: t for t in normalize(raw)}
        assert txns["GUSTO PAYROLL"].category == TransactionCategory.SALARY
        assert txns["WHOLE FOODS"].category == TransactionCategory.GROCERIES
        assert txns["ATM WITHDRAWAL"].category == TransactionCategory.ATM

    def test_balance_after_parsed(self):
        raw = _make_raw(self._std_rows())
        txns = normalize(raw)
        assert txns[0].balance_after == Decimal("5500.00")

    def test_header_row_filtered_out(self):
        rows = [
            {"Date": "Date", "Description": "Description", "Amount": "Amount"},
            {"Date": "01/10/2024", "Description": "SALARY", "Amount": "3000.00"},
        ]
        result = normalize(_make_raw(rows))
        assert len(result) == 1
        assert result[0].description == "SALARY"

    def test_zero_amount_row_filtered(self):
        rows = self._std_rows([{"Date": "01/20/2024", "Description": "FEE WAIVER", "Amount": "0.00", "Balance": "5179.50"}])
        result = normalize(_make_raw(rows))
        assert all(t.description != "FEE WAIVER" for t in result)

    def test_empty_rows_filtered(self):
        rows = self._std_rows([{"Date": "", "Description": "", "Amount": "", "Balance": ""}])
        result = normalize(_make_raw(rows))
        assert len(result) == 3

    def test_debit_credit_columns(self):
        rows = [
            {"Date": "01/10/2024", "Narration": "PAYROLL",   "Debit": "",       "Credit": "5000.00", "Balance": "5000.00"},
            {"Date": "01/12/2024", "Narration": "RENT PMT",  "Debit": "1500.00","Credit": "",        "Balance": "3500.00"},
        ]
        result = normalize(_make_raw(rows))
        assert len(result) == 2
        txns = {t.description: t for t in result}
        assert txns["PAYROLL"].transaction_type == TransactionType.CREDIT
        assert txns["RENT PMT"].transaction_type == TransactionType.DEBIT

    def test_text_only_pages_return_empty(self):
        raw = _make_raw([{"line": "some text"}], method="text")
        assert normalize(raw) == []

    def test_raw_description_preserved(self):
        rows = [{"Date": "01/10/2024", "Description": "  STARBUCKS #123  ", "Amount": "5.75", "Balance": "100.00"}]
        result = normalize(_make_raw(rows))
        assert result[0].raw_description == "STARBUCKS #123"

    def test_missing_balance_allowed(self):
        rows = [{"Date": "01/10/2024", "Description": "VENMO TRANSFER", "Amount": "50.00"}]
        result = normalize(_make_raw(rows))
        assert len(result) == 1
        assert result[0].balance_after is None
