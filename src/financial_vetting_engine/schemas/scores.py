from pydantic import BaseModel


class BehavioralScores(BaseModel):
    income_stability: int       # 0-100
    expense_volatility: int     # 0-100
    savings_trajectory: int     # 0-100
    liquidity_health: int       # 0-100
    payment_regularity: int     # 0-100
    overall: int                # weighted average
