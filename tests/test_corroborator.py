from datetime import date
from decimal import Decimal

import pytest

from financial_vetting_engine.schemas.corroboration import CorroborationResult, PayStubData
from financial_vetting_engine.schemas.extraction import PageExtraction, RawExtractionResult
from financial_vetting_engine.schemas.flags import RiskLevel
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType
from financial_vetting_engine.services.corroborator import corroborate, extract_pay_stub_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(text: str) -> RawExtractionResult:
    return RawExtractionResult(
        pages=[PageExtraction(page_number=1, method="text", rows=[], raw_text=text)],
        page_count=1,
        file_name="stub.pdf",
        file_size_bytes=len(text.encode()),
    )


SAMPLE_STUB_TEXT = """\
ACME CORPORATION
Pay Statement

Employee Name: John Doe
Pay Date: 01/15/2024
Pay Period: 01/01/2024 - 01/15/2024

Gross Pay: $5,000.00
Federal Tax: $750.00
State Tax: $250.00
Social Security: $310.00
Medicare: $72.50
Net Pay: $3,617.50

YTD Gross: $10,000.00
"""


def _salary(
    amount: str,
    txn_date: date = date(2024, 1, 15),
    description: str = "ACME CORP PAYROLL",
) -> Transaction:
    return Transaction(
        date=txn_date,
        description=description,
        raw_description=description,
        amount=Decimal(amount),
        transaction_type=TransactionType.CREDIT,
        category=TransactionCategory.SALARY,
    )


def _debit(amount: str, txn_date: date = date(2024, 1, 20), description: str = "Purchase") -> Transaction:
    return Transaction(
        date=txn_date,
        description=description,
        raw_description=description,
        amount=Decimal(amount),
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.OTHER,
    )


def _non_salary_credit(
    amount: str,
    txn_date: date = date(2024, 1, 16),
    description: str = "TRANSFER IN",
) -> Transaction:
    return Transaction(
        date=txn_date,
        description=description,
        raw_description=description,
        amount=Decimal(amount),
        transaction_type=TransactionType.CREDIT,
        category=TransactionCategory.TRANSFER,
    )


# ---------------------------------------------------------------------------
# extract_pay_stub_data
# ---------------------------------------------------------------------------

