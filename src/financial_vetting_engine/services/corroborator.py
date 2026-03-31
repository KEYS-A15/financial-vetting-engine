import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from financial_vetting_engine.schemas.corroboration import CorroborationResult, PayStubData
from financial_vetting_engine.schemas.extraction import RawExtractionResult
from financial_vetting_engine.schemas.flags import RiskFlag, RiskLevel
from financial_vetting_engine.schemas.transaction import Transaction, TransactionCategory, TransactionType
from financial_vetting_engine.utils.money_utils import parse_amount

_TWO = Decimal("0.01")
_AMOUNT_RE = re.compile(r"\$?([\d,]+\.\d{2})")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _get_full_text(raw: RawExtractionResult) -> str:
    return "\n".join(page.raw_text for page in raw.pages)


def _extract_amount(text: str, *label_patterns: str) -> Optional[Decimal]:
    """Search text for the first matching label and return the adjacent dollar amount."""
    lines = text.splitlines()
    for pattern in label_patterns:
        label_re = re.compile(pattern, re.IGNORECASE)
        for i, line in enumerate(lines):
            m = label_re.search(line)
            if m:
                rest = line[m.end():]
                am = _AMOUNT_RE.search(rest)
                if am:
                    return parse_amount(am.group(0))
                # Try next line
                if i + 1 < len(lines):
                    am = _AMOUNT_RE.search(lines[i + 1])
                    if am:
                        return parse_amount(am.group(0))
    return None


def _parse_date_str(s: str) -> Optional[date]:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _extract_pay_period(text: str) -> tuple[Optional[str], Optional[str]]:
    period_re = re.compile(
        r"(?:Pay\s+Period|Period\s+Begin|From)\s*[:\|]?\s*"
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})"
        r"(?:\s*[-\u2013to]+\s*|\s+(?:Period\s+End|To)\s*[:\|]?\s*)"
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        re.IGNORECASE,
    )
    m = period_re.search(text)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _detect_pay_frequency(text: str, start_str: Optional[str], end_str: Optional[str]) -> Optional[str]:
    freq_map = {
        "bi-weekly": "biweekly",
        "biweekly": "biweekly",
        "bi weekly": "biweekly",
        "semi-monthly": "semi-monthly",
        "semi monthly": "semi-monthly",
        "semimonthly": "semi-monthly",
        "monthly": "monthly",
        "weekly": "weekly",
    }
    freq_re = re.compile(
        r"\b(bi-weekly|biweekly|bi\s+weekly|semi-monthly|semi\s+monthly|semimonthly|monthly|weekly)\b",
        re.IGNORECASE,
    )
    m = freq_re.search(text)
    if m:
        raw = m.group(1).lower()
        return freq_map.get(raw, raw)

    if start_str and end_str:
        start_d = _parse_date_str(start_str)
        end_d = _parse_date_str(end_str)
        if start_d and end_d:
            delta = (end_d - start_d).days
            if delta <= 8:
                return "weekly"
            elif delta <= 14:
                return "biweekly"
            elif delta <= 17:
                return "semi-monthly"
            elif delta <= 31:
                return "monthly"
    return None


# ---------------------------------------------------------------------------
# Part A — Pay stub field extraction
# ---------------------------------------------------------------------------

