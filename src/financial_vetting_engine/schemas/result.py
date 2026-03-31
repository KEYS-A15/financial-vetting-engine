from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from .transaction import Transaction, StatementMetadata
from .metrics import FinancialMetrics
from .scores import BehavioralScores
from .flags import RiskFlag
from .corroboration import CorroborationResult


class AnalysisResult(BaseModel):
    analysis_id: str
    processed_at: datetime
    processing_time_seconds: float

    statement_metadata: StatementMetadata
    transactions: list[Transaction]

    metrics: FinancialMetrics
    behavioral_scores: BehavioralScores
    risk_flags: list[RiskFlag]
    corroboration: CorroborationResult

    summary: str
    overall_risk_level: str      # LOW / MEDIUM / HIGH
    recommendation: str          # one-line underwriting recommendation


class AnalysisError(BaseModel):
    error: str
    detail: str
    file_name: Optional[str]
