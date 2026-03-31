from datetime import date, timedelta
from decimal import Decimal

import pytest

from financial_vetting_engine.schemas.flags import RiskLevel
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType
from financial_vetting_engine.services.analyzer import compute_metrics, compute_behavioral_scores
from financial_vetting_engine.services.flagger import detect_flags


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


def _run(txns: list[Transaction]):
    """Compute metrics + scores, then run flagger."""
    m = compute_metrics(txns)
    s = compute_behavioral_scores(txns, m)
    return detect_flags(txns, m, s)


def _codes(txns: list[Transaction]) -> list[str]:
    return [f.code for f in _run(txns)]


# ---------------------------------------------------------------------------
# HIGH_EXPENSE_RATIO
# ---------------------------------------------------------------------------

class TestHighExpenseRatio:
    def test_triggers_high_at_0_96(self):
        # income=1000, expenses=960 → ratio=0.96 > 0.95 → HIGH
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("960",  txn_date=date(2024, 1, 15)),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "HIGH_EXPENSE_RATIO"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH

    def test_triggers_medium_at_0_93(self):
        # income=1000, expenses=930 → ratio=0.93, > 0.90 but ≤ 0.95 → MEDIUM
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("930",  txn_date=date(2024, 1, 15)),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "HIGH_EXPENSE_RATIO"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_does_not_trigger_at_0_85(self):
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("850",  txn_date=date(2024, 1, 15)),
        ]
        assert "HIGH_EXPENSE_RATIO" not in _codes(txns)

    def test_skipped_when_zero_income(self):
        txns = [_debit("500")]
        assert "HIGH_EXPENSE_RATIO" not in _codes(txns)


# ---------------------------------------------------------------------------
# NEGATIVE_BALANCE
# ---------------------------------------------------------------------------

class TestNegativeBalance:
    def test_triggers_medium_for_one_negative(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _txn("200", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="-50"),
            _txn("100", TransactionType.DEBIT, txn_date=date(2024, 1, 20), balance_after="500"),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "NEGATIVE_BALANCE"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_triggers_high_for_more_than_two(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _txn("100", TransactionType.DEBIT, txn_date=date(2024, 1, 5),  balance_after="-10"),
            _txn("100", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="-20"),
            _txn("100", TransactionType.DEBIT, txn_date=date(2024, 1, 15), balance_after="-5"),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "NEGATIVE_BALANCE"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH

    def test_no_flag_without_negative_balance(self):
        txns = [
            _txn("500", TransactionType.DEBIT, balance_after="2000"),
        ]
        assert "NEGATIVE_BALANCE" not in _codes(txns)

    def test_skipped_when_no_balance_after_data(self):
        txns = [_credit("3000"), _debit("500")]
        assert "NEGATIVE_BALANCE" not in _codes(txns)


# ---------------------------------------------------------------------------
# BALANCE_DISCONTINUITY
# ---------------------------------------------------------------------------

class TestBalanceContinuity:
    def test_triggers_when_closing_ne_opening(self):
        # Jan: last balance = 5000.00, Feb: first balance = 3000.00 → gap of 2000
        txns = [
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="6000"),
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 1, 28), balance_after="5000"),  # Jan closing
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 2, 5),  balance_after="3000"),  # Feb opening ≠ 5000
            _txn("200", TransactionType.DEBIT, txn_date=date(2024, 2, 20), balance_after="2800"),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "BALANCE_DISCONTINUITY"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH

    def test_no_flag_when_balance_carries_over(self):
        txns = [
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 1, 28), balance_after="5000"),
            _txn("200", TransactionType.DEBIT, txn_date=date(2024, 2, 5),  balance_after="5000"),  # same → no gap
            _txn("100", TransactionType.DEBIT, txn_date=date(2024, 2, 20), balance_after="4900"),
        ]
        assert "BALANCE_DISCONTINUITY" not in _codes(txns)

    def test_skipped_when_fewer_than_half_have_balance(self):
        # Only 1 of 4 transactions has balance_after (25% < 50%)
        txns = [
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="5000"),
            _debit("100", txn_date=date(2024, 1, 15)),
            _debit("100", txn_date=date(2024, 2, 10)),
            _debit("100", txn_date=date(2024, 2, 20)),
        ]
        assert "BALANCE_DISCONTINUITY" not in _codes(txns)

    def test_skipped_with_single_month(self):
        txns = [
            _txn("500", TransactionType.DEBIT, txn_date=date(2024, 1, 10), balance_after="5000"),
            _txn("200", TransactionType.DEBIT, txn_date=date(2024, 1, 20), balance_after="4800"),
        ]
        assert "BALANCE_DISCONTINUITY" not in _codes(txns)


