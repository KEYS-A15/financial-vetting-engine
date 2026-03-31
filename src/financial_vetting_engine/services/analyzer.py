import math
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

from financial_vetting_engine.schemas.flags import RiskFlag, RiskLevel
from financial_vetting_engine.schemas.metrics import FinancialMetrics, MonthlyBreakdown
from financial_vetting_engine.schemas.scores import BehavioralScores
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType

# ---------------------------------------------------------------------------
# Internal precision helper
# ---------------------------------------------------------------------------

_TWO = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def _compute_metrics(transactions: list[Transaction]) -> FinancialMetrics:
    transactions = sorted(transactions, key=lambda t: t.date)

    total_income    = Decimal("0")
    total_expenses  = Decimal("0")
    largest_expense = Decimal("0")
    largest_credit  = Decimal("0")
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    nsf_count = 0
    balance_after_values: list[Decimal] = []

    monthly: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expenses": Decimal("0")}
    )

    for txn in transactions:
        month_key = txn.date.strftime("%Y-%m")
        if txn.transaction_type == TransactionType.CREDIT:
            total_income += txn.amount
            monthly[month_key]["income"] += txn.amount
            if txn.amount > largest_credit:
                largest_credit = txn.amount
        else:
            total_expenses += txn.amount
            monthly[month_key]["expenses"] += txn.amount
            category_totals[txn.category.value] += txn.amount
            if txn.amount > largest_expense:
                largest_expense = txn.amount

        if txn.balance_after is not None:
            balance_after_values.append(txn.balance_after)
            if txn.balance_after < 0:
                nsf_count += 1

    num_months = max(len(monthly), 1)
    avg_monthly_income   = _q(total_income   / num_months)
    avg_monthly_expenses = _q(total_expenses / num_months)

    expense_to_income = (
        _q(total_expenses / total_income) if total_income > 0 else Decimal("0")
    )

    monthly_breakdown = [
        MonthlyBreakdown(
            month=month,
            total_income=_q(data["income"]),
            total_expenses=_q(data["expenses"]),
            net=_q(data["income"] - data["expenses"]),
        )
        for month, data in sorted(monthly.items())
    ]

    top_expense_categories = dict(
        sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    )

    avg_daily_balance = (
        _q(sum(balance_after_values) / len(balance_after_values))
        if balance_after_values else None
    )

    return FinancialMetrics(
        total_income=_q(total_income),
        total_expenses=_q(total_expenses),
        net_cashflow=_q(total_income - total_expenses),
        avg_monthly_income=avg_monthly_income,
        avg_monthly_expenses=avg_monthly_expenses,
        expense_to_income_ratio=expense_to_income,
        largest_single_expense=_q(largest_expense),
        largest_single_credit=_q(largest_credit),
        top_expense_categories={k: _q(v) for k, v in top_expense_categories.items()},
        monthly_breakdown=monthly_breakdown,
        transaction_count=len(transactions),
        nsf_count=nsf_count,
        months_analyzed=len(monthly),
        avg_daily_balance=avg_daily_balance,
    )


def compute_metrics(transactions: list[Transaction]) -> FinancialMetrics:
    """Public wrapper — sorts by date, computes all metrics."""
    return _compute_metrics(transactions)


# ---------------------------------------------------------------------------
# Behavioral scores
# ---------------------------------------------------------------------------

def _cv(values: list[Decimal]) -> float:
    """Coefficient of variation (std_dev / mean). Returns 0.0 if mean is 0."""
    if not values:
        return 0.0
    n = len(values)
    mean = sum(float(v) for v in values) / n
    if mean == 0.0:
        return 0.0
    variance = sum((float(v) - mean) ** 2 for v in values) / n
    return math.sqrt(variance) / mean


