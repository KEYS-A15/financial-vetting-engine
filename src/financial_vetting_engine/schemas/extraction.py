from dataclasses import dataclass, field


@dataclass
class PageExtraction:
    page_number: int
    method: str          # "table" or "text"
    rows: list[dict]     # raw rows extracted
    raw_text: str        # full page text regardless of method


@dataclass
class RawExtractionResult:
    pages: list[PageExtraction]
    page_count: int
    file_name: str
    file_size_bytes: int
