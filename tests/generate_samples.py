"""
Generate synthetic bank statement PDFs for integration testing.

Creates three PDFs in tests/sample_statements/:
  chase_checking_3mo.pdf   — clean 3-month statement, expected LOW risk
  high_risk_statement.pdf  — 2-month statement designed to trigger HIGH flags
  text_layout_statement.pdf — plain text layout (no table), forces text fallback

After generating each file, runs the extractor against it and prints a summary.

Usage:
    uv run python tests/generate_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path so we can import the package without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SAMPLES_DIR = Path(__file__).parent / "sample_statements"
SAMPLES_DIR.mkdir(exist_ok=True)

_HEADER_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003087")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (2, 1), (4, -1), "RIGHT"),  # Debit/Credit/Balance right-aligned
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
)


def _build_table(data: list[list[str]]) -> Table:
    col_widths = [0.85 * inch, 2.9 * inch, 0.85 * inch, 0.85 * inch, 1.0 * inch]
    t = Table(data, colWidths=col_widths)
    t.setStyle(_HEADER_STYLE)
    return t


# ---------------------------------------------------------------------------
# 1. chase_checking_3mo.pdf — clean 3-month statement
# ---------------------------------------------------------------------------

def build_chase_3mo() -> Path:
    dest = SAMPLES_DIR / "chase_checking_3mo.pdf"
    doc = SimpleDocTemplate(str(dest), pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()

    elements = []
    elements.append(Paragraph("<b>Chase</b>", styles["Title"]))
    elements.append(Paragraph("Account Number: ...4521", styles["Normal"]))
    elements.append(Paragraph("Statement Period: January 1 – March 31, 2024", styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))

    header = ["Date", "Description", "Debit", "Credit", "Balance"]
    rows = [
        # --- January ---
        ["01/03/2024", "Opening Balance",          "",         "",          "1300.00"],
        ["01/15/2024", "GUSTO PAYROLL 01/15",      "",         "3200.00",   "4500.00"],
        ["01/17/2024", "RENT PAYMENT JAN",          "1800.00",  "",          "2700.00"],
        ["01/20/2024", "WHOLE FOODS MKT #123",      "124.50",   "",          "2575.50"],
        ["01/22/2024", "DOORDASH*ORDER",             "34.20",    "",          "2541.30"],
        ["01/25/2024", "VERIZON WIRELESS PMT",       "85.00",    "",          "2456.30"],
        ["01/28/2024", "NETFLIX.COM",                "17.99",    "",          "2438.31"],
        ["01/30/2024", "SHELL OIL STATION",          "62.40",    "",          "2375.91"],
        # --- February ---
        ["02/15/2024", "GUSTO PAYROLL 02/15",       "",         "3200.00",   "5575.91"],
        ["02/17/2024", "RENT PAYMENT FEB",           "1800.00",  "",          "3775.91"],
        ["02/20/2024", "TRADER JOES #4521",          "88.30",    "",          "3687.61"],
        ["02/21/2024", "WHOLE FOODS MKT #123",       "98.75",    "",          "3588.86"],
        ["02/22/2024", "GRUBHUB ORDER",              "29.45",    "",          "3559.41"],
        ["02/24/2024", "COMCAST INTERNET",           "89.99",    "",          "3469.42"],
        ["02/26/2024", "AMAZON PRIME",               "14.99",    "",          "3454.43"],
        ["02/28/2024", "CHEVRON GAS STATION",        "54.80",    "",          "3399.63"],
        # --- March ---
        ["03/15/2024", "GUSTO PAYROLL 03/15",       "",         "3200.00",   "6599.63"],
        ["03/17/2024", "RENT PAYMENT MAR",           "1800.00",  "",          "4799.63"],
        ["03/19/2024", "SPROUTS FARMERS MKT",        "112.25",   "",          "4687.38"],
        ["03/21/2024", "UBER EATS ORDER",            "41.60",    "",          "4645.78"],
        ["03/22/2024", "ATM WITHDRAWAL",              "200.00",   "",          "4445.78"],
        ["03/24/2024", "T-MOBILE PAYMENT",            "75.00",    "",          "4370.78"],
        ["03/26/2024", "SPOTIFY PREMIUM",            "11.99",    "",          "4358.79"],
        ["03/28/2024", "CHEVRON GAS STATION",        "58.20",    "",          "4300.59"],
        ["03/30/2024", "WHOLE FOODS MKT #123",       "94.40",    "",          "4206.19"],
    ]

    data = [header] + rows
    elements.append(_build_table(data))
    doc.build(elements)
    return dest


# ---------------------------------------------------------------------------
# 2. high_risk_statement.pdf — designed to trigger HIGH flags
# ---------------------------------------------------------------------------

def build_high_risk() -> Path:
    dest = SAMPLES_DIR / "high_risk_statement.pdf"
    doc = SimpleDocTemplate(str(dest), pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()

    elements = []
    elements.append(Paragraph("<b>First National Bank</b>", styles["Title"]))
    elements.append(Paragraph("Account Number: ...7890", styles["Normal"]))
    elements.append(Paragraph("Statement Period: January 1 – February 28, 2024", styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))

    header = ["Date", "Description", "Debit", "Credit", "Balance"]
    rows = [
        # --- January: income $4,000, expenses $3,940 → ratio 0.985 → HIGH_EXPENSE_RATIO ---
        ["01/01/2024", "Opening Balance",           "",         "",         "2100.00"],
        ["01/15/2024", "ADP PAYROLL 01/15",         "",         "4000.00",  "6100.00"],
        ["01/16/2024", "RENT PAYMENT JAN",           "3200.00",  "",         "2900.00"],
        ["01/18/2024", "ATM CASH WITHDRAWAL",        "600.00",   "",         "2300.00"],  # large ATM
        ["01/20/2024", "GROCERY STORE",              "180.00",   "",         "2120.00"],
        ["01/22/2024", "UTILITY ELECTRIC",           "220.00",   "",         "1900.00"],
        ["01/25/2024", "ATM CASH WITHDRAWAL",        "550.00",   "",         "1350.00"],  # large ATM
        ["01/27/2024", "RESTAURANT DINING",          "190.00",   "",         "1160.00"],  # expense pushes ratio high
        # Jan total debit: 3200+600+180+220+550+190 = 4940 > 4000 → NEGATIVE_CASHFLOW
        # Running balance at Jan end: 1160 - ... let's fix

        # --- February: income $1,600 (40% of Jan), triggers INCOME_DROP ---
        ["02/15/2024", "ADP PAYROLL 02/15",         "",         "1600.00",  "2760.00"],
        ["02/16/2024", "RENT PAYMENT FEB",           "3200.00",  "",         "-440.00"],  # NEGATIVE_BALANCE
        ["02/20/2024", "GROCERY STORE",              "180.00",   "",         "-620.00"],
        ["02/22/2024", "NSF FEE",                    "35.00",    "",         "-655.00"],  # NSF event
        ["02/25/2024", "DRAFTKINGS DEPOSIT",         "200.00",   "",         "-855.00"],  # GAMBLING
    ]

    data = [header] + rows
    elements.append(_build_table(data))
    doc.build(elements)
    return dest


# ---------------------------------------------------------------------------
# 3. text_layout_statement.pdf — plain text, no table
# ---------------------------------------------------------------------------

def build_text_layout() -> Path:
    dest = SAMPLES_DIR / "text_layout_statement.pdf"
    doc = SimpleDocTemplate(str(dest), pagesize=letter, topMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    mono = styles["Code"]

    elements = []
    elements.append(Paragraph("<b>Community Credit Union</b>", styles["Title"]))
    elements.append(Paragraph("Account: ...2233 | Period: Jan 1 – Jan 31 2024", styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph("Transaction History", styles["Heading2"]))
    elements.append(Spacer(1, 0.1 * inch))

    lines = [
        "01/15/2024  DIRECT DEPOSIT PAYROLL          +$3,200.00   $4,500.00",
        "01/17/2024  RENT PAYMENT                     -$1,800.00   $2,700.00",
        "01/18/2024  WHOLE FOODS MARKET                 -$124.50   $2,575.50",
        "01/20/2024  ATM CASH WITHDRAWAL                -$200.00   $2,375.50",
        "01/22/2024  DOORDASH ORDER                      -$34.20   $2,341.30",
        "01/24/2024  VERIZON WIRELESS PMT                -$85.00   $2,256.30",
        "01/26/2024  AMAZON PURCHASE                     -$49.99   $2,206.31",
        "01/28/2024  NETFLIX.COM                         -$17.99   $2,188.32",
        "01/29/2024  SHELL GAS STATION                   -$62.40   $2,125.92",
        "01/31/2024  SPOTIFY PREMIUM                     -$11.99   $2,113.93",
    ]
    for line in lines:
        elements.append(Paragraph(line, mono))
        elements.append(Spacer(1, 0.02 * inch))

    doc.build(elements)
    return dest


# ---------------------------------------------------------------------------
# Extractor summary
# ---------------------------------------------------------------------------

def _print_summary(pdf_path: Path) -> None:
    try:
        from financial_vetting_engine.services.extractor import extract
        result = extract(pdf_path)
        print(f"\n{'='*60}")
        print(f"File    : {pdf_path.name}")
        print(f"Pages   : {result.page_count}")
        for page in result.pages:
            print(f"  Page {page.page_number}: method={page.method}, rows={len(page.rows)}")
            for row in page.rows[:3]:
                print(f"    {row}")
    except Exception as exc:
        print(f"\n{'='*60}")
        print(f"File    : {pdf_path.name}")
        print(f"Extractor skipped — {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Generating synthetic PDFs …")
    paths = [
        build_chase_3mo(),
        build_high_risk(),
        build_text_layout(),
    ]
    for p in paths:
        print(f"  [ok] {p}")

    print("\nRunning extractor against each file …")
    for p in paths:
        _print_summary(p)