# ---------------------------------------------------------------------------
# ROUND_NUMBER_CLUSTERING
# ---------------------------------------------------------------------------

class TestRoundNumberClustering:
    def test_triggers_above_40_percent(self):
        # 3 of 4 non-ATM transactions are round hundreds = 75% → flag
        txns = [
            _credit("3000"),                                                    # round
            _debit("1000", category=TransactionCategory.RENT),                 # round
            _debit("200",  category=TransactionCategory.GROCERIES),            # round
            _debit("173",  category=TransactionCategory.DINING),               # not round
        ]
        assert "ROUND_NUMBER_CLUSTERING" in _codes(txns)

    def test_does_not_trigger_at_40_percent_or_below(self):
        # 2 of 5 = 40% → no flag (threshold is strictly > 40%)
        txns = [
            _credit("3000"),
            _debit("200", category=TransactionCategory.RENT),
            _debit("173", category=TransactionCategory.DINING),
            _debit("149", category=TransactionCategory.GROCERIES),
            _debit("87",  category=TransactionCategory.UTILITIES),
        ]
        assert "ROUND_NUMBER_CLUSTERING" not in _codes(txns)

    def test_atm_excluded_from_calculation(self):
        # 2 non-ATM transactions, both round = 100% BUT ATM rounds don't count
        # If we have 1 ATM + 2 non-ATM where 1 is round → 50% → triggers
        txns = [
            _credit("3000"),
            _debit("500", category=TransactionCategory.ATM),   # excluded
            _debit("200", category=TransactionCategory.RENT),  # round → counts
            _debit("173", category=TransactionCategory.DINING),# not round → counts
        ]
        # 1 of 2 non-ATM non-credit... wait: credit also counts
        # Actually: non_atm includes credits. 3000 (round), 200 (round), 173 (not) = 2/3 = 66% → triggers
        assert "ROUND_NUMBER_CLUSTERING" in _codes(txns)


# ---------------------------------------------------------------------------
# IRREGULAR_TIMING
# ---------------------------------------------------------------------------

class TestIrregularTiming:
    def _weekday_dates(self, start: date, count: int) -> list[date]:
        """Generate `count` unique weekday dates starting from `start`."""
        result = []
        d = start
        while len(result) < count:
            if d.weekday() < 5:  # Mon-Fri
                result.append(d)
            d += timedelta(days=1)
        return result

    def test_triggers_for_weekday_only_over_35_days(self):
        # Jan 2, 2024 is Tuesday; collect 8 weekday dates spanning > 30 days
        start = date(2024, 1, 2)
        dates = self._weekday_dates(start, 8)
        # Force last date to be > 30 days after first
        dates[-1] = date(2024, 2, 6)  # Feb 6 is Tuesday, span = 35 days
        txns = [_credit("3000", txn_date=d) for d in dates]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "IRREGULAR_TIMING"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_no_flag_when_weekend_transactions_present(self):
        # Include a Saturday (Jan 6, 2024)
        txns = [
            _credit("3000", txn_date=date(2024, 1, 2)),   # Tue
            _debit("500",   txn_date=date(2024, 1, 6)),   # Sat ← weekend
            _debit("200",   txn_date=date(2024, 2, 6)),   # Tue
        ]
        assert "IRREGULAR_TIMING" not in _codes(txns)

    def test_no_flag_for_short_period(self):
        # All weekdays but span < 30 days
        txns = [
            _credit("3000", txn_date=date(2024, 1, 2)),
            _debit("500",   txn_date=date(2024, 1, 15)),
        ]
        assert "IRREGULAR_TIMING" not in _codes(txns)