def compute_behavioral_scores(
    transactions: list[Transaction],
    metrics: FinancialMetrics,
) -> BehavioralScores:
    if not transactions:
        return BehavioralScores(
            income_stability=50,
            expense_volatility=50,
            savings_trajectory=50,
            liquidity_health=50,
            payment_regularity=50,
            overall=50,
        )

    # Rebuild monthly income/expense buckets from sorted transactions
    monthly: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expenses": Decimal("0")}
    )
    for txn in sorted(transactions, key=lambda t: t.date):
        month_key = txn.date.strftime("%Y-%m")
        if txn.transaction_type == TransactionType.CREDIT:
            monthly[month_key]["income"] += txn.amount
        else:
            monthly[month_key]["expenses"] += txn.amount

    sorted_months = sorted(monthly.keys())
    num_months = len(sorted_months)

    monthly_incomes  = [monthly[m]["income"]   for m in sorted_months]
    monthly_expenses = [monthly[m]["expenses"] for m in sorted_months]

    # -- income_stability: CV=0 → 100, CV≥1 → 0, linear
    cv_income = _cv(monthly_incomes)
    income_stability = max(0, min(100, int((1.0 - cv_income) * 100)))

    # -- expense_volatility: same formula
    cv_expense = _cv(monthly_expenses)
    expense_volatility = max(0, min(100, int((1.0 - cv_expense) * 100)))

    # -- savings_trajectory
    nets = [b.net for b in metrics.monthly_breakdown]  # already sorted ascending
    if len(nets) < 2:
        savings_trajectory = 50
    else:
        all_negative = all(n < 0 for n in nets)
        # Split into first-half vs last-half so 2-month case compares month1 vs month2
        half = max(1, len(nets) // 2)
        first_avg = float(sum(nets[:half])) / half
        last_avg  = float(sum(nets[-half:])) / half

        if all_negative:
            savings_trajectory = 35 if last_avg > first_avg else 20
        elif last_avg > first_avg:
            denom = abs(first_avg) + 1.0
            improvement = (last_avg - first_avg) / denom
            savings_trajectory = min(100, 50 + int(improvement * 50))
        elif last_avg < first_avg:
            denom = abs(first_avg) + 1.0
            decline = (first_avg - last_avg) / denom
            savings_trajectory = max(41, 50 - int(decline * 20))
        else:
            savings_trajectory = 50

    # -- liquidity_health
    monthly_balances: dict[str, list[Decimal]] = defaultdict(list)
    for txn in transactions:
        if txn.balance_after is not None:
            monthly_balances[txn.date.strftime("%Y-%m")].append(txn.balance_after)

    if not monthly_balances:
        liquidity_health = 50
    else:
        avg_expenses = metrics.avg_monthly_expenses
        bad_months = sum(
            1 for balances in monthly_balances.values()
            if min(balances) < avg_expenses
        )
        ratio = bad_months / len(monthly_balances)
        liquidity_health = max(0, int((1.0 - ratio) * 100))

    # -- payment_regularity
    if num_months < 2:
        payment_regularity = 50
    else:
        cat_month_amounts: dict[str, dict[str, list[Decimal]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for txn in transactions:
            if txn.transaction_type == TransactionType.DEBIT:
                cat_month_amounts[txn.category.value][txn.date.strftime("%Y-%m")].append(txn.amount)

        regularity_scores: list[float] = []
        for cat, month_to_amts in cat_month_amounts.items():
            if len(month_to_amts) < 2:
                continue
            monthly_maxes = [max(amts) for amts in month_to_amts.values()]
            mean_amount = sum(monthly_maxes) / len(monthly_maxes)
            if mean_amount == 0:
                continue
            consistent = sum(
                1 for a in monthly_maxes
                if abs(a - mean_amount) / mean_amount <= Decimal("0.10")
            )
            coverage    = len(month_to_amts) / num_months
            consistency = consistent / len(monthly_maxes)
            regularity_scores.append(coverage * consistency * 100)

        payment_regularity = (
            min(100, int(sum(regularity_scores) / len(regularity_scores)))
            if regularity_scores else 50
        )

    # -- overall weighted average
    overall = round(
        income_stability  * 0.30
        + expense_volatility  * 0.20
        + savings_trajectory  * 0.25
        + liquidity_health    * 0.15
        + payment_regularity  * 0.10
    )

    return BehavioralScores(
        income_stability=income_stability,
        expense_volatility=expense_volatility,
        savings_trajectory=savings_trajectory,
        liquidity_health=liquidity_health,
        payment_regularity=payment_regularity,
        overall=overall,
    )


# ---------------------------------------------------------------------------
# Risk flag detectors — plugin pattern (each returns RiskFlag | None)
# ---------------------------------------------------------------------------

_FlagDetector = Callable[[list[Transaction], FinancialMetrics], RiskFlag | None]
_DETECTORS: list[_FlagDetector] = []


def _detector(fn: _FlagDetector) -> _FlagDetector:
    _DETECTORS.append(fn)
    return fn


@_detector
def _high_expense_ratio(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    ratio = metrics.expense_to_income_ratio
    if ratio >= Decimal("0.9"):
        level = RiskLevel.HIGH if ratio >= Decimal("1.0") else RiskLevel.MEDIUM
        return RiskFlag(
            code="HIGH_EXPENSE_RATIO",
            level=level,
            description="Expenses are very close to or exceed income.",
            evidence=[
                f"Expense-to-income ratio: {ratio:.2f}",
                f"Total income: ${metrics.total_income:,.2f}",
                f"Total expenses: ${metrics.total_expenses:,.2f}",
            ],
        )
    return None


@_detector
def _no_regular_income(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    salary_txns = [t for t in txns if t.category == TransactionCategory.SALARY]
    if not salary_txns:
        return RiskFlag(
            code="NO_REGULAR_INCOME",
            level=RiskLevel.HIGH,
            description="No identifiable salary or payroll deposits found.",
            evidence=["Zero transactions matched SALARY category patterns (PAYROLL, DIRECT DEP, GUSTO, ADP, etc.)"],
        )
    months_with_salary = {t.date.strftime("%Y-%m") for t in salary_txns}
    all_months = {b.month for b in metrics.monthly_breakdown}
    missing = sorted(all_months - months_with_salary)
    if missing:
        return RiskFlag(
            code="IRREGULAR_INCOME",
            level=RiskLevel.MEDIUM,
            description="Salary deposits missing in some months.",
            evidence=[f"No salary detected in: {', '.join(missing)}"],
        )
    return None


@_detector
def _negative_cashflow(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    negative_months = [b for b in metrics.monthly_breakdown if b.net < 0]
    if not negative_months:
        return None
    level = RiskLevel.HIGH if len(negative_months) >= 2 else RiskLevel.MEDIUM
    return RiskFlag(
        code="NEGATIVE_CASHFLOW",
        level=level,
        description="Expenses exceeded income in one or more months.",
        evidence=[
            f"{b.month}: income ${b.total_income:,.2f}, expenses ${b.total_expenses:,.2f}, net ${b.net:,.2f}"
            for b in negative_months
        ],
    )


@_detector
def _large_single_transaction(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    threshold = metrics.avg_monthly_expenses * Decimal("0.5")
    large = [t for t in txns if t.transaction_type == TransactionType.DEBIT and t.amount >= threshold and threshold > 0]
    if len(large) >= 2:
        return RiskFlag(
            code="LARGE_TRANSACTIONS",
            level=RiskLevel.MEDIUM,
            description=f"Multiple transactions exceed 50% of avg monthly expenses (${threshold:,.2f}).",
            evidence=[
                f"{t.date} — {t.description[:60]}: ${t.amount:,.2f}"
                for t in sorted(large, key=lambda x: x.amount, reverse=True)[:5]
            ],
        )
    return None


@_detector
def _gambling_detected(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    gambling = [t for t in txns if t.category == TransactionCategory.GAMBLING]
    if not gambling:
        return None
    total = sum(t.amount for t in gambling)
    return RiskFlag(
        code="GAMBLING_ACTIVITY",
        level=RiskLevel.HIGH,
        description="Gambling transactions detected.",
        evidence=[
            f"Count: {len(gambling)} transactions, total: ${total:,.2f}",
            *[f"{t.date} — {t.description[:60]}: ${t.amount:,.2f}" for t in gambling[:3]],
        ],
    )


@_detector
def _high_atm_withdrawals(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    atm = [t for t in txns if t.category == TransactionCategory.ATM]
    if not atm:
        return None
    total = sum(t.amount for t in atm)
    pct = (total / metrics.total_expenses * 100) if metrics.total_expenses > 0 else Decimal("0")
    if pct >= Decimal("10"):
        return RiskFlag(
            code="HIGH_ATM_WITHDRAWALS",
            level=RiskLevel.MEDIUM,
            description="ATM/cash withdrawals represent a significant portion of expenses.",
            evidence=[
                f"ATM total: ${total:,.2f} ({pct:.1f}% of expenses)",
                f"Count: {len(atm)} withdrawals",
            ],
        )
    return None


@_detector
def _loan_burden(txns: list[Transaction], metrics: FinancialMetrics) -> RiskFlag | None:
    loans = [t for t in txns if t.category == TransactionCategory.LOAN_PAYMENT]
    if not loans:
        return None
    total = sum(t.amount for t in loans)
    pct = (total / metrics.total_income * 100) if metrics.total_income > 0 else Decimal("0")
    if pct >= Decimal("40"):
        return RiskFlag(
            code="HIGH_LOAN_BURDEN",
            level=RiskLevel.HIGH,
            description="Loan/debt payments consume a large share of income.",
            evidence=[
                f"Loan total: ${total:,.2f} ({pct:.1f}% of income)",
                f"Count: {len(loans)} payments",
            ],
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_flags(transactions: list[Transaction], metrics: FinancialMetrics) -> list[RiskFlag]:
    """Run all risk flag detectors against pre-computed metrics."""
    return [flag for det in _DETECTORS if (flag := det(transactions, metrics))]


def analyze(transactions: list[Transaction]) -> tuple[FinancialMetrics, BehavioralScores]:
    """
    Compute FinancialMetrics and BehavioralScores from a list of Transactions.
    Returns (metrics, scores).
    """
    metrics = _compute_metrics(transactions)
    scores  = compute_behavioral_scores(transactions, metrics)
    return metrics, scores
