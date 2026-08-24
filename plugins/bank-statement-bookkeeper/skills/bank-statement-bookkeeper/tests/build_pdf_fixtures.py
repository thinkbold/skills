"""Build deterministic synthetic PDF fixtures for local extraction tests."""

from pathlib import Path
import sys

LINES = (
    "Synthetic Bank ***1001 CAD",
    "Date Description Debit Credit Balance Reference",
    "2026-01-05 OPENAI *CHATGPT SUBSCRIPTION 9F3A2 20.00 980.00 A1",
)


def _reportlab_available() -> bool:
    try:
        import PIL  # noqa: F401
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def _build_text_with_reportlab(path: Path) -> None:
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path), pagesize=(612, 792), invariant=1)
    for index, line in enumerate(LINES):
        canvas.drawString(54, 738 - index * 24, line)
    canvas.save()


def _build_scanned_with_reportlab(path: Path) -> None:
    from io import BytesIO

    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    image = Image.new("RGB", (1224, 1584), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(LINES):
        draw.text((108, 108 + index * 48), line, fill="black")
    image_data = BytesIO()
    image.save(image_data, format="PNG")
    image_data.seek(0)
    canvas = Canvas(str(path), pagesize=(612, 792), invariant=1)
    canvas.drawImage(ImageReader(image_data), 0, 0, width=612, height=792)
    canvas.save()


def _write_pdf(path: Path, objects: list[bytes]) -> None:
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    startxref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(output)


def _build_text_without_dependencies(path: Path) -> None:
    escaped_lines = (line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in LINES)
    stream = b"BT /F1 12 Tf 54 738 Td " + b" 0 -24 Td ".join(
        f"({line}) Tj".encode("ascii") for line in escaped_lines
    ) + b" ET"
    _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def _build_scanned_without_dependencies(path: Path) -> None:
    image = b"\xff"
    stream = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n" + image + b"\nendstream",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ])


def build_text_pdf(path: Path) -> None:
    if _reportlab_available():
        _build_text_with_reportlab(path)
    else:
        _build_text_without_dependencies(path)


def build_scanned_pdf(path: Path) -> None:
    if _reportlab_available():
        _build_scanned_with_reportlab(path)
    else:
        _build_scanned_without_dependencies(path)


def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    build_text_pdf(output_dir / "text-statement.pdf")
    build_scanned_pdf(output_dir / "scanned-statement.pdf")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
