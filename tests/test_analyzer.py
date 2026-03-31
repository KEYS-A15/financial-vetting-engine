from datetime import date
from decimal import Decimal

import pytest

from financial_vetting_engine.schemas.flags import RiskLevel
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType
from financial_vetting_engine.services.analyzer import (
    analyze,
    _compute_metrics,
    compute_behavioral_scores,
    detect_flags,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _txn(
    amount: str,
    txn_type: TransactionType,
    category: TransactionCategory = TransactionCategory.OTHER,
    txn_date: date = date(2024, 1, 15),
    description: str = "Test",
    balance_after: str | None = None,
) -> Transaction:
    return Transaction(
        date=txn_date,
        description=description,
        raw_description=description,
        amount=Decimal(amount),
        transaction_type=txn_type,
        category=category,
        balance_after=Decimal(balance_after) if balance_after is not None else None,
    )


def _credit(amount: str, category=TransactionCategory.SALARY, **kwargs) -> Transaction:
    return _txn(amount, TransactionType.CREDIT, category, **kwargs)


def _debit(amount: str, category=TransactionCategory.OTHER, **kwargs) -> Transaction:
    return _txn(amount, TransactionType.DEBIT, category, **kwargs)


def _flags(txns: list[Transaction]):
    """Helper: compute metrics then run flag detectors."""
    m = _compute_metrics(txns)
    return detect_flags(txns, m)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_total_income_and_expenses(self):
        txns = [_credit("3000"), _debit("1000"), _debit("500")]
        m = _compute_metrics(txns)
        assert m.total_income == Decimal("3000")
        assert m.total_expenses == Decimal("1500")

    def test_net_cashflow(self):
        txns = [_credit("3000"), _debit("2000")]
        m = _compute_metrics(txns)
        assert m.net_cashflow == Decimal("1000")

    def test_net_cashflow_negative(self):
        txns = [_credit("1000"), _debit("2000")]
        m = _compute_metrics(txns)
        assert m.net_cashflow == Decimal("-1000")

    def test_expense_to_income_ratio(self):
        txns = [_credit("2000"), _debit("1000")]
        m = _compute_metrics(txns)
        assert m.expense_to_income_ratio == Decimal("0.50")

    def test_expense_to_income_ratio_zero_income(self):
        txns = [_debit("500")]
        m = _compute_metrics(txns)
        assert m.expense_to_income_ratio == Decimal("0")

    def test_largest_single_expense(self):
        txns = [_debit("100"), _debit("500"), _debit("250")]
        m = _compute_metrics(txns)
        assert m.largest_single_expense == Decimal("500")

    def test_largest_single_credit(self):
        txns = [_credit("1000"), _credit("4500"), _credit("2000")]
        m = _compute_metrics(txns)
        assert m.largest_single_credit == Decimal("4500")

    def test_transaction_count(self):
        txns = [_credit("1000"), _debit("200"), _debit("300")]
        m = _compute_metrics(txns)
        assert m.transaction_count == 3

    def test_months_analyzed(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("3000", txn_date=date(2024, 2, 1)),
            _credit("3000", txn_date=date(2024, 3, 1)),
        ]
        m = _compute_metrics(txns)
        assert m.months_analyzed == 3

    def test_nsf_count(self):
        txns = [
            _txn("200", TransactionType.DEBIT, balance_after="-50"),
            _txn("100", TransactionType.DEBIT, balance_after="150"),
            _txn("300", TransactionType.DEBIT, balance_after="-10"),
        ]
        m = _compute_metrics(txns)
        assert m.nsf_count == 2

    def test_avg_daily_balance_present(self):
        txns = [
            _txn("100", TransactionType.DEBIT, balance_after="200"),
            _txn("100", TransactionType.DEBIT, balance_after="400"),
        ]
        m = _compute_metrics(txns)
        assert m.avg_daily_balance == Decimal("300.00")

    def test_avg_daily_balance_absent(self):
        txns = [_credit("1000"), _debit("500")]
        m = _compute_metrics(txns)
        assert m.avg_daily_balance is None

    def test_monthly_breakdown_single_month(self):
        txns = [_credit("3000"), _debit("1000"), _debit("500")]
        m = _compute_metrics(txns)
        assert len(m.monthly_breakdown) == 1
        assert m.monthly_breakdown[0].month == "2024-01"
        assert m.monthly_breakdown[0].total_income == Decimal("3000")
        assert m.monthly_breakdown[0].total_expenses == Decimal("1500")
        assert m.monthly_breakdown[0].net == Decimal("1500")

    def test_monthly_breakdown_multiple_months(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 1, 15)),
            _credit("3000", txn_date=date(2024, 2, 1)),
            _debit("2000", txn_date=date(2024, 2, 15)),
        ]
        m = _compute_metrics(txns)
        assert len(m.monthly_breakdown) == 2
        assert m.monthly_breakdown[0].month == "2024-01"
        assert m.monthly_breakdown[1].month == "2024-02"

    def test_avg_monthly_income(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("4000", txn_date=date(2024, 2, 1)),
        ]
        m = _compute_metrics(txns)
        assert m.avg_monthly_income == Decimal("3500.00")

    def test_top_expense_categories_max_5(self):
        cats = [
            TransactionCategory.RENT, TransactionCategory.DINING,
            TransactionCategory.GROCERIES, TransactionCategory.ATM,
            TransactionCategory.TRANSFER, TransactionCategory.UTILITIES,
        ]
        txns = [_debit(str(100 * (i + 1)), category=c) for i, c in enumerate(cats)]
        m = _compute_metrics(txns)
        assert len(m.top_expense_categories) == 5

    def test_top_expense_categories_sorted_by_amount(self):
        txns = [
            _debit("100", category=TransactionCategory.DINING),
            _debit("500", category=TransactionCategory.RENT),
            _debit("200", category=TransactionCategory.ATM),
        ]
        m = _compute_metrics(txns)
        top_keys = list(m.top_expense_categories.keys())
        assert top_keys[0] == "rent"

    def test_known_10_transactions_exact_values(self):
        txns = [
            _credit("5000.00", txn_date=date(2024, 1, 1)),
            _debit("1200.00", category=TransactionCategory.RENT, txn_date=date(2024, 1, 5)),
            _debit("300.00",  category=TransactionCategory.GROCERIES, txn_date=date(2024, 1, 10)),
            _debit("150.00",  category=TransactionCategory.DINING, txn_date=date(2024, 1, 15)),
            _debit("80.00",   category=TransactionCategory.UTILITIES, txn_date=date(2024, 1, 20)),
            _credit("5000.00", txn_date=date(2024, 2, 1)),
            _debit("1200.00", category=TransactionCategory.RENT, txn_date=date(2024, 2, 5)),
            _debit("400.00",  category=TransactionCategory.GROCERIES, txn_date=date(2024, 2, 10)),
            _debit("200.00",  category=TransactionCategory.DINING, txn_date=date(2024, 2, 15)),
            _debit("100.00",  category=TransactionCategory.UTILITIES, txn_date=date(2024, 2, 20)),
        ]
        m = _compute_metrics(txns)
        assert m.total_income    == Decimal("10000.00")
        assert m.total_expenses  == Decimal("3630.00")
        assert m.net_cashflow    == Decimal("6370.00")
        assert m.avg_monthly_income   == Decimal("5000.00")
        assert m.avg_monthly_expenses == Decimal("1815.00")
        assert m.largest_single_expense == Decimal("1200.00")
        assert m.largest_single_credit  == Decimal("5000.00")
        assert m.transaction_count == 10
        assert m.months_analyzed   == 2
        assert m.nsf_count == 0
        assert m.avg_daily_balance is None
        assert list(m.top_expense_categories.keys())[0] == "rent"

    def test_empty_transactions(self):
        m, scores = analyze([])
        assert m.total_income == Decimal("0")
        assert m.transaction_count == 0
        assert m.nsf_count == 0
        assert m.months_analyzed == 0
        assert scores.income_stability == 50
        assert scores.overall == 50

    def test_single_transaction(self):
        txns = [_credit("3000")]
        m, scores = analyze(txns)
        assert m.total_income == Decimal("3000")
        assert m.transaction_count == 1
        assert m.months_analyzed == 1