class TestExtractPayStubData:
    def test_parses_employer_name(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.employer_name == "ACME CORPORATION"

    def test_parses_employee_name(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.employee_name == "John Doe"

    def test_parses_pay_date(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.pay_date == "01/15/2024"

    def test_parses_gross_pay_as_decimal(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.gross_pay == Decimal("5000.00")

    def test_parses_net_pay_as_decimal(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.net_pay == Decimal("3617.50")

    def test_parses_federal_tax(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.federal_tax == Decimal("750.00")

    def test_parses_state_tax(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.state_tax == Decimal("250.00")

    def test_parses_social_security(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.social_security == Decimal("310.00")

    def test_parses_medicare(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.medicare == Decimal("72.50")

    def test_parses_ytd_gross(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert data.ytd_gross == Decimal("10000.00")

    def test_returns_paystubdata_instance(self):
        data = extract_pay_stub_data(_make_raw(SAMPLE_STUB_TEXT))
        assert isinstance(data, PayStubData)

    def test_handles_empty_text_gracefully(self):
        data = extract_pay_stub_data(_make_raw(""))
        assert data.gross_pay is None
        assert data.net_pay is None
        assert data.pay_date is None


# ---------------------------------------------------------------------------
# corroborate — no pay stub
# ---------------------------------------------------------------------------

class TestNoPayStub:
    def test_pay_stub_provided_false(self):
        result = corroborate([], pay_stub_raw=None)
        assert result.pay_stub_provided is False

    def test_empty_flags(self):
        result = corroborate([], pay_stub_raw=None)
        assert result.corroboration_flags == []

    def test_neutral_score(self):
        result = corroborate([], pay_stub_raw=None)
        assert result.corroboration_score == 50

    def test_note_mentions_skipped(self):
        result = corroborate([], pay_stub_raw=None)
        assert any("skipped" in n.lower() for n in result.notes)

    def test_returns_corroboration_result(self):
        result = corroborate([], pay_stub_raw=None)
        assert isinstance(result, CorroborationResult)


# ---------------------------------------------------------------------------
# corroborate — matching deposit (gap < 1%)
# ---------------------------------------------------------------------------

class TestMatchingDeposit:
    def test_score_above_90_for_exact_match(self):
        # Net pay = $3,617.50, deposit = $3,617.50 → gap = 0%
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.corroboration_score > 90

    def test_no_salary_gap_flag(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        codes = [f.code for f in result.corroboration_flags]
        assert "SALARY_DEPOSIT_GAP" not in codes

    def test_observed_deposit_populated(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.observed_deposit == Decimal("3617.50")

    def test_declared_net_pay_populated(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.declared_net_pay == Decimal("3617.50")


# ---------------------------------------------------------------------------
# corroborate — mismatched deposit (gap > 15%)
# ---------------------------------------------------------------------------

class TestMismatchedDeposit:
    def test_salary_deposit_gap_high_flag_present(self):
        # Declared net = $3,617.50, observed = $2,000 → gap ≈ 44.7%
        txns = [_salary("2000.00", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        flags = {f.code: f for f in result.corroboration_flags}
        assert "SALARY_DEPOSIT_GAP" in flags
        assert flags["SALARY_DEPOSIT_GAP"].level == RiskLevel.HIGH

    def test_gap_percent_exceeds_15(self):
        txns = [_salary("2000.00", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.gap_percent is not None
        assert result.gap_percent > Decimal("15")

    def test_score_reduced_for_large_gap(self):
        txns = [_salary("2000.00", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        # -40 for gap>15% at minimum
        assert result.corroboration_score <= 60

    def test_gap_amount_computed(self):
        txns = [_salary("2000.00", txn_date=date(2024, 1, 15))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.gap_amount == Decimal("1617.50")


# ---------------------------------------------------------------------------
# corroborate — no SALARY transaction → SALARY_NOT_FOUND
# ---------------------------------------------------------------------------

class TestNoSalaryTransaction:
    def test_salary_not_found_flag_present(self):
        txns = [_debit("500.00", txn_date=date(2024, 1, 20))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        codes = [f.code for f in result.corroboration_flags]
        assert "SALARY_NOT_FOUND" in codes

    def test_salary_not_found_is_high_level(self):
        txns = [_debit("500.00", txn_date=date(2024, 1, 20))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        flag = next(f for f in result.corroboration_flags if f.code == "SALARY_NOT_FOUND")
        assert flag.level == RiskLevel.HIGH

    def test_score_below_50_when_no_salary(self):
        # SALARY_NOT_FOUND (-50) + EMPLOYER_NAME_MISMATCH (-20) = 30
        txns = [_debit("500.00", txn_date=date(2024, 1, 20))]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.corroboration_score < 50


# ---------------------------------------------------------------------------
# corroborate — employer name match
# ---------------------------------------------------------------------------

class TestEmployerNameMatch:
    def test_match_when_employer_word_in_narration(self):
        # "ACME" from stub found in "ACME CORP PAYROLL"
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15), description="ACME CORP PAYROLL")]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.employer_name_match is True

    def test_no_employer_mismatch_flag_when_found(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15), description="ACME CORP PAYROLL")]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        codes = [f.code for f in result.corroboration_flags]
        assert "EMPLOYER_NAME_MISMATCH" not in codes

    def test_mismatch_when_employer_not_in_narration(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15), description="DIRECT DEPOSIT XYZ")]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        assert result.employer_name_match is False

    def test_mismatch_generates_employer_flag(self):
        txns = [_salary("3617.50", txn_date=date(2024, 1, 15), description="DIRECT DEPOSIT XYZ")]
        result = corroborate(txns, _make_raw(SAMPLE_STUB_TEXT))
        codes = [f.code for f in result.corroboration_flags]
        assert "EMPLOYER_NAME_MISMATCH" in codes


# ---------------------------------------------------------------------------
# corroborate — corroboration_score clamped to 0
# ---------------------------------------------------------------------------

class TestScoreClamped:
    def test_score_never_negative(self):
        # GLOBEX not in "TRANSFER IN", SALARY_NOT_FOUND (no salary tx), gap > 15%
        # Score = 100 - 50 (no salary) - 40 (gap>15%) - 20 (employer mismatch) = -10 → clamped to 0
        stub_text = """\
GLOBEX CORPORATION
Pay Statement

Employee Name: Jane Smith
Pay Date: 01/15/2024
Pay Period: 01/01/2024 - 01/31/2024

Gross Pay: $5,000.00
Net Pay: $3,500.00
"""
        # TRANSFER credit within ±3 bdays of Jan 15 provides fallback observed_deposit
        txns = [_non_salary_credit("1000.00", txn_date=date(2024, 1, 16))]
        result = corroborate(txns, _make_raw(stub_text))
        assert result.corroboration_score >= 0

    def test_score_is_zero_not_negative(self):
        stub_text = """\
GLOBEX CORPORATION
Pay Statement

Employee Name: Jane Smith
Pay Date: 01/15/2024
Pay Period: 01/01/2024 - 01/31/2024

Gross Pay: $5,000.00
Net Pay: $3,500.00
"""
        txns = [_non_salary_credit("1000.00", txn_date=date(2024, 1, 16))]
        result = corroborate(txns, _make_raw(stub_text))
        # Deductions: SALARY_NOT_FOUND(-50) + SALARY_DEPOSIT_GAP>15%(-40) + EMPLOYER_MISMATCH(-20) = -10 → 0
        assert result.corroboration_score == 0
