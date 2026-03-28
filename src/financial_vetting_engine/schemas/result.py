from pydantic import BaseModel
from datetime import datetime
from .transaction import Transaction, StatementMetadata
from .metrics import FinancialMetrics
from .flags import RiskFlag


class AnalysisResult(BaseModel):
    analysis_id: str
    processed_at: datetime
    statement_metadata: StatementMetadata
    transactions: list[Transaction]
    metrics: FinancialMetrics
    risk_flags: list[RiskFlag]
    summary: str