# ---------------------------------------------------------------------------
# Behavioral scores
# ---------------------------------------------------------------------------

class TestIncomeStability:
    def test_perfectly_stable_income_scores_100(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("3000", txn_date=date(2024, 2, 1)),
            _credit("3000", txn_date=date(2024, 3, 1)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.income_stability == 100

    def test_wildly_varying_income_scores_below_40(self):
        txns = [
            _credit("100",  txn_date=date(2024, 1, 1)),
            _credit("5000", txn_date=date(2024, 2, 1)),
            _credit("50",   txn_date=date(2024, 3, 1)),
            _credit("8000", txn_date=date(2024, 4, 1)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.income_stability < 40

    def test_moderately_stable_income_mid_range(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("3300", txn_date=date(2024, 2, 1)),
            _credit("2700", txn_date=date(2024, 3, 1)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert 60 <= scores.income_stability <= 100


class TestExpenseVolatility:
    def test_perfectly_stable_expenses_scores_100(self):
        txns = [
            _credit("5000", txn_date=date(2024, 1, 1)),
            _debit("1500", txn_date=date(2024, 1, 15)),
            _credit("5000", txn_date=date(2024, 2, 1)),
            _debit("1500", txn_date=date(2024, 2, 15)),
            _credit("5000", txn_date=date(2024, 3, 1)),
            _debit("1500", txn_date=date(2024, 3, 15)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.expense_volatility == 100

    def test_wildly_varying_expenses_scores_below_40(self):
        txns = [
            _credit("10000", txn_date=date(2024, 1, 1)),
            _debit("50",   txn_date=date(2024, 1, 15)),
            _debit("5000", txn_date=date(2024, 2, 15)),
            _debit("20",   txn_date=date(2024, 3, 15)),
            _debit("6000", txn_date=date(2024, 4, 15)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.expense_volatility < 40


class TestSavingsTrajectory:
    def test_improving_monthly_net_scores_above_60(self):
        # Jan net -200, Feb net 500 → improving
        txns = [
            _credit("800",  txn_date=date(2024, 1, 1)),
            _debit("1000",  txn_date=date(2024, 1, 15)),
            _credit("3000", txn_date=date(2024, 2, 1)),
            _debit("2500",  txn_date=date(2024, 2, 15)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.savings_trajectory > 60

    def test_consistently_negative_scores_below_40(self):
        txns = [
            _credit("500", txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 1, 15)),
            _credit("500", txn_date=date(2024, 2, 1)),
            _debit("1000", txn_date=date(2024, 2, 15)),
            _credit("500", txn_date=date(2024, 3, 1)),
            _debit("1000", txn_date=date(2024, 3, 15)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.savings_trajectory < 40

    def test_single_month_returns_50(self):
        txns = [_credit("3000"), _debit("1000")]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.savings_trajectory == 50


class TestLiquidityHealth:
    def test_no_balance_data_returns_50(self):
        txns = [_credit("3000"), _debit("1000")]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.liquidity_health == 50

    def test_always_above_threshold_scores_100(self):
        # avg_monthly_expenses will be 1000; min balance is 5000 each month → fine
        txns = [
            _txn("1000", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="5000"),
            _txn("1000", TransactionType.DEBIT, txn_date=date(2024, 2, 10), balance_after="5000"),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.liquidity_health == 100

    def test_balance_below_threshold_reduces_score(self):
        # avg expenses ~1000, but balance dips to 100 each month
        txns = [
            _txn("1000", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="100"),
            _txn("1000", TransactionType.DEBIT, txn_date=date(2024, 2, 10), balance_after="100"),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        assert scores.liquidity_health == 0


class TestOverallScore:
    def test_overall_is_weighted_average(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 1, 15)),
        ]
        m = _compute_metrics(txns)
        scores = compute_behavioral_scores(txns, m)
        expected = round(
            scores.income_stability  * 0.30
            + scores.expense_volatility * 0.20
            + scores.savings_trajectory * 0.25
            + scores.liquidity_health   * 0.15
            + scores.payment_regularity * 0.10
        )
        assert scores.overall == expected

    def test_overall_within_bounds(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 1, 15)),
        ]
        m, scores = analyze(txns)
        assert 0 <= scores.overall <= 100


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_transactions_all_scores_50(self):
        _, scores = analyze([])
        assert scores.income_stability  == 50
        assert scores.expense_volatility == 50
        assert scores.savings_trajectory == 50
        assert scores.liquidity_health   == 50
        assert scores.payment_regularity == 50
        assert scores.overall == 50

    def test_single_transaction_credit(self):
        txns = [_credit("5000")]
        m, scores = analyze(txns)
        assert m.total_income == Decimal("5000")
        assert m.total_expenses == Decimal("0")
        assert m.net_cashflow == Decimal("5000")

    def test_expense_to_income_ratio_zero_income(self):
        txns = [_debit("500")]
        m = _compute_metrics(txns)
        assert m.expense_to_income_ratio == Decimal("0")

    def test_all_same_category(self):
        txns = [
            _debit("100", category=TransactionCategory.DINING),
            _debit("200", category=TransactionCategory.DINING),
            _debit("150", category=TransactionCategory.DINING),
        ]
        m = _compute_metrics(txns)
        assert len(m.top_expense_categories) == 1
        assert "dining" in m.top_expense_categories

    def test_transactions_out_of_order_sorted(self):
        txns = [
            _credit("3000", txn_date=date(2024, 3, 1)),
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("3000", txn_date=date(2024, 2, 1)),
        ]
        m = _compute_metrics(txns)
        months = [b.month for b in m.monthly_breakdown]
        assert months == ["2024-01", "2024-02", "2024-03"]


# ---------------------------------------------------------------------------
# Risk flags  (use detect_flags directly now that analyze() returns BehavioralScores)
# ---------------------------------------------------------------------------

class TestHighExpenseRatio:
    def test_no_flag_below_threshold(self):
        txns = [_credit("3000"), _debit("1000")]
        codes = [f.code for f in _flags(txns)]
        assert "HIGH_EXPENSE_RATIO" not in codes

    def test_medium_flag_at_90_percent(self):
        txns = [_credit("1000"), _debit("900")]
        flag = next((f for f in _flags(txns) if f.code == "HIGH_EXPENSE_RATIO"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_high_flag_when_expenses_exceed_income(self):
        txns = [_credit("1000"), _debit("1100")]
        flag = next((f for f in _flags(txns) if f.code == "HIGH_EXPENSE_RATIO"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH


class TestNoRegularIncome:
    def test_flag_when_no_salary(self):
        txns = [_debit("500"), _credit("200", category=TransactionCategory.TRANSFER)]
        codes = [f.code for f in _flags(txns)]
        assert "NO_REGULAR_INCOME" in codes

    def test_no_flag_when_salary_present(self):
        txns = [_credit("3000", category=TransactionCategory.SALARY), _debit("1000")]
        codes = [f.code for f in _flags(txns)]
        assert "NO_REGULAR_INCOME" not in codes

    def test_irregular_income_when_month_missing_salary(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY, txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 2, 15)),  # Feb has no salary
        ]
        codes = [f.code for f in _flags(txns)]
        assert "IRREGULAR_INCOME" in codes


class TestNegativeCashflow:
    def test_no_flag_when_positive(self):
        txns = [_credit("3000"), _debit("1000")]
        assert all(f.code != "NEGATIVE_CASHFLOW" for f in _flags(txns))

    def test_medium_flag_for_one_negative_month(self):
        txns = [_credit("500"), _debit("1000")]
        flag = next((f for f in _flags(txns) if f.code == "NEGATIVE_CASHFLOW"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_high_flag_for_two_negative_months(self):
        txns = [
            _credit("500", txn_date=date(2024, 1, 1)),
            _debit("1000", txn_date=date(2024, 1, 15)),
            _credit("500", txn_date=date(2024, 2, 1)),
            _debit("1000", txn_date=date(2024, 2, 15)),
        ]
        flag = next((f for f in _flags(txns) if f.code == "NEGATIVE_CASHFLOW"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH


class TestGamblingDetected:
    def test_flag_when_gambling_present(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY),
            _debit("200", category=TransactionCategory.GAMBLING, description="DRAFTKINGS"),
        ]
        flag = next((f for f in _flags(txns) if f.code == "GAMBLING_ACTIVITY"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH

    def test_no_flag_without_gambling(self):
        txns = [_credit("3000"), _debit("500")]
        assert all(f.code != "GAMBLING_ACTIVITY" for f in _flags(txns))


class TestHighAtmWithdrawals:
    def test_flag_when_atm_over_10_percent(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY),
            _debit("800", category=TransactionCategory.ATM),
            _debit("200", category=TransactionCategory.OTHER),
        ]
        codes = [f.code for f in _flags(txns)]
        assert "HIGH_ATM_WITHDRAWALS" in codes

    def test_no_flag_when_atm_low(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY),
            _debit("50", category=TransactionCategory.ATM),
            _debit("1000", category=TransactionCategory.OTHER),
        ]
        assert all(f.code != "HIGH_ATM_WITHDRAWALS" for f in _flags(txns))


class TestLoanBurden:
    def test_flag_when_loans_exceed_40_percent(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY),
            _debit("1500", category=TransactionCategory.LOAN_PAYMENT),
        ]
        codes = [f.code for f in _flags(txns)]
        assert "HIGH_LOAN_BURDEN" in codes

    def test_no_flag_when_loans_low(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY),
            _debit("500", category=TransactionCategory.LOAN_PAYMENT),
        ]
        assert all(f.code != "HIGH_LOAN_BURDEN" for f in _flags(txns))


class TestFlagEvidence:
    def test_all_flags_have_evidence(self):
        txns = [
            _credit("500"),
            _debit("600", category=TransactionCategory.GAMBLING),
        ]
        flags = _flags(txns)
        for flag in flags:
            assert len(flag.evidence) >= 1

    def test_flag_has_code_level_description(self):
        txns = [_credit("1000"), _debit("1100")]
        for flag in _flags(txns):
            assert flag.code
            assert flag.level in RiskLevel
            assert flag.description
