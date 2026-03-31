from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from financial_vetting_engine.schemas.extraction import PageExtraction, RawExtractionResult
from financial_vetting_engine.services.extractor import (
    BankStatementExtractor,
    ExtractorFactory,
    _looks_like_headers,
    _table_to_dicts,
    extract,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestLooksLikeHeaders:
    def test_recognises_date_column(self):
        assert _looks_like_headers(["Date", "Description", "Amount"]) is True

    def test_recognises_debit_credit(self):
        assert _looks_like_headers(["Debit", "Credit", "Balance"]) is True

    def test_rejects_plain_data_row(self):
        assert _looks_like_headers(["01/01/2024", "Tesco", "12.50"]) is False

    def test_handles_none_cells(self):
        assert _looks_like_headers([None, "Amount", None]) is True

    def test_empty_row_returns_false(self):
        assert _looks_like_headers([]) is False


class TestTableToDicts:
    def test_header_row_used_as_keys(self):
        table = [
            ["Date", "Description", "Amount"],
            ["2024-01-01", "Salary", "5000"],
        ]
        result = _table_to_dicts(table)
        assert result == [{"Date": "2024-01-01", "Description": "Salary", "Amount": "5000"}]

    def test_positional_keys_when_no_headers(self):
        table = [
            ["2024-01-01", "Tesco", "12.50"],
            ["2024-01-02", "Shell", "45.00"],
        ]
        result = _table_to_dicts(table)
        assert result[0] == {"col_0": "2024-01-01", "col_1": "Tesco", "col_2": "12.50"}

    def test_empty_rows_skipped(self):
        table = [
            ["Date", "Amount"],
            [None, None],
            ["2024-01-01", "100"],
        ]
        result = _table_to_dicts(table)
        assert len(result) == 1

    def test_duplicate_headers_deduplicated(self):
        table = [
            ["Amount", "Amount"],
            ["100", "200"],
        ]
        result = _table_to_dicts(table)
        keys = list(result[0].keys())
        assert len(set(keys)) == 2  # no duplicate keys

    def test_empty_table_returns_empty(self):
        assert _table_to_dicts([]) == []


# ---------------------------------------------------------------------------
# BankStatementExtractor — mocked pdfplumber
# ---------------------------------------------------------------------------

def _make_page(page_number, table=None, text=""):
    page = MagicMock()
    page.page_number = page_number
    page.extract_table.return_value = table
    page.extract_text.return_value = text
    return page


def _mock_pdf(pages, path="statement.pdf", size=1024):
    pdf = MagicMock()
    pdf.pages = pages
    pdf.__enter__ = lambda s: s
    pdf.__exit__ = MagicMock(return_value=False)
    return pdf


class TestBankStatementExtractor:
    def _run(self, pages, file_name="statement.pdf", file_size=1024):
        pdf_mock = _mock_pdf(pages)
        fake_path = MagicMock(spec=Path)
        fake_path.name = file_name
        fake_path.stat.return_value.st_size = file_size

        with patch("pdfplumber.open", return_value=pdf_mock):
            extractor = BankStatementExtractor()
            return extractor.extract(fake_path)

    def test_returns_raw_extraction_result_shape(self):
        pages = [
            _make_page(1, table=[["Date", "Amount"], ["2024-01-01", "100"]], text="Date Amount"),
        ]
        result = self._run(pages)
        assert isinstance(result, RawExtractionResult)
        assert result.file_name == "statement.pdf"
        assert result.file_size_bytes == 1024
        assert result.page_count == 1

    def test_table_path_sets_method_to_table(self):
        pages = [
            _make_page(1, table=[["Date", "Amount"], ["2024-01-01", "100"]], text="some text"),
        ]
        result = self._run(pages)
        assert result.pages[0].method == "table"
        assert result.pages[0].rows == [{"Date": "2024-01-01", "Amount": "100"}]

    def test_fallback_to_text_when_table_is_none(self):
        pages = [
            _make_page(1, table=None, text="Line one\nLine two"),
        ]
        result = self._run(pages)
        assert result.pages[0].method == "text"
        assert result.pages[0].rows == [{"line": "Line one"}, {"line": "Line two"}]

    def test_fallback_to_text_when_table_is_empty_list(self):
        pages = [
            _make_page(1, table=[], text="Some text here"),
        ]
        result = self._run(pages)
        assert result.pages[0].method == "text"

    def test_empty_page_is_skipped(self):
        pages = [
            _make_page(1, table=None, text=""),       # empty — skipped
            _make_page(2, table=None, text="Content"),
        ]
        result = self._run(pages)
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 2

    def test_raw_text_always_stored(self):
        pages = [
            _make_page(1, table=[["Date", "Amount"], ["2024-01-01", "50"]], text="Date Amount\n2024-01-01 50"),
        ]
        result = self._run(pages)
        assert "Date Amount" in result.pages[0].raw_text

    def test_mixed_pages_table_and_text(self):
        pages = [
            _make_page(1, table=[["Date", "Amount"], ["2024-01-01", "100"]], text="header text"),
            _make_page(2, table=None, text="Free text page"),
        ]
        result = self._run(pages)
        assert len(result.pages) == 2
        assert result.pages[0].method == "table"
        assert result.pages[1].method == "text"

    def test_password_protected_raises_permission_error(self):
        fake_path = MagicMock(spec=Path)
        fake_path.name = "locked.pdf"
        fake_path.stat.return_value.st_size = 512

        with patch(
            "pdfplumber.open",
            side_effect=Exception("encrypted PDF"),
        ):
            extractor = BankStatementExtractor()
            with pytest.raises(PermissionError, match="password-protected"):
                extractor.extract(fake_path)


# ---------------------------------------------------------------------------
# ExtractorFactory + top-level extract()
# ---------------------------------------------------------------------------

class TestExtractorFactory:
    def test_returns_bank_statement_extractor(self):
        factory_result = ExtractorFactory.get_extractor(Path("any.pdf"))
        assert isinstance(factory_result, BankStatementExtractor)


class TestExtractFunction:
    def test_top_level_extract_delegates_to_factory(self):
        fake_path = MagicMock(spec=Path)
        fake_path.name = "test.pdf"
        fake_path.stat.return_value.st_size = 256

        pdf_mock = _mock_pdf([_make_page(1, table=None, text="Hello")])

        with patch("pdfplumber.open", return_value=pdf_mock):
            result = extract(fake_path)

        assert isinstance(result, RawExtractionResult)
        assert result.file_name == "test.pdf"
