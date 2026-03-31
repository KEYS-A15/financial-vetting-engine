import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..core.config import settings
from ..schemas.extraction import RawExtractionResult
from ..schemas.result import AnalysisResult
from ..schemas.transaction import StatementMetadata, Transaction
from ..services import (
    analyzer,
    corroborator,
    extractor,
    flagger,
    ingestor,
    normalizer,
    reporter,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_KNOWN_BANKS = [
    "Chase",
    "Bank of America",
    "Wells Fargo",
    "Citibank",
    "US Bank",
]


def _extract_metadata(
    raw: RawExtractionResult, transactions: list[Transaction]
) -> StatementMetadata:
    bank_name = None
    account_number_last4 = None

    first_page_text = raw.pages[0].raw_text if raw.pages else ""

    for bank in _KNOWN_BANKS:
        if bank.lower() in first_page_text.lower():
            bank_name = bank
            break

    acct_match = re.search(r"[x*]{0,4}(\d{4})\b", first_page_text)
    if acct_match:
        account_number_last4 = acct_match.group(1)

    dates = [t.date for t in transactions]
    period_start = min(dates)
    period_end = max(dates)

    opening_balance = (
        transactions[0].balance_after
        if transactions[0].balance_after is not None
        else None
    )
    closing_balance = (
        transactions[-1].balance_after
        if transactions[-1].balance_after is not None
        else None
    )

    return StatementMetadata(
        bank_name=bank_name,
        account_number_last4=account_number_last4,
        statement_period_start=period_start,
        statement_period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        currency="USD",
    )


@router.post("/analyze", response_model=AnalysisResult)
async def analyze(
    statement: UploadFile = File(...),
    pay_stub: UploadFile = File(None),
):
    start = time.time()
    statement_path: Path | None = None
    pay_stub_path: Path | None = None

    try:
        # 1. Ingest
        statement_path = ingestor.validate_and_save(statement, settings.temp_dir)
        if pay_stub and pay_stub.filename:
            pay_stub_path = ingestor.validate_and_save(pay_stub, settings.temp_dir)

        # 2. Extract
        raw = extractor.extract(statement_path)
        pay_stub_raw = extractor.extract(pay_stub_path) if pay_stub_path else None

        # 3. Normalize
        transactions = normalizer.normalize(raw)
        if not transactions:
            raise HTTPException(
                status_code=422,
                detail="No transactions could be extracted from this PDF",
            )

        # 4. Analyze
        metrics, scores = analyzer.analyze(transactions)

        # 5. Flag
        flags = flagger.detect_flags(transactions, metrics, scores)

        # 6. Corroborate
        corroboration = corroborator.corroborate(transactions, pay_stub_raw)

        # 7. Extract metadata
        metadata = _extract_metadata(raw, transactions)

        # 8. Assemble
        return reporter.assemble(
            statement_path, transactions, metrics,
            scores, flags, corroboration, start, metadata,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Analysis failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if statement_path:
            ingestor.cleanup(statement_path)
        if pay_stub_path:
            ingestor.cleanup(pay_stub_path)


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "app": settings.app_name,
    }


@router.get("/schema/result")
async def schema_result():
    return AnalysisResult.model_json_schema()


@router.get("/schema/transaction")
async def schema_transaction():
    return Transaction.model_json_schema()
