from pathlib import Path
import json
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from bookkeeper.contracts import AccountContext
from bookkeeper.importing import CsvMapping
from bookkeeper.ledger import initialize_ledger
from bookkeeper.pdf_local import (
    PdfCapabilities,
    PdfExtraction,
    PdfPage,
    extract_pdf_pages,
    map_pdf_tables,
)


FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = CsvMapping("Date", "Description", "Debit", "Credit", "Balance", "Reference")
ACCOUNT = AccountContext("checking-001", "Synthetic Bank", "***1001", "CAD")


class _PdfPage:
    def __init__(self, text: str, tables: list[list[list[str]]] | None = None) -> None:
        self._text = text
        self._tables = tables or []

    def extract_text(self) -> str:
        return self._text

    def extract_tables(self) -> list[list[list[str]]]:
        return self._tables


class _PdfDocument:
    def __init__(self, pages: list[_PdfPage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_PdfDocument":
        return self

    def __exit__(self, *arguments: object) -> None:
        return None


class _PdfReader:
    @staticmethod
    def open(source: Path) -> _PdfDocument:
        if source.name == "scanned-statement.pdf":
            return _PdfDocument([_PdfPage("")])
        return _PdfDocument([_PdfPage("OPENAI *CHATGPT SUBSCRIPTION 9F3A2")])


class _BlankTableReader:
    @staticmethod
    def open(source: Path) -> _PdfDocument:
        return _PdfDocument([_PdfPage("", [[["", ""]]])])


class PdfLocalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.work = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_text_pdf_has_page_provenance(self) -> None:
        """Catches stripping page provenance or treating readable local PDFs as OCR inputs."""
        result = extract_pdf_pages(
            FIXTURES / "text-statement.pdf", self.work,
            PdfCapabilities(pdfplumber=True, ocrmypdf=None),
            pdf_reader=_PdfReader,
        )
        self.assertEqual("local_pdf_text", result.method)
        self.assertEqual(1, result.pages[0].page_number)
        self.assertIn("OPENAI", result.pages[0].text)
        self.assertEqual((), result.issues)

    def test_scanned_pdf_uses_local_ocr_and_stages_searchable_output(self) -> None:
        """Catches returning an OCR result without making a searchable ledger-local artifact."""
        def copy_searchable_pdf(source: Path, staged: Path, executable: str) -> Path:
            self.assertEqual("/usr/bin/ocrmypdf", executable)
            self.assertEqual(FIXTURES / "scanned-statement.pdf", source)
            shutil.copy2(FIXTURES / "text-statement.pdf", staged)
            return staged

        result = extract_pdf_pages(
            FIXTURES / "scanned-statement.pdf", self.work,
            PdfCapabilities(pdfplumber=True, ocrmypdf="/usr/bin/ocrmypdf"),
            ocr_runner=copy_searchable_pdf,
            pdf_reader=_PdfReader,
        )
        self.assertEqual("local_ocr", result.method)
        self.assertIsNotNone(result.staged_pdf)
        self.assertTrue(result.staged_pdf.is_file())
        self.assertTrue(result.staged_pdf.is_relative_to(self.work / "pdf-ocr"))
        self.assertIn("OPENAI", result.pages[0].text)
        self.assertEqual((), result.issues)
        self.assertEqual(b"%PDF", (FIXTURES / "scanned-statement.pdf").read_bytes()[:4])

    def test_missing_ocr_is_blocking(self) -> None:
        """Catches silently accepting a scanned page when no local OCR executable exists."""
        result = extract_pdf_pages(
            FIXTURES / "scanned-statement.pdf", self.work,
            PdfCapabilities(pdfplumber=True, ocrmypdf=None),
            pdf_reader=_PdfReader,
        )
        self.assertTrue(result.issues)
        self.assertEqual("LOCAL_OCR_UNAVAILABLE", result.issues[0].code)
        self.assertTrue(result.issues[0].blocking)
        self.assertNotIn("OPENAI", result.issues[0].message)

    def test_blank_table_cells_still_require_local_ocr(self) -> None:
        """Catches treating an all-blank extracted table as evidence that a page is readable."""
        result = extract_pdf_pages(
            FIXTURES / "scanned-statement.pdf", self.work,
            PdfCapabilities(pdfplumber=True, ocrmypdf=None), pdf_reader=_BlankTableReader,
        )
        self.assertTrue(result.issues)
        self.assertEqual("LOCAL_OCR_UNAVAILABLE", result.issues[0].code)

    def test_unmappable_pdf_header_is_blocking(self) -> None:
        """Catches guessing at table column names instead of requiring confirmed exact headers."""
        extraction = PdfExtraction(
            pages=(PdfPage(1, "Synthetic", ((
                ("Date", "Merchant", "Debit", "Credit", "Balance", "Reference"),
                ("2026-01-05", "OPENAI", "20.00", "", "980.00", "A1"),
            ),), "high"),),
            method="local_pdf_text", issues=(),
        )
        result = map_pdf_tables(extraction, MAPPING, ACCOUNT, source_file="text-statement.pdf")
        self.assertEqual("PDF_TABLE_UNMAPPABLE", result.issues[0].code)
        self.assertEqual((), result.transactions)

    def test_pdf_table_requires_confirmed_account_context(self) -> None:
        """Catches PDF mapping creating canonical rows for an unconfirmed account identity."""
        extraction = PdfExtraction(
            pages=(PdfPage(1, "Synthetic", ((
                ("Date", "Description", "Debit", "Credit", "Balance", "Reference"),
                ("2026-01-05", "OPENAI", "20.00", "", "980.00", "A1"),
            ),), "high"),),
            method="local_pdf_text", issues=(),
        )
        result = map_pdf_tables(
            extraction, MAPPING, AccountContext("checking-001", "Synthetic Bank", "1001", "CAD"),
            source_file="text-statement.pdf",
        )
        self.assertTrue(result.issues)
        self.assertEqual("ACCOUNT_UNCONFIRMED", result.issues[0].code)
        self.assertEqual((), result.transactions)

    def test_reliable_pdf_table_maps_to_canonical_csv_row(self) -> None:
        """Catches losing canonical debit direction or page/row provenance during PDF mapping."""
        extraction = PdfExtraction(
            pages=(PdfPage(1, "Synthetic statement", ((
                ("Date", "Description", "Debit", "Credit", "Balance", "Reference"),
                ("2026-01-05", "OPENAI", "20.00", "", "980.00", "A1"),
            ),), "high"),),
            method="local_pdf_text", issues=(),
        )
        result = map_pdf_tables(extraction, MAPPING, ACCOUNT, source_file="text-statement.pdf")
        self.assertEqual("20.00", result.transactions[0]["outflow"])
        self.assertEqual("0", result.transactions[0]["inflow"])
        self.assertEqual("page:1/row:2", result.transactions[0]["source_page_or_row"])
        self.assertEqual("local_pdf_text", result.transactions[0]["extraction_method"])

    def test_pdf_command_reports_missing_local_library_without_statement_text(self) -> None:
        """Catches a public PDF command bypassing the local capability block or printing statement data."""
        ledger = self.work / "ledger"
        initialize_ledger(ledger, "synthetic", "Synthetic", "CAD")
        (ledger / "inputs" / "statement.pdf").write_bytes((FIXTURES / "text-statement.pdf").read_bytes())
        (ledger / "work" / "mapping.json").write_text(json.dumps({
            "transaction_date": "Date", "description": "Description", "debit": "Debit",
            "credit": "Credit", "balance": "Balance", "reference": "Reference",
        }), encoding="utf-8")
        (ledger / "work" / "account.json").write_text(json.dumps({
            "account_id": "checking-001", "institution": "Synthetic Bank", "masked_label": "***1001", "currency": "CAD",
        }), encoding="utf-8")
        completed = subprocess.run([
            sys.executable, str(SKILL_ROOT / "scripts" / "import_statements.py"), "pdf", str(ledger), "inputs/statement.pdf",
            "--mapping", "work/mapping.json", "--account", "work/account.json",
        ], check=False, capture_output=True, text=True)
        self.assertTrue(completed.stdout, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(2, completed.returncode)
        self.assertEqual(["PDF_LIBRARY_UNAVAILABLE"], payload["issues"])
        self.assertNotIn("OPENAI", completed.stdout)


if __name__ == "__main__":
    unittest.main()
