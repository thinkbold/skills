"""Local PDF extraction and OCR staging for selected bookkeeping ledgers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import re
from typing import Any, Callable

from .contracts import AccountContext, ImportResult, Issue
from .importing import CsvMapping, parse_decimal, serialize_decimal
from .storage import sha256_file


@dataclass(frozen=True)
class PdfCapabilities:
    pdfplumber: bool
    ocrmypdf: str | None


@dataclass(frozen=True)
class PdfPage:
    page_number: int
    text: str
    tables: tuple[tuple[tuple[str, ...], ...], ...]
    confidence: str


@dataclass(frozen=True)
class PdfExtraction:
    pages: tuple[PdfPage, ...]
    method: str
    issues: tuple[Issue, ...]
    staged_pdf: Path | None = None


OcrRunner = Callable[[Path, Path, str], Path]
_MASKED_LABEL = re.compile(r"^\*+[^\d]*\d{4}$")


def detect_pdf_capabilities() -> PdfCapabilities:
    """Report locally available PDF extraction tools without installing anything."""
    return PdfCapabilities(
        pdfplumber=importlib.util.find_spec("pdfplumber") is not None,
        ocrmypdf=shutil.which("ocrmypdf"),
    )


def _issue(code: str, message: str, source: Path, location: str = "") -> Issue:
    return Issue(code, message, source_file=source.name, source_location=location)


def _load_reader() -> Any:
    import pdfplumber

    return pdfplumber


def _tables(page: Any) -> tuple[tuple[tuple[str, ...], ...], ...]:
    extracted = page.extract_tables() or ()
    output: list[tuple[tuple[str, ...], ...]] = []
    for table in extracted:
        output.append(tuple(tuple("" if cell is None else str(cell).strip() for cell in row) for row in table))
    return tuple(output)


def _read_pages(source: Path, reader: PdfReader) -> tuple[PdfPage, ...]:
    pages: list[PdfPage] = []
    with reader.open(source) as document:
        for page_number, page in enumerate(document.pages, start=1):
            text = (page.extract_text() or "").strip()
            tables = _tables(page)
            table_content = any(cell for table in tables for row in table for cell in row)
            content_present = bool("".join(text.split()) or table_content)
            pages.append(PdfPage(page_number, text, tables, "high" if content_present else "low"))
    return tuple(pages)


def _is_encrypted(error: Exception) -> bool:
    description = f"{type(error).__name__}: {error}".casefold()
    return "encrypt" in description or "password" in description


def run_local_ocr(source: Path, staged_pdf: Path, executable: str) -> Path:
    """Create a searchable copy locally, without replacing the statement source."""
    staged_pdf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [executable, "--skip-text", str(source), str(staged_pdf)],
        check=True,
        capture_output=True,
        text=True,
    )
    if not staged_pdf.is_file():
        raise RuntimeError("local OCR did not create a staged PDF")
    return staged_pdf


def _staged_ocr_path(source: Path, work_dir: Path) -> Path:
    source_hash = sha256_file(source)
    return Path(work_dir) / "pdf-ocr" / source_hash / f"{source.stem}-searchable.pdf"


def extract_pdf_pages(
    source: Path,
    work_dir: Path,
    capabilities: PdfCapabilities | None = None,
    *,
    ocr_runner: OcrRunner | None = None,
) -> PdfExtraction:
    """Extract each page locally and OCR only image-only PDFs into the ledger work area."""
    source = Path(source)
    capabilities = capabilities or detect_pdf_capabilities()
    if not capabilities.pdfplumber:
        return PdfExtraction((), "local_pdf_text", (_issue(
            "PDF_LIBRARY_UNAVAILABLE", "Local PDF extraction requires the configured PDF library.", source,
        ),))
    try:
        reader = _load_reader()
        pages = _read_pages(source, reader)
    except Exception as error:  # The third-party parser controls its exception hierarchy.
        code = "PDF_ENCRYPTED" if _is_encrypted(error) else "PDF_PAGE_EMPTY"
        message = "The PDF is encrypted and requires a local password workflow." if code == "PDF_ENCRYPTED" else "The PDF could not be read locally."
        return PdfExtraction((), "local_pdf_text", (_issue(code, message, source),))

    if pages and all(page.confidence == "high" for page in pages):
        return PdfExtraction(pages, "local_pdf_text", ())
    if not capabilities.ocrmypdf:
        return PdfExtraction(pages, "local_pdf_text", (_issue(
            "LOCAL_OCR_UNAVAILABLE", "A page has no local text or table data and local OCR is unavailable.", source,
        ),))

    staged_pdf = _staged_ocr_path(source, work_dir)
    try:
        staged_pdf.parent.mkdir(parents=True, exist_ok=True)
        runner = ocr_runner or run_local_ocr
        staged_pdf = Path(runner(source, staged_pdf, capabilities.ocrmypdf))
        if not staged_pdf.resolve().is_relative_to((Path(work_dir) / "pdf-ocr").resolve()):
            raise ValueError("OCR staging path is outside the ledger work directory")
        ocr_pages = _read_pages(staged_pdf, reader)
    except Exception:
        return PdfExtraction((), "local_ocr", (_issue(
            "LOCAL_OCR_FAILED", "Local OCR could not create a searchable staged PDF.", source,
        ),), staged_pdf=staged_pdf)
    if not ocr_pages or any(page.confidence != "high" for page in ocr_pages):
        return PdfExtraction(ocr_pages, "local_ocr", (_issue(
            "PDF_PAGE_EMPTY", "A PDF page has no local text or table data after OCR.", source,
        ),), staged_pdf=staged_pdf)
    return PdfExtraction(ocr_pages, "local_ocr", (), staged_pdf=staged_pdf)


def _mapping_headers(mapping: CsvMapping) -> tuple[str, ...]:
    return tuple(value for value in (
        mapping.transaction_date, mapping.posting_date, mapping.description,
        mapping.debit, mapping.credit, mapping.balance, mapping.reference,
    ) if value)


def _account_issue(account: AccountContext) -> Issue | None:
    if not account.currency.strip():
        return Issue("CURRENCY_MISSING", "A currency is required for each import.")
    if not all((account.account_id, account.institution, account.masked_label)):
        return Issue("ACCOUNT_UNCONFIRMED", "A confirmed account context is required.")
    if not _MASKED_LABEL.fullmatch(account.masked_label):
        return Issue("ACCOUNT_UNCONFIRMED", "Account labels must be explicitly masked before import.")
    return None


def _parse_date(value: str, formats: tuple[str, ...]) -> str:
    for date_format in formats:
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("date is not in a confirmed format")


def _pdf_row(
    raw: dict[str, str], source_file: str, source_hash: str, location: str,
    mapping: CsvMapping, account: AccountContext, method: str, confidence: str,
) -> dict[str, str]:
    transaction_date = _parse_date(raw[mapping.transaction_date], mapping.date_formats)
    posting_date = transaction_date
    if mapping.posting_date and raw[mapping.posting_date].strip():
        posting_date = _parse_date(raw[mapping.posting_date], mapping.date_formats)
    debit_text = raw[mapping.debit].strip() if mapping.debit else ""
    credit_text = raw[mapping.credit].strip() if mapping.credit else ""
    if not debit_text and not credit_text:
        raise ValueError("a debit or credit amount is required")
    debit = abs(parse_decimal(debit_text)) if debit_text else parse_decimal("")
    credit = abs(parse_decimal(credit_text)) if credit_text else parse_decimal("")
    if debit and credit:
        raise ValueError("simultaneous debit and credit")
    if not debit and not credit:
        raise ValueError("a transaction amount cannot be zero")
    balance_text = raw[mapping.balance].strip() if mapping.balance else ""
    if not balance_text:
        raise ValueError("a running balance amount is required")
    balance = parse_decimal(balance_text)
    transaction_id = hashlib.sha256(f"{source_file}:{source_hash}:{location}".encode("utf-8")).hexdigest()
    return {
        "transaction_id": transaction_id,
        "account_id": account.account_id,
        "currency": account.currency,
        "transaction_date": transaction_date,
        "posting_date": posting_date,
        "raw_description": raw[mapping.description],
        "normalized_merchant": "",
        "inflow": serialize_decimal(credit),
        "outflow": serialize_decimal(debit),
        "running_balance": serialize_decimal(balance),
        "reference": raw[mapping.reference] if mapping.reference else "",
        "source_file": source_file,
        "source_page_or_row": location,
        "extraction_method": method,
        "extraction_confidence": confidence,
        "classification_status": "unclassified",
        "account_code": "",
        "account_name": "",
        "rule_id": "",
        "review_note": "",
        "source_locations": f"{source_file}:{location}",
    }


def map_pdf_tables(
    extraction: PdfExtraction,
    mapping: CsvMapping,
    account: AccountContext,
    *,
    source_file: str,
    source_hash: str,
) -> ImportResult:
    """Map only exact confirmed PDF table headers to canonical rows with page provenance."""
    if extraction.issues:
        return ImportResult(issues=extraction.issues)
    account_issue = _account_issue(account)
    if account_issue is not None:
        return ImportResult(issues=(account_issue,))
    headers = _mapping_headers(mapping)
    rows: list[dict[str, str]] = []
    issues: list[Issue] = []
    matched_table = False
    for page in extraction.pages:
        for table in page.tables:
            if not table:
                continue
            header = table[0]
            if any(label not in header for label in headers):
                continue
            matched_table = True
            indexes = {label: header.index(label) for label in headers}
            for row_number, values in enumerate(table[1:], start=2):
                if len(values) < len(header):
                    issues.append(Issue(
                        "PDF_TABLE_UNMAPPABLE", "A confirmed PDF table row is incomplete.",
                        source_file=source_file, source_location=f"page:{page.page_number}/row:{row_number}",
                    ))
                    continue
                raw = {label: values[index] for label, index in indexes.items()}
                location = f"page:{page.page_number}/row:{row_number}"
                try:
                    rows.append(_pdf_row(raw, source_file, source_hash, location, mapping, account, extraction.method, page.confidence))
                except ValueError:
                    issues.append(Issue(
                        "PDF_TABLE_UNMAPPABLE", "A confirmed PDF table row has invalid required values.",
                        source_file=source_file, source_location=location,
                    ))
    if not matched_table:
        issues.append(Issue(
            "PDF_TABLE_UNMAPPABLE", "PDF tables require exact user-confirmed header labels.", source_file=source_file,
        ))
    return ImportResult(transactions=tuple(rows) if not issues else (), issues=tuple(issues), source_hashes={source_file: source_hash})
