"""
Shared pytest configuration and fixtures.

pdfplumber depends on a cryptography DLL that may be blocked by Windows
Application Control in some environments. We stub it before collection so
tests that exercise the real extractor can mock pdfplumber.open themselves.
"""
import sys
from decimal import Decimal
from datetime import date

import pytest

# Stub pdfplumber if the real library cannot be loaded
try:
    import pdfplumber  # noqa: F401
except Exception:
    from unittest.mock import MagicMock
    sys.modules["pdfplumber"] = MagicMock()

from financial_vetting_engine.schemas.transaction import (
    Transaction,
    TransactionType,
    TransactionCategory,
)


@pytest.fixture
def sample_transactions():
    return [
        Transaction(
            date=date(2024, 1, 15),
            description="GUSTO PAYROLL",
            raw_description="GUSTO PAYROLL 01/15",
            amount=Decimal("3200.00"),
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY,
            balance_after=Decimal("4500.00"),
        ),
        Transaction(
            date=date(2024, 1, 17),
            description="RENT PAYMENT",
            raw_description="RENT PAYMENT JAN",
            amount=Decimal("1800.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT,
            balance_after=Decimal("2700.00"),
        ),
        Transaction(
            date=date(2024, 1, 20),
            description="WHOLE FOODS MARKET",
            raw_description="WHOLE FOODS MKT #123",
            amount=Decimal("124.50"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.GROCERIES,
            balance_after=Decimal("2575.50"),
        ),
        Transaction(
            date=date(2024, 1, 22),
            description="DOORDASH",
            raw_description="DOORDASH*ORDER",
            amount=Decimal("34.20"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.DINING,
            balance_after=Decimal("2541.30"),
        ),
        Transaction(
            date=date(2024, 1, 25),
            description="VERIZON WIRELESS",
            raw_description="VERIZON WIRELESS PMT",
            amount=Decimal("85.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.UTILITIES,
            balance_after=Decimal("2456.30"),
        ),
        Transaction(
            date=date(2024, 2, 15),
            description="GUSTO PAYROLL",
            raw_description="GUSTO PAYROLL 02/15",
            amount=Decimal("3200.00"),
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY,
            balance_after=Decimal("5656.30"),
        ),
        Transaction(
            date=date(2024, 2, 17),
            description="RENT PAYMENT",
            raw_description="RENT PAYMENT FEB",
            amount=Decimal("1800.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT,
            balance_after=Decimal("3856.30"),
        ),
        Transaction(
            date=date(2024, 2, 21),
            description="WHOLE FOODS MARKET",
            raw_description="WHOLE FOODS MKT #123",
            amount=Decimal("98.75"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.GROCERIES,
            balance_after=Decimal("3757.55"),
        ),
        Transaction(
            date=date(2024, 3, 15),
            description="GUSTO PAYROLL",
            raw_description="GUSTO PAYROLL 03/15",
            amount=Decimal("3200.00"),
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY,
            balance_after=Decimal("6957.55"),
        ),
        Transaction(
            date=date(2024, 3, 17),
            description="RENT PAYMENT",
            raw_description="RENT PAYMENT MAR",
            amount=Decimal("1800.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT,
            balance_after=Decimal("5157.55"),
        ),
    ]


@pytest.fixture
def high_risk_transactions():
    """Transactions designed to trigger multiple HIGH-level flags."""
    return [
        Transaction(
            date=date(2024, 1, 15),
            description="GUSTO PAYROLL",
            raw_description="GUSTO PAYROLL",
            amount=Decimal("2000.00"),
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY,
            balance_after=Decimal("2100.00"),
        ),
        Transaction(
            date=date(2024, 1, 16),
            description="RENT PAYMENT",
            raw_description="RENT PAYMENT",
            amount=Decimal("1900.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT,
            balance_after=Decimal("200.00"),
        ),
        Transaction(
            date=date(2024, 1, 18),
            description="ATM WITHDRAWAL",
            raw_description="ATM CASH WITHDRAWAL",
            amount=Decimal("200.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.ATM,
            balance_after=Decimal("-5.00"),
        ),
        Transaction(
            date=date(2024, 2, 15),
            description="GUSTO PAYROLL",
            raw_description="GUSTO PAYROLL",
            amount=Decimal("800.00"),
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY,
            balance_after=Decimal("795.00"),
        ),
        Transaction(
            date=date(2024, 2, 17),
            description="RENT PAYMENT",
            raw_description="RENT PAYMENT",
            amount=Decimal("1900.00"),
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT,
            balance_after=Decimal("-1105.00"),
        ),
    ]


@pytest.fixture
def empty_transactions():
    return []