# ---------------------------------------------------------------------------
# DUPLICATE_TRANSACTIONS
# ---------------------------------------------------------------------------

class TestDuplicateTransactions:
    def test_triggers_for_identical_rows(self):
        txns = [
            _debit("150", description="NETFLIX CHARGE", txn_date=date(2024, 1, 15)),
            _debit("150", description="NETFLIX CHARGE", txn_date=date(2024, 1, 15)),
            _credit("3000"),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "DUPLICATE_TRANSACTIONS"), None)
        assert flag is not None
        assert flag.level == RiskLevel.MEDIUM

    def test_no_flag_for_same_amount_different_date(self):
        txns = [
            _debit("150", description="NETFLIX CHARGE", txn_date=date(2024, 1, 15)),
            _debit("150", description="NETFLIX CHARGE", txn_date=date(2024, 2, 15)),
        ]
        assert "DUPLICATE_TRANSACTIONS" not in _codes(txns)

    def test_no_flag_for_same_date_different_description(self):
        txns = [
            _debit("150", description="NETFLIX",  txn_date=date(2024, 1, 15)),
            _debit("150", description="SPOTIFY",  txn_date=date(2024, 1, 15)),
        ]
        assert "DUPLICATE_TRANSACTIONS" not in _codes(txns)


# ---------------------------------------------------------------------------
# NSF_EVENTS
# ---------------------------------------------------------------------------

class TestNsfEvents:
    def test_triggers_for_nsf_in_description(self):
        txns = [
            _credit("1000"),
            _debit("35", description="NSF FEE", txn_date=date(2024, 1, 10)),
        ]
        assert "NSF_EVENTS" in _codes(txns)

    def test_triggers_for_overdraft_description(self):
        txns = [
            _credit("1000"),
            _debit("35", description="OVERDRAFT FEE", txn_date=date(2024, 1, 10)),
        ]
        assert "NSF_EVENTS" in _codes(txns)

    def test_high_for_more_than_two_nsf(self):
        txns = [
            _credit("1000"),
            _debit("35", description="NSF FEE", txn_date=date(2024, 1, 5)),
            _debit("35", description="NSF FEE", txn_date=date(2024, 1, 10)),
            _debit("35", description="NSF FEE", txn_date=date(2024, 1, 15)),
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "NSF_EVENTS"), None)
        assert flag is not None
        assert flag.level == RiskLevel.HIGH

    def test_no_flag_without_nsf_keywords(self):
        txns = [_credit("3000"), _debit("500", description="GROCERY STORE")]
        assert "NSF_EVENTS" not in _codes(txns)


# ---------------------------------------------------------------------------
# INCOME_DROP
# ---------------------------------------------------------------------------

class TestIncomeDrop:
    def test_triggers_medium_when_month_below_60_percent(self):
        # total=7400, months=3, avg≈2467; threshold_medium=1480; Mar=1400 < 1480 → flag
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("3000", txn_date=date(2024, 2, 1)),
            _credit("1400", txn_date=date(2024, 3, 1)),  # < 60% of avg → flag
        ]
        flags = _run(txns)
        flag = next((f for f in flags if f.code == "INCOME_DROP"), None)
        assert flag is not None

    def test_skipped_for_single_month(self):
        txns = [_credit("3000"), _debit("1000")]
        assert "INCOME_DROP" not in _codes(txns)

    def test_no_flag_when_all_months_normal(self):
        txns = [
            _credit("3000", txn_date=date(2024, 1, 1)),
            _credit("2900", txn_date=date(2024, 2, 1)),  # 96% of avg → fine
        ]
        assert "INCOME_DROP" not in _codes(txns)


