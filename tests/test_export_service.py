from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from wechat_context_exporter.service import ExportOptions, ExportService
from wechat_context_exporter.sources import JsonChatSource


def test_end_to_end_export_with_image_and_companions(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (900, 500), "#2f855a").save(image_path)
    payload = {
        "version": 1,
        "conversations": [
            {
                "id": "c1",
                "name": "Export test",
                "messages": [
                    {"id": "m1", "sender": "A", "timestamp": "2026-08-21T10:00:00", "type": "text", "content": "Please inspect the image."},
                    {"id": "m2", "sender": "B", "timestamp": "2026-08-21T10:01:00", "type": "image", "content": "source.png"},
                    {"id": "m3", "sender": "A", "timestamp": "2026-08-21T10:02:00", "type": "text", "content": "The result is acceptable."},
                ],
            }
        ],
    }
    source_path = tmp_path / "chat.json"
    source_path.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "context.pdf"
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "page_0099_chat.png").write_bytes(b"stale")
    markdown = tmp_path / "context.md"
    normalized = tmp_path / "context.json"

    result = ExportService().export(
        JsonChatSource(source_path),
        ExportOptions(
            conversation_id="c1",
            output_pdf=output,
            include_image_pages=True,
            pages_dir=pages_dir,
            markdown_path=markdown,
            json_path=normalized,
        ),
    )

    assert result.message_count == 3
    assert result.chat_page_count == 1
    assert result.image_page_count == 1
    assert result.page_count == 2
    assert len(PdfReader(str(output)).pages) == 2
    assert len(list(pages_dir.glob("page_*.png"))) == 2
    assert not (pages_dir / "page_0099_chat.png").exists()
    assert "Please inspect the image" in markdown.read_text(encoding="utf-8")
    assert json.loads(normalized.read_text(encoding="utf-8"))["messages"][1]["type"] == "image"
