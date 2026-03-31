from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

app = typer.Typer(
    name="fv-engine",
    help="Financial Vetting Engine — analyse bank statement PDFs.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    invoke_without_command=True,
    context_settings={"allow_interspersed_args": True},
)
console = Console()
err_console = Console(stderr=True)

OUTPUTS_DIR = Path(__file__).parent / "outputs"

_CATEGORY_COLORS = {
    "salary":       "bold green",
    "rent":         "yellow",
    "utilities":    "cyan",
    "groceries":    "blue",
    "dining":       "magenta",
    "transfer":     "white",
    "loan_payment": "red",
    "gambling":     "bold red",
    "atm":          "dim white",
    "other":        "dim",
}

_RISK_COLORS = {
    "low":    "green",
    "medium": "yellow",
    "high":   "bold red",
}


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------

def _render_extraction(result, page_slice, rows: int) -> str:
    lines = []
    lines.append(f"# Extraction Report — {result.file_name}")
    lines.append(f"\n_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append("## Summary\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| File | {result.file_name} |")
    lines.append(f"| Size | {result.file_size_bytes / 1024:.1f} KB |")
    lines.append(f"| PDF pages | {result.page_count} |")
    lines.append(f"| Processed pages | {len(result.pages)} |")
    for page in page_slice:
        lines.append(f"\n## Page {page.page_number} — {page.method.upper()} ({len(page.rows)} rows)\n")
        if not page.rows:
            lines.append("_(empty)_\n")
            continue
        sample = page.rows[:rows]
        if page.method == "table" and sample:
            cols = list(sample[0].keys())
            lines.append("| " + " | ".join(cols) + " |")
            lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
            for row in sample:
                lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        else:
            for row in sample:
                lines.append(f"- {row.get('line', '')}")
        if len(page.rows) > rows:
            lines.append(f"\n_… {len(page.rows) - rows} more rows_")
        if page.raw_text.strip():
            lines.append(f"\n<details><summary>Raw text</summary>\n\n```\n{page.raw_text.strip()}\n```\n</details>")
    return "\n".join(lines) + "\n"


def _render_normalize(txns, file_name: str) -> str:
    lines = []
    lines.append(f"# Normalize Report — {file_name}")
    lines.append(f"\n_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append(f"**Total transactions:** {len(txns)}\n")
    cats = Counter(t.category.value for t in txns)
    lines.append("## Category Breakdown\n")
    lines.append("| Category | Count |")
    lines.append("|---|---|")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {count} |")
    lines.append("\n## Transactions\n")
    lines.append("| # | Date | Type | Amount | Category | Description |")
    lines.append("|---|---|---|---|---|---|")
    for i, t in enumerate(txns, 1):
        lines.append(f"| {i} | {t.date} | {t.transaction_type.value} | {t.amount} | {t.category.value} | {t.description} |")
    return "\n".join(lines) + "\n"


def _score_bar(score: int, width: int = 20) -> str:
    filled = round(score / 100 * width)
    empty  = width - filled
    color  = "green" if score >= 70 else "yellow" if score >= 40 else "bold red"
    return f"[{color}]{'█' * filled}[/{color}]{'░' * empty}  {score}/100"


def _yn(value) -> str:
    if value is True:
        return "[green]✓  Yes[/green]"
    if value is False:
        return "[red]✗  No[/red]"
    return "[dim]—  N/A[/dim]"


def _show_corroboration(result, has_stub: bool) -> None:
    from financial_vetting_engine.schemas.corroboration import CorroborationResult

    if not has_stub:
        console.print("\n[dim]No pay stub provided — corroboration skipped.[/dim]")
        return

    d = result.pay_stub_data

    stub_lines = _score_bar(result.corroboration_score)
    if d:
        if d.employer_name:
            stub_lines += f"\n[bold]Employer:[/]   {d.employer_name}"
        if d.employee_name:
            stub_lines += f"\n[bold]Employee:[/]   {d.employee_name}"
        if d.pay_date:
            stub_lines += f"\n[bold]Pay Date:[/]   {d.pay_date}"
        if d.gross_pay is not None:
            stub_lines += f"\n[bold]Gross Pay:[/]  ${d.gross_pay:,.2f}"
        if d.net_pay is not None:
            stub_lines += f"    [bold]Net Pay:[/] ${d.net_pay:,.2f}"
        if d.pay_frequency:
            stub_lines += f"\n[bold]Frequency:[/]  {d.pay_frequency}"

    score_color = "green" if result.corroboration_score >= 70 else "yellow" if result.corroboration_score >= 40 else "red"
    console.print(Panel(
        stub_lines,
        title=f"[bold {score_color}]Corroboration Score: {result.corroboration_score}/100",
        border_style=score_color,
    ))

    # Gap analysis
    gap_lines  = f"[bold]Declared net pay:[/]  {f'${result.declared_net_pay:,.2f}' if result.declared_net_pay else '[dim]N/A[/dim]'}\n"
    gap_lines += f"[bold]Observed deposit:[/]  {f'${result.observed_deposit:,.2f}' if result.observed_deposit else '[dim]not found[/dim]'}\n"
    if result.gap_amount is not None:
        gap_color  = "green" if result.gap_percent <= 5 else "yellow" if result.gap_percent <= 15 else "bold red"
        gap_lines += f"[bold]Gap:[/]               [{gap_color}]${result.gap_amount:,.2f}  ({result.gap_percent:.2f}%)[/{gap_color}]\n"
    else:
        gap_lines += "[bold]Gap:[/]               [dim]N/A[/dim]\n"
    gap_lines += f"[bold]Employer match:[/]    {_yn(result.employer_name_match)}\n"
    gap_lines += f"[bold]Freq match:[/]        {_yn(result.pay_frequency_match)}"
    console.print(Panel(gap_lines, title="Gap Analysis", border_style="dim"))

    # Notes
    if result.notes:
        for note in result.notes:
            console.print(f"  [dim]·[/dim] {note}")

    # Corroboration flags
    if result.corroboration_flags:
        cf_table = Table("Level", "Code", "Description", box=box.SIMPLE_HEAD, header_style="bold magenta")
        for f in result.corroboration_flags:
            rc = _RISK_COLORS.get(f.level.value, "white")
            cf_table.add_row(
                f"[{rc}]{f.level.value.upper()}[/{rc}]",
                f.code,
                f.description,
            )
        console.print(Panel(
            cf_table,
            title=f"[bold red]Corroboration Flags ({len(result.corroboration_flags)})",
            border_style="red",
        ))
        for f in result.corroboration_flags:
            rc = _RISK_COLORS.get(f.level.value, "white")
            console.print(f"\n[{rc}][bold]{f.code}[/bold][/{rc}]")
            for e in f.evidence:
                console.print(f"  [dim]·[/dim] {e}")
            if f.recommendation:
                console.print(f"  [italic dim]→ {f.recommendation}[/italic dim]")


def _render_corroboration(result, has_stub: bool) -> str:
    lines = ["\n## Corroboration\n"]
    if not has_stub:
        lines.append("_No pay stub provided — corroboration skipped._\n")
        return "\n".join(lines)

    lines.append(f"**Corroboration Score: {result.corroboration_score}/100**\n")

    d = result.pay_stub_data
    if d:
        lines.append("### Pay Stub Fields\n")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        if d.employer_name:
            lines.append(f"| Employer | {d.employer_name} |")
        if d.employee_name:
            lines.append(f"| Employee | {d.employee_name} |")
        if d.pay_date:
            lines.append(f"| Pay Date | {d.pay_date} |")
        if d.pay_period_start:
            lines.append(f"| Pay Period | {d.pay_period_start} – {d.pay_period_end} |")
        if d.gross_pay is not None:
            lines.append(f"| Gross Pay | ${d.gross_pay:,.2f} |")
        if d.net_pay is not None:
            lines.append(f"| Net Pay | ${d.net_pay:,.2f} |")
        if d.federal_tax is not None:
            lines.append(f"| Federal Tax | ${d.federal_tax:,.2f} |")
        if d.state_tax is not None:
            lines.append(f"| State Tax | ${d.state_tax:,.2f} |")
        if d.pay_frequency:
            lines.append(f"| Pay Frequency | {d.pay_frequency} |")
        if d.ytd_gross is not None:
            lines.append(f"| YTD Gross | ${d.ytd_gross:,.2f} |")

    lines.append("\n### Gap Analysis\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Declared Net Pay | {f'${result.declared_net_pay:,.2f}' if result.declared_net_pay else 'N/A'} |")
    lines.append(f"| Observed Deposit | {f'${result.observed_deposit:,.2f}' if result.observed_deposit else 'not found'} |")
    if result.gap_amount is not None:
        lines.append(f"| Gap | ${result.gap_amount:,.2f} ({result.gap_percent:.2f}%) |")
    lines.append(f"| Employer Match | {'Yes' if result.employer_name_match else 'No' if result.employer_name_match is False else 'N/A'} |")
    lines.append(f"| Freq Match | {'Yes' if result.pay_frequency_match else 'No' if result.pay_frequency_match is False else 'N/A'} |")

    if result.notes:
        lines.append("\n### Notes\n")
        for note in result.notes:
            lines.append(f"- {note}")

    if result.corroboration_flags:
        lines.append(f"\n### Corroboration Flags ({len(result.corroboration_flags)})\n")
        for f in result.corroboration_flags:
            lines.append(f"#### [{f.level.value.upper()}] {f.code}")
            lines.append(f"{f.description}\n")
            for e in f.evidence:
                lines.append(f"- {e}")
            if f.recommendation:
                lines.append(f"\n_→ {f.recommendation}_")
            lines.append("")

    return "\n".join(lines) + "\n"


def _render_analyze(txns, metrics, flags, file_name: str, corr=None, has_stub: bool = False) -> str:
    lines = []
    lines.append(f"# Analysis Report — {file_name}")
    lines.append(f"\n_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
    lines.append("## Financial Metrics\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total Income | ${metrics.total_income:,.2f} |")
    lines.append(f"| Total Expenses | ${metrics.total_expenses:,.2f} |")
    lines.append(f"| Net Cashflow | ${metrics.net_cashflow:,.2f} |")
    lines.append(f"| Avg Monthly Income | ${metrics.avg_monthly_income:,.2f} |")
    lines.append(f"| Avg Monthly Expenses | ${metrics.avg_monthly_expenses:,.2f} |")
    lines.append(f"| Expense-to-Income Ratio | {metrics.expense_to_income_ratio:.2f} |")
    lines.append(f"| Largest Single Expense | ${metrics.largest_single_expense:,.2f} |")
    lines.append(f"| Transaction Count | {metrics.transaction_count} |")
    lines.append("\n## Monthly Breakdown\n")
    lines.append("| Month | Income | Expenses | Net |")
    lines.append("|---|---|---|---|")
    for b in metrics.monthly_breakdown:
        lines.append(f"| {b.month} | ${b.total_income:,.2f} | ${b.total_expenses:,.2f} | ${b.net:,.2f} |")
    lines.append("\n## Top Expense Categories\n")
    lines.append("| Category | Total |")
    lines.append("|---|---|")
    for cat, total in metrics.top_expense_categories.items():
        lines.append(f"| {cat} | ${total:,.2f} |")
    lines.append(f"\n## Risk Flags ({len(flags)} detected)\n")
    if not flags:
        lines.append("_No risk flags detected._\n")
    for f in flags:
        lines.append(f"### [{f.level.upper()}] {f.code}")
        lines.append(f"{f.description}\n")
        for e in f.evidence:
            lines.append(f"- {e}")
        if f.recommendation:
            lines.append(f"\n_→ {f.recommendation}_")
        lines.append("")
    if corr is not None:
        lines.append(_render_corroboration(corr, has_stub))
    return "\n".join(lines) + "\n"


def _save(stem: str, suffix: str, md: str, txt: str) -> tuple[Path, Path]:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{stem}_{suffix}_{ts}"
    md_path  = OUTPUTS_DIR / f"{base}.md"
    txt_path = OUTPUTS_DIR / f"{base}.txt"
    md_path.write_text(md, encoding="utf-8")
    txt_path.write_text(txt, encoding="utf-8")
    return md_path, txt_path


def _print_saved(md_path: Path, txt_path: Path) -> None:
    console.print(Panel(
        f"[bold]Markdown:[/] {md_path}\n[bold]Text:[/]     {txt_path}",
        title="[bold green]Saved",
        border_style="dim green",
    ))


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _show_extraction(result, page_slice, rows: int) -> None:
    summary = (
        f"[bold]File:[/]       {result.file_name}\n"
        f"[bold]Size:[/]       {result.file_size_bytes / 1024:.1f} KB\n"
        f"[bold]PDF pages:[/]  {result.page_count}\n"
        f"[bold]Processed:[/]  {len(result.pages)} non-empty pages"
    )
    console.print(Panel(summary, title="[bold green]Extraction", border_style="green"))
    for page in page_slice:
        color = "blue" if page.method == "table" else "yellow"
        console.print(f"\n[bold]Page {page.page_number}  [{color}]{page.method.upper()}[/{color}]  — {len(page.rows)} rows[/]")
        if not page.rows:
            console.print("  [dim](no rows)[/dim]")
            continue
        sample = page.rows[:rows]
        if page.method == "table":
            cols = list(sample[0].keys())
            t = Table(*cols, box=box.SIMPLE_HEAD, header_style="bold magenta")
            for row in sample:
                t.add_row(*[row.get(c, "") for c in cols])
            console.print(t)
        else:
            for row in sample:
                console.print(f"  [dim]›[/dim] {row.get('line', '')}")
        if len(page.rows) > rows:
            console.print(f"  [dim]… {len(page.rows) - rows} more rows[/dim]")


def _show_normalize(txns, limit: Optional[int] = None) -> None:
    cats = Counter(t.category.value for t in txns)
    total_credits = sum(t.amount for t in txns if t.transaction_type.value == "credit")
    total_debits  = sum(t.amount for t in txns if t.transaction_type.value == "debit")
    summary = (
        f"[bold]Transactions:[/]  {len(txns)}\n"
        f"[bold]Total credits:[/] {total_credits:,.2f}\n"
        f"[bold]Total debits:[/]  {total_debits:,.2f}\n"
        f"[bold]Categories:[/]    {', '.join(f'{k}({v})' for k, v in sorted(cats.items(), key=lambda x: -x[1]))}"
    )
    console.print(Panel(summary, title="[bold green]Normalize", border_style="green"))
    display = txns[:limit] if limit else txns
    t = Table("#", "Date", "Type", "Amount", "Category", "Description",
              box=box.SIMPLE_HEAD, header_style="bold magenta")
    for i, txn in enumerate(display, 1):
        cc = _CATEGORY_COLORS.get(txn.category.value, "white")
        tc = "green" if txn.transaction_type.value == "credit" else "red"
        t.add_row(
            str(i), str(txn.date),
            f"[{tc}]{txn.transaction_type.value}[/{tc}]",
            f"{txn.amount:,.2f}",
            f"[{cc}]{txn.category.value}[/{cc}]",
            txn.description[:50],
        )
    console.print(t)
    if limit and len(txns) > limit:
        console.print(f"[dim]… {len(txns) - limit} more (remove --limit to see all)[/dim]")


def _show_analyze(metrics, flags) -> None:
    m = metrics
    summary = (
        f"[bold]Income:[/]      ${m.total_income:>12,.2f}    "
        f"[bold]Expenses:[/] ${m.total_expenses:>12,.2f}\n"
        f"[bold]Net:[/]         ${m.net_cashflow:>12,.2f}    "
        f"[bold]Ratio:[/]    {m.expense_to_income_ratio:.2f}\n"
        f"[bold]Avg Income/mo:[/]  ${m.avg_monthly_income:>10,.2f}    "
        f"[bold]Avg Exp/mo:[/] ${m.avg_monthly_expenses:>10,.2f}\n"
        f"[bold]Largest expense:[/] ${m.largest_single_expense:,.2f}    "
        f"[bold]Transactions:[/] {m.transaction_count}"
    )
    console.print(Panel(summary, title="[bold green]Financial Metrics", border_style="green"))

    # Monthly breakdown
    mb = Table("Month", "Income", "Expenses", "Net", box=box.SIMPLE_HEAD, header_style="bold magenta")
    for b in m.monthly_breakdown:
        net_color = "green" if b.net >= 0 else "red"
        mb.add_row(b.month, f"${b.total_income:,.2f}", f"${b.total_expenses:,.2f}",
                   f"[{net_color}]${b.net:,.2f}[/{net_color}]")
    console.print(mb)

    # Top categories
    if m.top_expense_categories:
        ct = Table("Category", "Total", box=box.SIMPLE_HEAD, header_style="bold magenta")
        for cat, total in m.top_expense_categories.items():
            cc = _CATEGORY_COLORS.get(cat, "white")
            ct.add_row(f"[{cc}]{cat}[/{cc}]", f"${total:,.2f}")
        console.print(ct)

    # Risk flags
    if not flags:
        console.print(Panel("[green]No risk flags detected.[/]", title="Risk Flags", border_style="green"))
    else:
        flag_table = Table("Level", "Code", "Description", box=box.SIMPLE_HEAD, header_style="bold magenta")
        for f in flags:
            rc = _RISK_COLORS.get(f.level.value, "white")
            flag_table.add_row(
                f"[{rc}]{f.level.value.upper()}[/{rc}]",
                f.code,
                f.description,
            )
        console.print(Panel(flag_table, title=f"[bold red]Risk Flags ({len(flags)})", border_style="red"))
        for f in flags:
            rc = _RISK_COLORS.get(f.level.value, "white")
            console.print(f"\n[{rc}][bold]{f.code}[/bold][/{rc}]")
            for e in f.evidence:
                console.print(f"  [dim]·[/dim] {e}")


# ---------------------------------------------------------------------------
# Main pipeline — invoked directly as: fv-engine statement.pdf [options]
# ---------------------------------------------------------------------------

@app.callback()
def run(
    ctx: typer.Context,
    pdf: Optional[Path] = typer.Argument(None, help="Path to the bank statement PDF."),
    pay_stub: Optional[Path] = typer.Option(None, "--pay-stub", "-s", help="Path to a pay stub PDF for cross-document corroboration."),
    extract_only: bool = typer.Option(False, "--extract-only", help="Stop after extraction."),
    normalize_only: bool = typer.Option(False, "--normalize-only", help="Stop after normalization."),
    rows: int = typer.Option(3, "--rows", "-r", help="Sample rows to preview per page (extraction view)."),
    pages: Optional[int] = typer.Option(None, "--pages", "-p", help="Limit pages shown in extraction view."),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Limit transactions shown in normalize view."),
    no_save: bool = typer.Option(False, "--no-save", help="Skip saving output files to src/outputs/."),
) -> None:
    """Run the vetting pipeline: extract > normalize > analyze > corroborate.

    Pass --pay-stub to cross-reference a pay stub PDF against the bank statement.
    Use --extract-only or --normalize-only to stop at an earlier stage.
    """
    if ctx.invoked_subcommand is not None or pdf is None:
        return

    if not pdf.exists():
        err_console.print(f"[bold red]Error:[/] File not found: {pdf}")
        raise typer.Exit(code=1)
    if not pdf.is_file():
        err_console.print(f"[bold red]Error:[/] Not a file: {pdf}")
        raise typer.Exit(code=1)

    save = not no_save
    from financial_vetting_engine.services.extractor import extract as run_extract

    console.print(f"\n[bold cyan]Extracting[/] [white]{pdf.name}[/] …")
    try:
        raw = run_extract(pdf)
    except PermissionError as exc:
        err_console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(code=1)

    page_slice = raw.pages[:pages] if pages else raw.pages
    _show_extraction(raw, page_slice, rows)

    if save and extract_only:
        md  = _render_extraction(raw, page_slice, rows)
        txt = md  # text version identical for extraction
        md_path, txt_path = _save(pdf.stem, "extracted", md, txt)
        _print_saved(md_path, txt_path)

    if extract_only:
        return

    # --- Normalize ---
    from financial_vetting_engine.services.normalizer import normalize as run_normalize

    console.print(f"\n[bold cyan]Normalizing[/] …")
    txns = run_normalize(raw)

    if not txns:
        console.print("[yellow]No transactions found — PDF may be text-only or use an unsupported layout.[/]")
        raise typer.Exit()

    _show_normalize(txns, limit)

    if save and normalize_only:
        md  = _render_normalize(txns, pdf.name)
        md_path, txt_path = _save(pdf.stem, "normalized", md, md)
        _print_saved(md_path, txt_path)

    if normalize_only:
        return

    # --- Analyze ---
    from financial_vetting_engine.services.analyzer import analyze as run_analyze
    from financial_vetting_engine.services.flagger import detect_flags

    console.print(f"\n[bold cyan]Analyzing[/] …\n")
    metrics, scores = run_analyze(txns)
    flags = detect_flags(txns, metrics, scores)
    _show_analyze(metrics, flags)

    # --- Corroborate ---
    from financial_vetting_engine.services.corroborator import corroborate
    from financial_vetting_engine.services.extractor import PayStubExtractor

    stub_raw = None
    if pay_stub:
        if not pay_stub.exists():
            err_console.print(f"[bold red]Error:[/] Pay stub not found: {pay_stub}")
            raise typer.Exit(code=1)
        if not pay_stub.is_file():
            err_console.print(f"[bold red]Error:[/] Not a file: {pay_stub}")
            raise typer.Exit(code=1)
        console.print(f"\n[bold cyan]Corroborating[/] pay stub [white]{pay_stub.name}[/] …\n")
        try:
            stub_raw = PayStubExtractor().extract(pay_stub)
        except PermissionError as exc:
            err_console.print(f"[bold red]Error:[/] {exc}")
            raise typer.Exit(code=1)

    corr = corroborate(txns, stub_raw)
    _show_corroboration(corr, pay_stub is not None)

    if save:
        md  = _render_analyze(txns, metrics, flags, pdf.name, corr, has_stub=pay_stub is not None)
        md_path, txt_path = _save(pdf.stem, "analysis", md, md)
        _print_saved(md_path, txt_path)


# ---------------------------------------------------------------------------
# info subcommand
# ---------------------------------------------------------------------------

@app.command()
def info(
    pdf: Path = typer.Argument(..., help="Path to the PDF file.", exists=True, readable=True),
) -> None:
    """Show basic file info without running the pipeline."""
    import os
    size_kb = os.path.getsize(pdf) / 1024
    console.print(Panel(
        f"[bold]Name:[/]  {pdf.name}\n"
        f"[bold]Path:[/]  {pdf.resolve()}\n"
        f"[bold]Size:[/]  {size_kb:.1f} KB",
        title="[bold blue]File Info",
        border_style="blue",
    ))
