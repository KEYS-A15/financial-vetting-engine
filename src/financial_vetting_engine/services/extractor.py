import re
from abc import ABC, abstractmethod
from pathlib import Path

from financial_vetting_engine.schemas.extraction import PageExtraction, RawExtractionResult

# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

_HEADER_KEYWORDS = {
    "date", "amount", "description", "balance", "debit", "credit",
    "narration", "particulars", "withdrawal", "deposit", "reference",
    "transaction", "detail", "value",
}


def _looks_like_headers(row: list) -> bool:
    if not row:
        return False
    non_null = [str(c).strip().lower() for c in row if c is not None]
    if not non_null:
        return False
    matches = sum(1 for cell in non_null if any(kw in cell for kw in _HEADER_KEYWORDS))
    return matches >= 1


def _table_to_dicts(table: list[list]) -> list[dict]:
    if not table:
        return []

    if _looks_like_headers(table[0]):
        raw_headers = table[0]
        headers = []
        seen: dict[str, int] = {}
        for h in raw_headers:
            key = str(h).strip() if h is not None else ""
            if not key:
                key = f"col_{len(headers)}"
            if key in seen:
                seen[key] += 1
                key = f"{key}_{seen[key]}"
            else:
                seen[key] = 0
            headers.append(key)
        data_rows = table[1:]
    else:
        headers = [f"col_{i}" for i in range(len(table[0]))]
        data_rows = table

    result = []
    for row in data_rows:
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        result.append({
            headers[i]: (str(row[i]).strip() if row[i] is not None else "")
            for i in range(min(len(headers), len(row)))
        })
    return result


# ---------------------------------------------------------------------------
# Structured text parser (handles Chase-style and similar text-based PDFs)
# ---------------------------------------------------------------------------

# Lines starting with MM/DD or MM/DD/YYYY
_DATE_PREFIX    = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?\s")
# Last two decimal numbers on a line → amount + balance
_AMT_BAL_SUFFIX = re.compile(r"([-+]?[\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$")
# Section delimiters used by Chase (and some other banks)
_SECTION_MARKER = re.compile(
    r"\*start\*transactiondetail(.*?)\*end\*transactiondetail", re.DOTALL | re.IGNORECASE
)

_SKIP_PREFIXES = (
    "DATE ", "TRANSACTION DETAIL", "*start*", "*end*",
    "Page", "Beginning Balance", "Ending Balance",
)


def _try_parse_as_structured_text(text: str) -> list[dict] | None:
    """
    Parse bank statement text into structured {Date, Description, Amount, Balance} rows.

    Strategy:
      1. If section markers exist, extract only those blocks.
      2. Group lines: a new transaction starts whenever a line begins with MM/DD.
      3. Try to extract amount + balance from the end of each transaction's first line.
      4. Continuation lines (card numbers, wire details) are appended to description.

    Returns None if the text doesn't look like structured transaction data.
    """
    if not text:
        return None

    sections = _SECTION_MARKER.findall(text)
    working = "\n".join(sections) if sections else text

    lines = [
        ln.strip() for ln in working.splitlines()
        if ln.strip() and not any(ln.strip().startswith(p) for p in _SKIP_PREFIXES)
    ]

    # Group into transactions: new group starts on a date-prefixed line
    groups: list[list[str]] = []
    for line in lines:
        if _DATE_PREFIX.match(line):
            groups.append([line])
        elif groups:
            groups[-1].append(line)

    if not groups:
        return None

    rows = []
    for group in groups:
        first = group[0]
        date_end = _DATE_PREFIX.match(first).end()
        date_str  = first[:date_end].strip()
        first_rest = first[date_end:].strip()

        # Try amount/balance on the first line
        ab = _AMT_BAL_SUFFIX.search(first_rest)
        if ab:
            desc_base    = first_rest[:ab.start()].strip()
            # Continuation lines become extra description context
            extra = " ".join(ln.strip() for ln in group[1:])
            description  = (desc_base + " " + extra).strip() if extra else desc_base
            amount_str   = ab.group(1)
            balance_str  = ab.group(2)
        else:
            # Fallback: join all lines and search again (e.g. wrapped amount)
            joined = " ".join(group)
            ab = _AMT_BAL_SUFFIX.search(joined)
            if not ab:
                continue
            description = joined[date_end:ab.start()].strip()
            amount_str  = ab.group(1)
            balance_str = ab.group(2)

        rows.append({
            "Date":        date_str,
            "Description": description,
            "Amount":      amount_str,
            "Balance":     balance_str,
        })

    # Require at least 30% hit-rate to trust the result
    if len(rows) < max(1, len(groups) * 0.3):
        return None

    return rows


# ---------------------------------------------------------------------------
# Extractor classes
# ---------------------------------------------------------------------------

class DocumentExtractor(ABC):
    @abstractmethod
    def extract(self, file_path: Path) -> RawExtractionResult:
        ...


class BankStatementExtractor(DocumentExtractor):
    def extract(self, file_path: Path) -> RawExtractionResult:
        import pdfplumber  # lazy import so tests can mock before the DLL loads

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as exc:
            if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                raise PermissionError(
                    f"PDF is password-protected and cannot be read: {file_path.name}"
                ) from exc
            raise

        pages: list[PageExtraction] = []

        with pdf:
            for page in pdf.pages:
                raw_text: str = page.extract_text() or ""
                table = page.extract_table()

                if table:
                    rows   = _table_to_dicts(table)
                    method = "table"
                else:
                    # Try to extract structure from text before falling back to lines
                    structured = _try_parse_as_structured_text(raw_text)
                    if structured:
                        rows   = structured
                        method = "table"   # structured rows → normalizer treats as table
                    else:
                        lines  = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                        rows   = [{"line": ln} for ln in lines]
                        method = "text"

                if not rows and not raw_text.strip():
                    continue

                pages.append(PageExtraction(
                    page_number=page.page_number,
                    method=method,
                    rows=rows,
                    raw_text=raw_text,
                ))

        return RawExtractionResult(
            pages=pages,
            page_count=len(pdf.pages),
            file_name=file_path.name,
            file_size_bytes=file_path.stat().st_size,
        )


class PayStubExtractor(DocumentExtractor):
    def extract(self, file_path: Path) -> RawExtractionResult:
        import pdfplumber  # lazy import so tests can mock before the DLL loads

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as exc:
            if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                raise PermissionError(
                    f"PDF is password-protected and cannot be read: {file_path.name}"
                ) from exc
            raise

        pages: list[PageExtraction] = []

        with pdf:
            for page in pdf.pages:
                raw_text: str = page.extract_text() or ""
                lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                rows = [{"line": ln} for ln in lines]

                if not rows and not raw_text.strip():
                    continue

                pages.append(PageExtraction(
                    page_number=page.page_number,
                    method="text",
                    rows=rows,
                    raw_text=raw_text,
                ))

        return RawExtractionResult(
            pages=pages,
            page_count=len(pdf.pages),
            file_name=file_path.name,
            file_size_bytes=file_path.stat().st_size,
        )


class ExtractorFactory:
    @staticmethod
    def get_extractor(file_path: Path, document_type: str = "bank_statement") -> DocumentExtractor:
        if document_type == "pay_stub":
            return PayStubExtractor()
        return BankStatementExtractor()


def extract(file_path: Path) -> RawExtractionResult:
    extractor = ExtractorFactory.get_extractor(file_path)
    return extractor.extract(file_path)
