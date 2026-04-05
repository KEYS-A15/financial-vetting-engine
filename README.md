# Financial Vetting Engine

### *A replica of client project in FinTech domain*  

An open-source, locally-runnable financial document analysis engine for the US market. Upload bank statements and pay stubs, get back a structured underwriting-grade analysis such as **income verification**, **risk flags**, **behavioral scoring**, and **cross-document corroboration**. No cloud account required. No data leaves your machine.

## The problem this solves

Manual bank statement review is one of the last truly manual steps in US lending, mortgage underwriting, and tenant screening. Analysts spend hours extracting the same metrics from PDF statements that any structured system could compute in seconds.

Commercial solutions (Ocrolus, Inscribe, Flagright) exist but are closed, expensive, and require sending sensitive financial documents to third-party APIs. There is no well-engineered open-source alternative built for US banking formats.

**This is that alternative.**

# What it does

Submit a bank statement PDF (and optionally a pay stub) and receive:

### Transaction analysis
- Full transaction extraction across Chase, Bank of America, Wells Fargo, Citi, and other major US bank statement layouts
- Automatic categorization: salary, rent, utilities, loan payments, transfers, ATM, dining, groceries, and more
- Counterparty classification: employer, lender, utility provider, peer transfer

### Financial metrics
- Total income and expenses with monthly breakdown
- Net cashflow trend (improving / stable / declining)
- Expense-to-income ratio
- Savings rate over statement period
- Largest single expense and top spending categories
- Average daily balance and liquidity stress events

### Behavioral scoring
Five deterministic, explainable scores (0–100):

| Score | What it measures |
|---|---|
| Income stability | Variance in credit amounts month-over-month |
| Expense volatility | How erratic spending patterns are |
| Savings trajectory | Whether the savings rate is improving or declining |
| Liquidity health | Frequency of near-zero or negative balance events |
| Payment regularity | Consistency of recurring obligations (rent, loan EMIs) |

### Risk flags (cited, not asserted)
Every flag includes the exact transactions, dates, and amounts that triggered it — no black box assertions:

| Flag | Description |
|---|---|
| `HIGH_EXPENSE_RATIO` | Expenses consistently exceed 90% of income |
| `INCOME_INSTABILITY` | Monthly income variance exceeds 40% |
| `NSF_EVENTS` | Non-sufficient funds or overdraft transactions detected |
| `LARGE_CASH_WITHDRAWALS` | ATM withdrawals above threshold, clustered |
| `ROUND_NUMBER_CLUSTERING` | Unusual concentration of round-number transactions |
| `BALANCE_DISCONTINUITY` | Closing balance of one month doesn't match opening of next |
| `UNDECLARED_RECURRING_DEBT` | Regular fixed outflows not matching known categories |
| `INCOME_SOURCE_UNVERIFIED` | Bank credits don't match employer named on pay stub |
| `SALARY_DEPOSIT_GAP` | Net pay on stub vs actual bank deposit diverges > 5% |

### Cross-document corroboration (with pay stub)
When a pay stub is provided alongside the bank statement:
- Declared gross income vs actual net deposits
- Employer name on stub vs credit narration in statement  
- Pay frequency verification (biweekly / semi-monthly / monthly)
- Flags any gap between stated and observed income

### Statement authenticity signals
Deterministic fraud indicators, no ML required:
- Balance continuity across months
- Transaction timing distribution (too-regular patterns are a signal)
- Round-number concentration
- Weekend transaction presence
- Narration entropy (copy-pasted transactions flag themselves)

---

## API
```
POST   /analyze                    Upload PDF(s), returns AnalysisResult
GET    /health                     Service health check  
GET    /schema/result              AnalysisResult JSON schema
GET    /schema/transaction         Transaction schema
```

**Example request:**
```bash
curl -X POST http://localhost:8000/analyze \
  -F "statement=@chase_statement.pdf" \
  -F "pay_stub=@paystub_march.pdf"
```

**Example response shape:**
```json
{
    "analysis_id": "uuid",
    "processed_at": "2025-03-27T...",
    "statement_metadata": { ... },
    "transactions": [ ... ],
    "metrics": {
        "total_income": "8450.00",
        "total_expenses": "7230.00",
        "net_cashflow": "1220.00",
        "expense_to_income_ratio": "0.856",
        "monthly_breakdown": [ ... ]
    },
    "behavioral_scores": {
        "income_stability": 82,
        "expense_volatility": 61,
        "savings_trajectory": 74,
        "liquidity_health": 55,
        "payment_regularity": 90
    },
    "risk_flags": [
        {
            "code": "HIGH_EXPENSE_RATIO",
            "level": "medium",
            "description": "Expenses exceeded 85% of income in 3 of 3 months",
            "evidence": [
                "January: $2,890 expenses / $3,200 income = 90.3%",
                "February: $2,650 expenses / $2,950 income = 89.8%",
                "March: $1,690 expenses / $2,300 income = 73.5%"
            ]
        }
    ],
    "corroboration": {
        "pay_stub_match": true,
        "declared_net_pay": "2850.00",
        "observed_deposit": "2847.50",
        "gap_percent": "0.09",
        "flags": []
    },
    "summary": "..."
}
```

---

## Architecture

Five service layers. Each layer communicates only through Pydantic v2 schemas.
No raw dicts passed between layers.
```
PDF / Pay Stub
      │
      ▼
 Ingestor ──────── validates file type, size, extracts bytes
      │
      ▼
 Extractor ─────── layout-agnostic table detection via pdfplumber geometry
      │             table-first → text-line fallback per page
      │  RawExtractionResult
      ▼
 Normalizer ─────── cleans rows, parses dates/amounts, categorizes transactions
      │  List[Transaction]
      ▼
 Analyzer ──────── computes metrics, behavioral scores, risk flags
      │             corroborates against pay stub if provided
      │  FinancialMetrics + BehavioralScores + List[RiskFlag]
      ▼
 Reporter ──────── assembles AnalysisResult, generates summary
      │
      ▼
 FastAPI ────────── thin shell, multipart upload, JSON response
```

