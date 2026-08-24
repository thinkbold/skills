"""Build deterministic synthetic PDF fixtures for local extraction tests."""

from io import BytesIO
from pathlib import Path
import sys

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

LINES = (
    "Synthetic Bank ***1001 CAD",
    "Date Description Debit Credit Balance Reference",
    "2026-01-05 OPENAI *CHATGPT SUBSCRIPTION 9F3A2 20.00 980.00 A1",
)


def build_text_pdf(path: Path) -> None:
    canvas = Canvas(str(path), pagesize=(612, 792), invariant=1)
    for index, line in enumerate(LINES):
        canvas.drawString(54, 738 - index * 24, line)
    canvas.save()


def build_scanned_pdf(path: Path) -> None:
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


def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    build_text_pdf(output_dir / "text-statement.pdf")
    build_scanned_pdf(output_dir / "scanned-statement.pdf")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
