from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from .flags import RiskFlag


class PayStubData(BaseModel):
    employer_name: Optional[str] = None
    employee_name: Optional[str] = None
    pay_period_start: Optional[str] = None
    pay_period_end: Optional[str] = None
    pay_date: Optional[str] = None
    gross_pay: Optional[Decimal] = None
    net_pay: Optional[Decimal] = None
    federal_tax: Optional[Decimal] = None
    state_tax: Optional[Decimal] = None
    social_security: Optional[Decimal] = None
    medicare: Optional[Decimal] = None
    other_deductions: Optional[Decimal] = None
    pay_frequency: Optional[str] = None   # weekly, biweekly, semi-monthly, monthly
    ytd_gross: Optional[Decimal] = None


class CorroborationResult(BaseModel):
    pay_stub_provided: bool
    pay_stub_data: Optional[PayStubData] = None
    declared_net_pay: Optional[Decimal] = None
    observed_deposit: Optional[Decimal] = None
    gap_amount: Optional[Decimal] = None
    gap_percent: Optional[Decimal] = None
    employer_name_match: Optional[bool] = None
    pay_frequency_match: Optional[bool] = None
    corroboration_flags: list[RiskFlag] = []
    corroboration_score: int = 50          # 0-100, 100 = perfect match
    notes: list[str] = []