### Document type extensibility

The extractor follows an abstract base class pattern, making new document types 
straightforward to add:
```python
class DocumentExtractor(ABC):
    @abstractmethod
    def extract(self, file_path: Path) -> RawExtractionResult:
        pass

# Implemented:
class BankStatementExtractor(DocumentExtractor): ...
class PayStubExtractor(DocumentExtractor): ...

# Planned V2:
class Form1099Extractor(DocumentExtractor): ...
class W2Extractor(DocumentExtractor): ...
```

---

## Design decisions

**Why deterministic analysis, not LLM-based?**

LLM-based financial analysis produces outputs that cannot be cited in a lending 
decision, audited by a regulator, or explained to a borrower. Every flag in 
this system cites the exact transactions that triggered it. That's a 
requirement in regulated financial contexts, not a nice-to-have.

**Why local-first?**

Bank statements contain some of the most sensitive personal data that exists. 
Sending them to a third-party API — even a well-intentioned one — is a 
compliance and privacy risk. This system processes everything locally with zero 
network calls in V1.

**Why pdfplumber over Textract/OCR?**

The vast majority of US bank statements downloaded from online banking portals 
are text-based PDFs, not scanned images. pdfplumber extracts from these with 
perfect fidelity and no API cost. OCR (V2) is reserved for physically scanned 
documents.

---

## Tech stack

| Component | Choice | Rationale |
|---|---|---|
| PDF extraction | pdfplumber | Local, zero config, handles text-based PDFs |
| Data validation | Pydantic v2 | Fast, strict, self-documenting schemas |
| API | FastAPI + uvicorn | Industry standard, automatic OpenAPI docs |
| Config | pydantic-settings | .env → typed config, no magic |
| Dependency mgmt | uv | Fast resolver, lockfile, modern tooling |
| Testing | pytest | Standard, composable |

---

## V1 vs V2 roadmap

**V1 — this repo:**
- Bank statements + pay stubs
- Text-based PDFs only (no OCR)
- Deterministic analysis
- Stateless (no database)
- Single-file and paired-file processing

**V2 — planned:**
- OCR support via AWS Textract (scanned documents)
- W-2 and 1099 parsing
- Claude API for narrative summary generation
- PostgreSQL persistence + job history
- Async processing via task queue
- Batch processing (multiple months, multiple accounts)

---

## Getting started

**Requirements:** Python 3.11+, uv
```bash
git clone https://github.com/YOUR_USERNAME/financial-vetting-engine
cd financial-vetting-engine

uv sync
cp .env.example .env

uv run uvicorn financial_vetting_engine.main:app --reload
# → http://localhost:8000/docs
```

**Run tests:**
```bash
uv run pytest                                                        # all tests
uv run pytest tests/test_analyzer.py -v                             # specific module
uv run pytest --cov=financial_vetting_engine --cov-report=term-missing  # with coverage
```

**Generate synthetic test PDFs** (required once before running integration tests):
```bash
uv run python tests/generate_samples.py
```

---

## Project structure
```
financial-vetting-engine/
├── src/financial_vetting_engine/
│   ├── main.py
│   ├── api/
│   │   └── routes.py
│   ├── core/
│   │   └── config.py
│   ├── schemas/
│   │   ├── transaction.py       # Transaction, StatementMetadata
│   │   ├── metrics.py           # FinancialMetrics, MonthlyBreakdown
│   │   ├── scores.py            # BehavioralScores
│   │   ├── flags.py             # RiskFlag, RiskLevel
│   │   ├── corroboration.py     # CorroborationResult
│   │   └── result.py            # AnalysisResult
│   ├── services/
│   │   ├── ingestor.py
│   │   ├── extractor.py         # Abstract base + implementations
│   │   ├── normalizer.py
│   │   ├── analyzer.py          # Metrics, scores, flags
│   │   ├── corroborator.py      # Cross-document comparison
│   │   └── reporter.py
│   └── utils/
│       ├── date_utils.py
│       ├── money_utils.py
│       └── text_utils.py        # Narration cleaning, fuzzy match
├── tests/
│   ├── sample_statements/       # Synthetic test PDFs (generated by generate_samples.py)
│   ├── conftest.py              # Shared fixtures
│   ├── generate_samples.py      # Builds synthetic PDFs via reportlab
│   ├── test_extractor.py
│   ├── test_normalizer.py
│   ├── test_analyzer.py
│   ├── test_flagger.py
│   ├── test_corroborator.py
│   └── test_api.py
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Background

This is a clean-room reimplementation of a production financial vetting system,
rebuilt for the US market with a cleaner architecture. The original was 
AWS-native (Textract, Bedrock, SQS, pgvector) and India-focused. This version 
strips back to the deterministic core, runs entirely locally, and is designed 
to be understandable, auditable, and extensible.

---

## Build status

| Phase | Description | Status |
|---|---|---|
| 0 | Schemas | ✅ |
| 1 | PDF extractor (layout-agnostic) | ✅ |
| 2 | Normalizer + US categorization | ✅ |
| 3 | Analyzer: metrics + behavioral scores | ✅ |
| 4 | Risk flags + authenticity signals | ✅ |
| 5 | Pay stub extractor + corroborator | ✅ |
| 6 | FastAPI shell + OpenAPI docs | ✅ |
| 7 | Tests + sample statements | ✅ |