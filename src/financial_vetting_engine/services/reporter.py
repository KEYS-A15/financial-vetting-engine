import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..schemas.corroboration import CorroborationResult
from ..schemas.flags import RiskFlag, RiskLevel
from ..schemas.metrics import FinancialMetrics
from ..schemas.result import AnalysisResult
from ..schemas.scores import BehavioralScores
from ..schemas.transaction import StatementMetadata, Transaction


def assemble(
    file_path: Path,
    transactions: list[Transaction],
    metrics: FinancialMetrics,
    scores: BehavioralScores,
    flags: list[RiskFlag],
    corroboration: CorroborationResult,
    processing_start: float,
    statement_metadata: StatementMetadata,
) -> AnalysisResult:
    # Step 1: Overall risk level
    levels = {f.level for f in flags}
    if RiskLevel.HIGH in levels:
        overall_risk_level = "HIGH"
    elif RiskLevel.MEDIUM in levels:
        overall_risk_level = "MEDIUM"
    else:
        overall_risk_level = "LOW"

    # Step 2: Recommendation
    high_flags = [f for f in flags if f.level == RiskLevel.HIGH]
    medium_flags = [f for f in flags if f.level == RiskLevel.MEDIUM]

    ratio = metrics.expense_to_income_ratio
    avg_income = metrics.avg_monthly_income

    if high_flags:
        top_descs = "; ".join(f.description for f in high_flags[:3])
        recommendation = (
            f"High risk profile detected. {len(high_flags)} high-severity flag(s) require "
            f"manual review before proceeding. Key concerns: {top_descs}"
        )
    elif medium_flags:
        top_concern = medium_flags[0].description
        recommendation = (
            f"Moderate risk profile. {len(flags)} flag(s) identified for review. "
            f"Income-to-expense ratio is {ratio:.2f}. "
            f"Recommend verification of {top_concern}."
        )
    elif flags:
        recommendation = (
            f"Low risk profile. Financials appear stable with consistent "
            f"income of ${avg_income:.2f}/month and expense ratio of "
            f"{ratio:.2f}. {len(flags)} minor flag(s) noted."
        )
    else:
        recommendation = (
            f"Clean financial profile. No risk flags detected. "
            f"Average monthly income ${avg_income:.2f}, "
            f"expense ratio {ratio:.2f}, "
            f"behavioral score {scores.overall}/100."
        )

    # Step 3: Summary
    start_date = statement_metadata.statement_period_start
    end_date = statement_metadata.statement_period_end
    months = metrics.months_analyzed
    total_income = metrics.total_income
    total_expenses = metrics.total_expenses
    net = metrics.net_cashflow

    if not flags:
        flag_summary = "No risk flags detected."
    else:
        codes = ", ".join(f.code for f in flags)
        flag_summary = f"{len(flags)} risk flag(s) detected: {codes}"

    summary = (
        f"Statement covers {months} month(s) from {start_date} to {end_date}. "
        f"Total income: ${total_income:.2f}, total expenses: ${total_expenses:.2f}, "
        f"net cashflow: ${net:.2f}. "
        f"Behavioral score: {scores.overall}/100. {flag_summary}"
    )

    # Step 4: Processing time
    processing_time_seconds = round(time.time() - processing_start, 3)

    # Step 5: Return AnalysisResult
    return AnalysisResult(
        analysis_id=str(uuid.uuid4()),
        processed_at=datetime.now(timezone.utc),
        processing_time_seconds=processing_time_seconds,
        statement_metadata=statement_metadata,
        transactions=transactions,
        metrics=metrics,
        behavioral_scores=scores,
        risk_flags=flags,
        corroboration=corroboration,
        summary=summary,
        overall_risk_level=overall_risk_level,
        recommendation=recommendation,
    )
