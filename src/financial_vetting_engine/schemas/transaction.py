from pydantic import BaseModel
from decimal import Decimal
from datetime import date
from enum import Enum
from typing import Optional


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class TransactionCategory(str, Enum):
    SALARY = "salary"
    RENT = "rent"
    UTILITIES = "utilities"
    GROCERIES = "groceries"
    DINING = "dining"
    TRANSFER = "transfer"
    LOAN_PAYMENT = "loan_payment"
    GAMBLING = "gambling"
    ATM = "atm"
    OTHER = "other"


class Transaction(BaseModel):
    date: date
    description: str
    amount: Decimal
    transaction_type: TransactionType
    category: TransactionCategory
    balance_after: Optional[Decimal] = None
    raw_description: str


class StatementMetadata(BaseModel):
    bank_name: Optional[str] = None
    account_number_last4: Optional[str] = None
    statement_period_start: date
    statement_period_end: date
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    currency: str = "USD"
