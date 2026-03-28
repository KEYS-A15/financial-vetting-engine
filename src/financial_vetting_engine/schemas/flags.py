from pydantic import BaseModel
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskFlag(BaseModel):
    code: str
    level: RiskLevel
    description: str
    evidence: list[str]