def extract_pay_stub_data(raw: RawExtractionResult) -> PayStubData:
    text = _get_full_text(raw)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # employer_name: last non-empty line before "Pay Statement" / "Pay Stub" / "Earnings Statement"
    employer_name: Optional[str] = None
    stub_kw_re = re.compile(r"Pay\s+Statement|Pay\s+Stub|Earnings\s+Statement", re.IGNORECASE)
    kw_match = stub_kw_re.search(text)
    if kw_match:
        before_lines = [ln.strip() for ln in text[: kw_match.start()].splitlines() if ln.strip()]
        if before_lines:
            employer_name = before_lines[-1]
    if employer_name is None and lines:
        employer_name = lines[0]

    # employee_name
    employee_name: Optional[str] = None
    emp_re = re.compile(r"Employee(?:\s+Name)?\s*[:\|]\s*(.+?)(?:\n|$)", re.IGNORECASE)
    em = emp_re.search(text)
    if em:
        employee_name = em.group(1).strip()

    # pay_date
    pay_date_re = re.compile(
        r"(?:Pay\s+Date|Check\s+Date|Payment\s+Date)\s*[:\|]?\s*"
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        re.IGNORECASE,
    )
    pay_date: Optional[str] = None
    pdm = pay_date_re.search(text)
    if pdm:
        pay_date = pdm.group(1)

    # pay_period
    pay_period_start, pay_period_end = _extract_pay_period(text)

    # pay_frequency
    pay_frequency = _detect_pay_frequency(text, pay_period_start, pay_period_end)

    # amounts — more-specific patterns must come before general ones
    gross_pay = _extract_amount(text, r"Total\s+Gross", r"Gross\s+Earnings", r"Gross\s+Pay")
    net_pay = _extract_amount(text, r"Total\s+Net", r"Take\s+Home", r"Net\s+Earnings", r"Net\s+Pay")
    federal_tax = _extract_amount(
        text, r"Federal\s+Income\s+Tax", r"Federal\s+Tax", r"Fed\s+Tax", r"\bFIT\b"
    )
    state_tax = _extract_amount(text, r"State\s+Income\s+Tax", r"State\s+Tax", r"\bSIT\b")
    social_security = _extract_amount(text, r"Social\s+Security", r"\bOASDI\b", r"SS\s+Tax")
    medicare = _extract_amount(text, r"Med\s+Tax", r"Medicare")
    other_deductions = _extract_amount(text, r"Other\s+Deductions", r"Misc\s+Deductions")
    ytd_gross = _extract_amount(text, r"YTD\s+Gross", r"YTD\s+Earnings", r"Year\s+to\s+Date")

    return PayStubData(
        employer_name=employer_name,
        employee_name=employee_name,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        pay_date=pay_date,
        gross_pay=gross_pay,
        net_pay=net_pay,
        federal_tax=federal_tax,
        state_tax=state_tax,
        social_security=social_security,
        medicare=medicare,
        other_deductions=other_deductions,
        pay_frequency=pay_frequency,
        ytd_gross=ytd_gross,
    )


# ---------------------------------------------------------------------------
# Business day helpers
# ---------------------------------------------------------------------------

def _add_business_days(d: date, n: int) -> date:
    current = d
    added = 0
    while added < n:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _subtract_business_days(d: date, n: int) -> date:
    current = d
    subtracted = 0
    while subtracted < n:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            subtracted += 1
    return current


# ---------------------------------------------------------------------------
# Pay frequency inference
# ---------------------------------------------------------------------------

def _infer_frequency(salary_count: int, months_analyzed: int) -> Optional[str]:
    """Infer pay frequency from salary transaction count vs months.
    Requires at least 2 months of data to make a reliable inference.
    """
    if months_analyzed < 2 or salary_count == 0:
        return None
    ratio = salary_count / months_analyzed
    if ratio <= 1.3:
        return "monthly"
    elif ratio <= 3.0:
        return "biweekly"  # indistinguishable from semi-monthly by count
    else:
        return "weekly"


def _frequencies_match(inferred: Optional[str], declared: Optional[str]) -> bool:
    if not inferred or not declared:
        return True  # can't determine → don't penalise

    def _normalize(f: str) -> str:
        f = f.lower().replace("-", "").replace(" ", "")
        # biweekly and semi-monthly are both ~2×/month; treat as equivalent
        if f in ("semimonthly", "biweekly"):
            return "twice_monthly"
        return f

    return _normalize(inferred) == _normalize(declared)


# ---------------------------------------------------------------------------
# Part B — Cross-document corroboration
# ---------------------------------------------------------------------------

