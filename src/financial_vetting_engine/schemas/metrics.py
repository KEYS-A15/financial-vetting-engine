from pydantic import BaseModel
from decimal import Decimal


class MonthlyBreakdown(BaseModel):
    month: str
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal


class FinancialMetrics(BaseModel):
    total_income: Decimal
    total_expenses: Decimal
    net_cashflow: Decimal
    avg_monthly_income: Decimal
    avg_monthly_expenses: Decimal
    expense_to_income_ratio: Decimal
    largest_single_expense: Decimal
    top_expense_categories: dict[str, Decimal]
    monthly_breakdown: list[MonthlyBreakdown]
    transaction_count: int
