from collections import defaultdict
from decimal import Decimal
from typing import Optional

from financial_vetting_engine.schemas.flags import RiskFlag, RiskLevel
from financial_vetting_engine.schemas.metrics import FinancialMetrics
from financial_vetting_engine.schemas.scores import BehavioralScores
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType

_LEVEL_ORDER = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}


# ---------------------------------------------------------------------------
# Financial flags
# ---------------------------------------------------------------------------

def _check_high_expense_ratio(metrics: FinancialMetrics) -> Optional[RiskFlag]:
    if metrics.total_income == 0:
        return None
    ratio = metrics.expense_to_income_ratio
    if ratio <= Decimal("0.90"):
        return None
    level = RiskLevel.HIGH if ratio > Decimal("0.95") else RiskLevel.MEDIUM
    months_evidence = [
        f"{b.month}: income ${b.total_income:,.2f}, expenses ${b.total_expenses:,.2f}"
        for b in metrics.monthly_breakdown
    ]
    return RiskFlag(
        code="HIGH_EXPENSE_RATIO",
        level=level,
        description=f"Expense-to-income ratio is {ratio:.2f}, indicating spending at or near income capacity.",
        evidence=[
            f"Ratio: {ratio:.2f}",
            f"Total income: ${metrics.total_income:,.2f}",
            f"Total expenses: ${metrics.total_expenses:,.2f}",
            *months_evidence,
        ],
        triggered_by=[f"Expense ratio: {ratio:.4f}"],
        recommendation="Review fixed vs discretionary expense split",
    )


def _check_income_instability(
    transactions: list[Transaction],
    scores: BehavioralScores,
) -> Optional[RiskFlag]:
    if scores.income_stability >= 50:
        return None
    level = RiskLevel.HIGH if scores.income_stability < 30 else RiskLevel.MEDIUM

    monthly: dict[str, Decimal] = defaultdict(Decimal)
    for txn in transactions:
        if txn.transaction_type == TransactionType.CREDIT:
            monthly[txn.date.strftime("%Y-%m")] += txn.amount

    monthly_lines = [f"{m}: ${amt:,.2f}" for m, amt in sorted(monthly.items())]
    return RiskFlag(
        code="INCOME_INSTABILITY",
        level=level,
        description=f"Income stability score is {scores.income_stability}/100, indicating inconsistent income.",
        evidence=[f"Income stability score: {scores.income_stability}", *monthly_lines],
        triggered_by=[f"Income stability score: {scores.income_stability}"],
        recommendation="Verify employment status and income source consistency",
    )


def _check_negative_balance(transactions: list[Transaction]) -> Optional[RiskFlag]:
    negative = [t for t in transactions if t.balance_after is not None and t.balance_after < 0]
    if not negative:
        return None
    level = RiskLevel.HIGH if len(negative) > 2 else RiskLevel.MEDIUM
    return RiskFlag(
        code="NEGATIVE_BALANCE",
        level=level,
        description=f"{len(negative)} transaction(s) resulted in a negative account balance.",
        evidence=[
            f"{t.date} — {t.description[:60]}: balance after ${t.balance_after:,.2f}"
            for t in negative
        ],
        triggered_by=[
            f"{t.date} ${t.amount:,.2f} → balance ${t.balance_after:,.2f}"
            for t in negative
        ],
        recommendation="Check for overdraft protection and fee patterns",
    )


def _check_nsf_events(transactions: list[Transaction]) -> Optional[RiskFlag]:
    _NSF_PATTERNS = ("NSF", "NON-SUFFICIENT", "OVERDRAFT", "RETURNED", "INSUFFICIENT FUNDS")
    nsf = [
        t for t in transactions
        if any(p in t.description.upper() for p in _NSF_PATTERNS)
    ]
    if not nsf:
        return None
    level = RiskLevel.HIGH if len(nsf) > 2 else RiskLevel.MEDIUM
    return RiskFlag(
        code="NSF_EVENTS",
        level=level,
        description=f"{len(nsf)} NSF/overdraft event(s) detected in transaction descriptions.",
        evidence=[f"{t.date} — {t.description[:80]}: ${t.amount:,.2f}" for t in nsf],
        triggered_by=[f"{t.date} {t.description[:60]}" for t in nsf],
        recommendation="Review cash flow timing and overdraft frequency",
    )


