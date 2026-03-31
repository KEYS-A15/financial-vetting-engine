"""
API integration tests for the /analyze, /health, and /schema/* endpoints.

The full-pipeline tests mock all service calls (extractor → normalizer →
analyzer → flagger → corroborator) so the tests remain hermetic regardless
of whether pdfplumber can open files in the current OS environment.

Validation-only tests (empty file, wrong extension) are truly unit-level
and need no mocking because they fail before any service is invoked.
"""
import io
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from financial_vetting_engine.main import app
from financial_vetting_engine.core.config import settings
from financial_vetting_engine.schemas.corroboration import CorroborationResult
from financial_vetting_engine.schemas.extraction import PageExtraction, RawExtractionResult
from financial_vetting_engine.schemas.flags import RiskFlag, RiskLevel
from financial_vetting_engine.schemas.metrics import FinancialMetrics, MonthlyBreakdown
from financial_vetting_engine.schemas.scores import BehavioralScores
from financial_vetting_engine.schemas.transaction import (
    Transaction,
    TransactionCategory,
    TransactionType,
)

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SAMPLE_TRANSACTIONS = [
    Transaction(
        date=date(2025, 11, 1),
        description="SALARY DEPOSIT",
        amount=Decimal("5000.00"),
        transaction_type=TransactionType.CREDIT,
        category=TransactionCategory.SALARY,
        balance_after=Decimal("5000.00"),
        raw_description="SALARY DEPOSIT",
    ),
    Transaction(
        date=date(2025, 11, 15),
        description="RENT PAYMENT",
        amount=Decimal("1500.00"),
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.RENT,
        balance_after=Decimal("3500.00"),
        raw_description="RENT PAYMENT",
    ),
]

_SAMPLE_METRICS = FinancialMetrics(
    total_income=Decimal("5000.00"),
    total_expenses=Decimal("1500.00"),
    net_cashflow=Decimal("3500.00"),
    avg_monthly_income=Decimal("5000.00"),
    avg_monthly_expenses=Decimal("1500.00"),
    expense_to_income_ratio=Decimal("0.30"),
    largest_single_expense=Decimal("1500.00"),
    largest_single_credit=Decimal("5000.00"),
    top_expense_categories={"rent": Decimal("1500.00")},
    monthly_breakdown=[
        MonthlyBreakdown(
            month="2025-11",
            total_income=Decimal("5000.00"),
            total_expenses=Decimal("1500.00"),
            net=Decimal("3500.00"),
        )
    ],
    transaction_count=2,
    nsf_count=0,
    months_analyzed=1,
)

_SAMPLE_SCORES = BehavioralScores(
    income_stability=85,
    expense_volatility=75,
    savings_trajectory=70,
    liquidity_health=90,
    payment_regularity=80,
    overall=81,
)

_SAMPLE_RAW = RawExtractionResult(
    pages=[
        PageExtraction(
            page_number=1,
            method="text",
            rows=[],
            raw_text="Chase Bank Account ...1234\n01/11/2025 SALARY DEPOSIT 5000.00",
        )
    ],
    page_count=1,
    file_name="statement.pdf",
    file_size_bytes=1000,
)

_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>\nstream\n"
    b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000266 00000 n \n"
    b"0000000360 00000 n \n"
    b"trailer<</Size 6/Root 1 0 R>>\n"
    b"startxref\n430\n%%EOF\n"
)


def _make_ingestor_mock(tmp_path: Path):
    """Return a side_effect function that writes a real temp file."""
    saved: list[Path] = []

    def _save(file, temp_dir):
        dest = tmp_path / f"{uuid.uuid4()}.pdf"
        dest.write_bytes(b"fake")
        saved.append(dest)
        return dest

    return _save, saved


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "app" in data


# ---------------------------------------------------------------------------
# GET /schema/result
# ---------------------------------------------------------------------------

def test_schema_result_returns_valid_json_schema():
    resp = client.get("/schema/result")
    assert resp.status_code == 200
    schema = resp.json()
    assert "properties" in schema
    assert "title" in schema


# ---------------------------------------------------------------------------
# POST /analyze — validation errors (no mocking needed)
# ---------------------------------------------------------------------------

def test_analyze_no_file_returns_422():
    resp = client.post("/analyze")
    assert resp.status_code == 422


def test_analyze_non_pdf_returns_415():
    resp = client.post(
        "/analyze",
        files={"statement": ("report.txt", b"this is not a pdf", "text/plain")},
    )
    assert resp.status_code == 415
    assert "PDF" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /analyze — full pipeline (services mocked)