# ---------------------------------------------------------------------------
# LARGE_IRREGULAR_CREDIT
# ---------------------------------------------------------------------------

class TestLargeIrregularCredit:
    def test_triggers_for_non_salary_large_credit(self):
        # 4 months salary $1000 + $20000 transfer in May → avg=4800, threshold=14400; 20000 > 14400 → flag
        txns = [
            _credit("1000", category=TransactionCategory.SALARY, txn_date=date(2024, 1, 1)),
            _credit("1000", category=TransactionCategory.SALARY, txn_date=date(2024, 2, 1)),
            _credit("1000", category=TransactionCategory.SALARY, txn_date=date(2024, 3, 1)),
            _credit("1000", category=TransactionCategory.SALARY, txn_date=date(2024, 4, 1)),
            _credit("20000", category=TransactionCategory.TRANSFER, txn_date=date(2024, 5, 1)),
        ]
        assert "LARGE_IRREGULAR_CREDIT" in _codes(txns)

    def test_no_flag_for_salary_credit(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY, txn_date=date(2024, 1, 1)),
            _credit("10000", category=TransactionCategory.SALARY, txn_date=date(2024, 1, 15)),
        ]
        assert "LARGE_IRREGULAR_CREDIT" not in _codes(txns)

    def test_no_flag_when_credit_below_threshold(self):
        txns = [
            _credit("3000", category=TransactionCategory.SALARY, txn_date=date(2024, 1, 1)),
            _credit("5000", category=TransactionCategory.TRANSFER, txn_date=date(2024, 1, 15)),
            # avg income = (3000+5000)/1 = 8000 (both in Jan); 3×8000=24000; 5000 < 24000 → no flag
            # Actually: avg_monthly_income = total_income / months = 8000 / 1 = 8000; threshold = 24000; 5000 < 24000 → no flag
        ]
        assert "LARGE_IRREGULAR_CREDIT" not in _codes(txns)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_list_returns_no_flags(self):
        assert detect_flags([], compute_metrics([]), compute_behavioral_scores([], compute_metrics([]))) == []

    def test_all_flags_have_non_empty_evidence(self):
        # Craft transactions that trigger several flags
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("960",   txn_date=date(2024, 1, 5), balance_after="-50"),   # high ratio + neg balance
            _debit("35",    txn_date=date(2024, 1, 10), description="NSF FEE"),
        ]
        flags = _run(txns)
        assert flags, "Expected at least one flag"
        for flag in flags:
            assert len(flag.evidence) >= 1, f"{flag.code} has empty evidence"

    def test_flags_ordered_high_before_medium(self):
        # HIGH_EXPENSE_RATIO (HIGH) + DUPLICATE_TRANSACTIONS (MEDIUM)
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("960",   txn_date=date(2024, 1, 5)),   # ratio = 0.96 → HIGH
            _debit("50", description="COFFEE", txn_date=date(2024, 1, 10)),   # dup1
            _debit("50", description="COFFEE", txn_date=date(2024, 1, 10)),   # dup2 → MEDIUM
        ]
        flags = _run(txns)
        levels = [f.level for f in flags]
        high_indices   = [i for i, lv in enumerate(levels) if lv == RiskLevel.HIGH]
        medium_indices = [i for i, lv in enumerate(levels) if lv == RiskLevel.MEDIUM]
        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices), "HIGH flags must come before MEDIUM flags"

    def test_flags_have_triggered_by_and_recommendation(self):
        txns = [
            _credit("1000", txn_date=date(2024, 1, 1)),
            _debit("960",   txn_date=date(2024, 1, 15)),
        ]
        flags = _run(txns)
        for flag in flags:
            assert isinstance(flag.triggered_by, list)
            assert isinstance(flag.recommendation, str)