def _check_large_cash_withdrawals(
    transactions: list[Transaction],
    metrics: FinancialMetrics,
) -> Optional[RiskFlag]:
    atm = [t for t in transactions if t.category == TransactionCategory.ATM]
    if not atm:
        return None

    large_single = [t for t in atm if t.amount > Decimal("500")]
    total_atm    = sum(t.amount for t in atm)
    pct_threshold = metrics.total_expenses * Decimal("0.15")
    over_pct      = pct_threshold > 0 and total_atm > pct_threshold

    if not large_single and not over_pct:
        return None

    level = RiskLevel.HIGH if any(t.amount > Decimal("1000") for t in atm) else RiskLevel.MEDIUM
    evidence: list[str] = [
        f"{t.date} — {t.description[:60]}: ${t.amount:,.2f}"
        for t in large_single
    ]
    if over_pct:
        pct_val = float(total_atm / metrics.total_expenses) * 100
        evidence.append(f"Total ATM: ${total_atm:,.2f} ({pct_val:.1f}% of expenses)")
    if not evidence:
        evidence = [f"Total ATM withdrawals: ${total_atm:,.2f}"]

    return RiskFlag(
        code="LARGE_CASH_WITHDRAWALS",
        level=level,
        description="Significant cash withdrawals detected via ATM transactions.",
        evidence=evidence,
        triggered_by=[f"{t.date} ATM ${t.amount:,.2f}" for t in large_single]
        or [f"Total ATM: ${total_atm:,.2f}"],
        recommendation="Verify cash usage pattern and source of funds",
    )


def _check_income_drop(
    transactions: list[Transaction],
    metrics: FinancialMetrics,
) -> Optional[RiskFlag]:
    if metrics.months_analyzed < 2 or metrics.avg_monthly_income == 0:
        return None

    threshold_medium = metrics.avg_monthly_income * Decimal("0.60")
    threshold_high   = metrics.avg_monthly_income * Decimal("0.40")

    flagged = [b for b in metrics.monthly_breakdown if b.total_income < threshold_medium]
    if not flagged:
        return None

    level = RiskLevel.HIGH if any(b.total_income < threshold_high for b in flagged) else RiskLevel.MEDIUM
    return RiskFlag(
        code="INCOME_DROP",
        level=level,
        description=f"Income dropped below 60% of average in {len(flagged)} month(s).",
        evidence=[
            f"{b.month}: income ${b.total_income:,.2f} vs avg ${metrics.avg_monthly_income:,.2f}"
            for b in flagged
        ],
        triggered_by=[f"{b.month} income ${b.total_income:,.2f}" for b in flagged],
        recommendation="Verify reason for income gap — job change, leave, or gap",
    )


def _check_large_irregular_credits(
    transactions: list[Transaction],
    metrics: FinancialMetrics,
) -> Optional[RiskFlag]:
    if metrics.avg_monthly_income == 0:
        return None

    threshold = metrics.avg_monthly_income * Decimal("3")
    flagged = [
        t for t in transactions
        if t.transaction_type == TransactionType.CREDIT
        and t.category != TransactionCategory.SALARY
        and t.amount > threshold
    ]
    if not flagged:
        return None

    return RiskFlag(
        code="LARGE_IRREGULAR_CREDIT",
        level=RiskLevel.MEDIUM,
        description=f"{len(flagged)} non-salary credit(s) exceed 3× average monthly income (${threshold:,.2f}).",
        evidence=[
            f"{t.date} — {t.description[:60]}: ${t.amount:,.2f} (category: {t.category.value})"
            for t in flagged
        ],
        triggered_by=[f"{t.date} ${t.amount:,.2f} {t.category.value}" for t in flagged],
        recommendation="Verify source of large deposit — gift, asset sale, loan",
    )


# ---------------------------------------------------------------------------
# Authenticity flags
# ---------------------------------------------------------------------------