# ---------------------------------------------------------------------------

def _pipeline_patches(corr_override=None):
    """Context managers that mock the entire service chain."""
    corr = corr_override or CorroborationResult(
        pay_stub_provided=False,
        corroboration_score=50,
        notes=["No pay stub provided — corroboration skipped"],
    )
    return [
        patch(
            "financial_vetting_engine.services.ingestor.validate_and_save",
            side_effect=lambda f, d: Path(f"/tmp/fve/{uuid.uuid4()}.pdf"),
        ),
        patch("financial_vetting_engine.services.ingestor.cleanup"),
        patch(
            "financial_vetting_engine.services.extractor.extract",
            return_value=_SAMPLE_RAW,
        ),
        patch(
            "financial_vetting_engine.services.normalizer.normalize",
            return_value=_SAMPLE_TRANSACTIONS,
        ),
        patch(
            "financial_vetting_engine.services.analyzer.analyze",
            return_value=(_SAMPLE_METRICS, _SAMPLE_SCORES),
        ),
        patch(
            "financial_vetting_engine.services.flagger.detect_flags",
            return_value=[],
        ),
        patch(
            "financial_vetting_engine.services.corroborator.corroborate",
            return_value=corr,
        ),
    ]


def test_analyze_pdf_returns_correct_shape():
    patches = _pipeline_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        resp = client.post(
            "/analyze",
            files={"statement": ("statement.pdf", _MINIMAL_PDF, "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "analysis_id" in data
    assert "processed_at" in data
    assert "processing_time_seconds" in data

    assert len(data["transactions"]) == 2

    # Metrics have Decimal fields (serialised as strings in JSON)
    metrics = data["metrics"]
    assert "total_income" in metrics
    assert "total_expenses" in metrics
    assert "net_cashflow" in metrics

    # Behavioral scores — all five dimensions present
    scores = data["behavioral_scores"]
    for key in ("income_stability", "expense_volatility", "savings_trajectory",
                "liquidity_health", "payment_regularity", "overall"):
        assert key in scores, f"Missing score: {key}"

    assert isinstance(data["risk_flags"], list)
    assert data["corroboration"]["pay_stub_provided"] is False
    assert isinstance(data["summary"], str) and len(data["summary"]) > 0
    assert data["overall_risk_level"] in ("LOW", "MEDIUM", "HIGH")


def test_analyze_with_pay_stub_sets_provided_true():
    corr_with_stub = CorroborationResult(
        pay_stub_provided=True,
        corroboration_score=90,
        notes=[],
    )
    patches = _pipeline_patches(corr_override=corr_with_stub)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        resp = client.post(
            "/analyze",
            files={
                "statement": ("statement.pdf", _MINIMAL_PDF, "application/pdf"),
                "pay_stub": ("paystub.pdf", _MINIMAL_PDF, "application/pdf"),
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["corroboration"]["pay_stub_provided"] is True


# ---------------------------------------------------------------------------
# Temp file cleanup test
# ---------------------------------------------------------------------------

def test_temp_files_cleaned_up_after_request(tmp_path):
    """Verify that ingestor.cleanup is called for every saved temp file."""
    created: list[Path] = []

    def fake_save(file, temp_dir):
        dest = tmp_path / f"{uuid.uuid4()}.pdf"
        dest.write_bytes(b"fake")
        created.append(dest)
        return dest

    def real_cleanup(file_path):
        file_path.unlink(missing_ok=True)

    patches = [
        patch("financial_vetting_engine.services.ingestor.validate_and_save", side_effect=fake_save),
        patch("financial_vetting_engine.services.ingestor.cleanup", side_effect=real_cleanup),
        patch("financial_vetting_engine.services.extractor.extract", return_value=_SAMPLE_RAW),
        patch("financial_vetting_engine.services.normalizer.normalize", return_value=_SAMPLE_TRANSACTIONS),
        patch("financial_vetting_engine.services.analyzer.analyze", return_value=(_SAMPLE_METRICS, _SAMPLE_SCORES)),
        patch("financial_vetting_engine.services.flagger.detect_flags", return_value=[]),
        patch(
            "financial_vetting_engine.services.corroborator.corroborate",
            return_value=CorroborationResult(pay_stub_provided=False, corroboration_score=50),
        ),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        resp = client.post(
            "/analyze",
            files={"statement": ("statement.pdf", _MINIMAL_PDF, "application/pdf")},
        )

    assert resp.status_code == 200
    # All files created during the request should have been deleted
    for f in created:
        assert not f.exists(), f"Temp file was not cleaned up: {f}"
