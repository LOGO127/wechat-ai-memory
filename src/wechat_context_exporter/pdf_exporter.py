from __future__ import annotations

from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


class PdfExporter:
    def export(self, page_paths: Iterable[str | Path], output_path: str | Path, title: str) -> Path:
        paths = [Path(path) for path in page_paths]
        if not paths:
            raise ValueError("At least one rendered page is required")
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
        document.setTitle(title)
        document.setAuthor("WeChat AI Memory")
        document.setSubject("Local WeChat memory archive for AI agents")
        page_width, page_height = A4
        for path in paths:
            document.drawImage(
                ImageReader(str(path)),
                0,
                0,
                width=page_width,
                height=page_height,
                preserveAspectRatio=False,
                mask="auto",
            )
            document.showPage()
        document.save()
        return output