def _check_balance_continuity(transactions: list[Transaction]) -> Optional[RiskFlag]:
    with_balance = [t for t in transactions if t.balance_after is not None]
    if not transactions or len(with_balance) / len(transactions) <= 0.50:
        return None

    by_month: dict[str, list[Transaction]] = defaultdict(list)
    for t in with_balance:
        by_month[t.date.strftime("%Y-%m")].append(t)

    sorted_months = sorted(by_month.keys())
    if len(sorted_months) < 2:
        return None

    discontinuities: list[str] = []
    triggered: list[str] = []

    for i in range(len(sorted_months) - 1):
        month_a = sorted_months[i]
        month_b = sorted_months[i + 1]
        last_a  = sorted(by_month[month_a], key=lambda t: t.date)[-1]
        first_b = sorted(by_month[month_b], key=lambda t: t.date)[0]
        closing = last_a.balance_after
        opening = first_b.balance_after
        if abs(closing - opening) > Decimal("0.01"):
            discontinuities.append(
                f"{month_a} closing: ${closing:,.2f} → {month_b} opening: ${opening:,.2f}"
            )
            triggered.append(f"{month_a}/{month_b} gap: ${abs(closing - opening):,.2f}")

    if not discontinuities:
        return None

    return RiskFlag(
        code="BALANCE_DISCONTINUITY",
        level=RiskLevel.HIGH,
        description=f"Balance does not carry over at {len(discontinuities)} month boundary/boundaries.",
        evidence=discontinuities,
        triggered_by=triggered,
        recommendation="Possible missing transactions or altered statement",
    )


def _check_round_number_clustering(transactions: list[Transaction]) -> Optional[RiskFlag]:
    non_atm = [t for t in transactions if t.category != TransactionCategory.ATM]
    if not non_atm:
        return None

    round_hundreds = [t for t in non_atm if t.amount % 100 == 0]
    pct = len(round_hundreds) / len(non_atm) * 100

    if pct <= 40:
        return None

    return RiskFlag(
        code="ROUND_NUMBER_CLUSTERING",
        level=RiskLevel.MEDIUM,
        description=f"{pct:.1f}% of non-ATM transactions have round-hundred amounts.",
        evidence=[
            f"{len(round_hundreds)} of {len(non_atm)} non-ATM transactions are round hundreds ({pct:.1f}%)",
        ],
        triggered_by=[f"{t.date} ${t.amount:,.2f}" for t in round_hundreds[:10]],
        recommendation="Unusual concentration of round amounts — manual review advised",
    )


def _check_transaction_timing(transactions: list[Transaction]) -> Optional[RiskFlag]:
    if not transactions:
        return None

    dates = sorted({t.date for t in transactions})
    span_days = (dates[-1] - dates[0]).days

    if span_days < 30:
        return None

    if any(d.weekday() >= 5 for d in dates):  # 5=Sat, 6=Sun
        return None

    return RiskFlag(
        code="IRREGULAR_TIMING",
        level=RiskLevel.MEDIUM,
        description=f"No weekend transactions detected over a {span_days}-day period ({dates[0]} to {dates[-1]}).",
        evidence=[
            f"Date range: {dates[0]} to {dates[-1]} ({span_days} days)",
            f"Total unique transaction dates: {len(dates)}",
            "Zero transactions on Saturday or Sunday",
        ],
        triggered_by=[f"0 weekend transactions over {span_days} days"],
        recommendation="No weekend activity detected — verify statement authenticity",
    )


def _check_duplicate_transactions(transactions: list[Transaction]) -> Optional[RiskFlag]:
    seen: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in transactions:
        seen[(t.date, t.amount, t.description)].append(t)

    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if not dupes:
        return None

    evidence  = []
    triggered = []
    for (d, amt, desc), txns in dupes.items():
        evidence.append(f"{d} — {desc[:60]}: ${amt:,.2f} × {len(txns)}")
        triggered.append(f"{d} ${amt:,.2f} '{desc[:40]}'")

    return RiskFlag(
        code="DUPLICATE_TRANSACTIONS",
        level=RiskLevel.MEDIUM,
        description=f"{len(dupes)} set(s) of exact duplicate transactions found.",
        evidence=evidence,
        triggered_by=triggered,
        recommendation="Verify these are genuine duplicate transactions",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_flags(
    transactions: list[Transaction],
    metrics: FinancialMetrics,
    scores: BehavioralScores,
) -> list[RiskFlag]:
    """
    Run all financial and authenticity detectors.
    Returns flags sorted HIGH → MEDIUM → LOW.
    """
    if not transactions:
        return []

    candidates = [
        _check_high_expense_ratio(metrics),
        _check_income_instability(transactions, scores),
        _check_negative_balance(transactions),
        _check_nsf_events(transactions),
        _check_large_cash_withdrawals(transactions, metrics),
        _check_income_drop(transactions, metrics),
        _check_large_irregular_credits(transactions, metrics),
        _check_balance_continuity(transactions),
        _check_round_number_clustering(transactions),
        _check_transaction_timing(transactions),
        _check_duplicate_transactions(transactions),
    ]

    flags = [f for f in candidates if f is not None]
    return sorted(flags, key=lambda f: _LEVEL_ORDER[f.level])