def corroborate(
    transactions: list[Transaction],
    pay_stub_raw: Optional[RawExtractionResult] = None,
) -> CorroborationResult:
    if not pay_stub_raw:
        return CorroborationResult(
            pay_stub_provided=False,
            corroboration_flags=[],
            corroboration_score=50,
            notes=["No pay stub provided — corroboration skipped"],
        )

    # Step 1: Extract pay stub fields
    pay_stub_data = extract_pay_stub_data(pay_stub_raw)

    # Step 2: Find matching deposit
    salary_txns = [
        t for t in transactions
        if t.transaction_type == TransactionType.CREDIT
        and t.category == TransactionCategory.SALARY
    ]

    observed_deposit: Optional[Decimal] = None
    deposit_date: Optional[date] = None
    pay_date_obj: Optional[date] = None

    if pay_stub_data.pay_date:
        pay_date_obj = _parse_date_str(pay_stub_data.pay_date)

    if pay_date_obj:
        lower_3 = _subtract_business_days(pay_date_obj, 3)
        upper_3 = _add_business_days(pay_date_obj, 3)

        nearby_salary = [t for t in salary_txns if lower_3 <= t.date <= upper_3]
        if nearby_salary:
            best = max(nearby_salary, key=lambda t: t.amount)
            observed_deposit = best.amount
            deposit_date = best.date
        else:
            # Fallback: any credit within ±3 business days
            nearby_credits = [
                t for t in transactions
                if t.transaction_type == TransactionType.CREDIT
                and lower_3 <= t.date <= upper_3
            ]
            if nearby_credits:
                best = max(nearby_credits, key=lambda t: t.amount)
                observed_deposit = best.amount
                deposit_date = best.date
            else:
                # Final fallback: largest credit overall
                all_credits = [t for t in transactions if t.transaction_type == TransactionType.CREDIT]
                if all_credits:
                    best = max(all_credits, key=lambda t: t.amount)
                    observed_deposit = best.amount
                    deposit_date = best.date
    else:
        # No pay_date: largest credit overall
        all_credits = [t for t in transactions if t.transaction_type == TransactionType.CREDIT]
        if all_credits:
            best = max(all_credits, key=lambda t: t.amount)
            observed_deposit = best.amount
            deposit_date = best.date

    # Step 3: Compare net pay vs observed deposit
    declared_net_pay = pay_stub_data.net_pay
    gap_amount: Optional[Decimal] = None
    gap_percent: Optional[Decimal] = None

    if declared_net_pay and observed_deposit and declared_net_pay > 0:
        gap_amount = abs(declared_net_pay - observed_deposit)
        gap_percent = (gap_amount / declared_net_pay * 100).quantize(_TWO, rounding=ROUND_HALF_UP)

    # Step 4: Employer name match — search SALARY transaction descriptions only
    employer_name_match: Optional[bool] = None
    if pay_stub_data.employer_name:
        employer_words = [w.lower() for w in pay_stub_data.employer_name.split() if len(w) >= 3]
        if employer_words:
            salary_narrations = " ".join(t.description.lower() for t in salary_txns)
            employer_name_match = any(w in salary_narrations for w in employer_words)

    # Step 5: Pay frequency match
    pay_frequency_match: Optional[bool] = None
    months_set = {t.date.strftime("%Y-%m") for t in transactions}
    months_analyzed = len(months_set)
    salary_count = len(salary_txns)
    inferred_freq = _infer_frequency(salary_count, months_analyzed)
    if pay_stub_data.pay_frequency and inferred_freq:
        pay_frequency_match = _frequencies_match(inferred_freq, pay_stub_data.pay_frequency)

    # Step 6: Generate corroboration flags
    corroboration_flags: list[RiskFlag] = []

    # SALARY_NOT_FOUND
    salary_not_found = False
    if pay_date_obj:
        lower_5 = _subtract_business_days(pay_date_obj, 5)
        upper_5 = _add_business_days(pay_date_obj, 5)
        nearby_salary_5 = [t for t in salary_txns if lower_5 <= t.date <= upper_5]
        if not nearby_salary_5:
            salary_not_found = True
            corroboration_flags.append(RiskFlag(
                code="SALARY_NOT_FOUND",
                level=RiskLevel.HIGH,
                description="No salary deposit found in statement near the declared pay date.",
                evidence=[
                    f"Pay date: {pay_stub_data.pay_date}",
                    f"Searched {lower_5} to {upper_5} (±5 business days)",
                    f"SALARY category transactions in statement: {len(salary_txns)}",
                ],
                triggered_by=[f"No SALARY tx within 5 business days of {pay_stub_data.pay_date}"],
                recommendation="Salary deposit not located — verify account or pay date",
            ))

    # SALARY_DEPOSIT_GAP
    if gap_percent is not None and gap_percent > Decimal("5.0"):
        level = RiskLevel.HIGH if gap_percent > Decimal("15.0") else RiskLevel.MEDIUM
        corroboration_flags.append(RiskFlag(
            code="SALARY_DEPOSIT_GAP",
            level=level,
            description=f"Declared net pay differs from observed deposit by {gap_percent:.2f}%.",
            evidence=[
                f"Declared net pay: ${declared_net_pay:,.2f}",
                f"Observed deposit: ${observed_deposit:,.2f}",
                f"Gap: ${gap_amount:,.2f} ({gap_percent:.2f}%)",
            ],
            triggered_by=[f"Gap: ${gap_amount:,.2f} ({gap_percent:.2f}%)"],
            recommendation="Verify deductions or confirm correct pay period",
        ))

    # EMPLOYER_NAME_MISMATCH
    if employer_name_match is False and pay_stub_data.employer_name:
        corroboration_flags.append(RiskFlag(
            code="EMPLOYER_NAME_MISMATCH",
            level=RiskLevel.MEDIUM,
            description=f"Employer '{pay_stub_data.employer_name}' not found in salary transaction narrations.",
            evidence=[
                f"Employer on stub: {pay_stub_data.employer_name}",
                f"Searched SALARY transaction descriptions for: {pay_stub_data.employer_name}",
            ],
            triggered_by=[f"Employer '{pay_stub_data.employer_name}' not found in narrations"],
            recommendation="Confirm employer name on bank statement narrations",
        ))

    # PAY_FREQUENCY_MISMATCH
    if pay_frequency_match is False:
        corroboration_flags.append(RiskFlag(
            code="PAY_FREQUENCY_MISMATCH",
            level=RiskLevel.LOW,
            description="Inferred pay frequency from statement doesn't match declared pay frequency.",
            evidence=[
                f"Inferred from statement: {inferred_freq}",
                f"Declared on stub: {pay_stub_data.pay_frequency}",
                f"Salary transactions: {salary_count} over {months_analyzed} months",
            ],
            triggered_by=[f"Inferred: {inferred_freq}, Declared: {pay_stub_data.pay_frequency}"],
            recommendation="Verify pay schedule matches statement activity",
        ))

    # Step 7: Compute corroboration score
    score = 100
    if salary_not_found:
        score -= 50
    if gap_percent is not None:
        if gap_percent > Decimal("15.0"):
            score -= 40
        elif gap_percent > Decimal("5.0"):
            score -= 20
    if employer_name_match is False:
        score -= 20
    if pay_frequency_match is False:
        score -= 10
    score = max(0, min(100, score))

    # Step 8: Notes
    notes: list[str] = []
    if declared_net_pay:
        notes.append(f"Net pay of ${declared_net_pay:,.2f} declared on stub")
    if observed_deposit and deposit_date:
        notes.append(f"Deposit of ${observed_deposit:,.2f} found on {deposit_date}")
    if pay_stub_data.employer_name:
        if employer_name_match:
            notes.append(
                f"Employer '{pay_stub_data.employer_name}' detected in statement narrations"
            )
        else:
            notes.append(
                f"Employer '{pay_stub_data.employer_name}' not detected in statement narrations"
            )
    if inferred_freq:
        notes.append(f"Pay frequency inferred as {inferred_freq} from statement activity")

    return CorroborationResult(
        pay_stub_provided=True,
        pay_stub_data=pay_stub_data,
        declared_net_pay=declared_net_pay,
        observed_deposit=observed_deposit,
        gap_amount=gap_amount,
        gap_percent=gap_percent,
        employer_name_match=employer_name_match,
        pay_frequency_match=pay_frequency_match,
        corroboration_flags=corroboration_flags,
        corroboration_score=score,
        notes=notes,
    )
