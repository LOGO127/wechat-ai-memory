from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
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
    document = PdfReader(str(output))
    assert len(document.pages) == 2
    assert document.pages[0].images[0].image.size == (2480, 3508)
    assert len(list(pages_dir.glob("page_*.png"))) == 2
    with Image.open(pages_dir / "page_0001_chat.png") as rendered_page:
        assert rendered_page.size == (2480, 3508)
    assert not (pages_dir / "page_0099_chat.png").exists()
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "Please inspect the image" in markdown_text
    assert "![Image attachment](context_assets/0002_m2.png)" in markdown_text
    normalized_payload = json.loads(normalized.read_text(encoding="utf-8"))
    assert normalized_payload["conversations"][0]["messages"][1]["type"] == "image"
    assert normalized_payload["conversations"][0]["messages"][1]["content"] == "context_assets/0002_m2.png"
    roundtrip = JsonChatSource(normalized)
    assert [message.id for message in roundtrip.get_messages("c1")] == ["m1", "m2", "m3"]
    image_path.unlink()
    assert roundtrip.get_messages("c1")[1].image_path.is_file()


def test_export_applies_query_to_pdf_and_companions(tmp_path):
    payload = {
        "version": 1,
        "conversations": [
            {
                "id": "c1",
                "name": "Search test",
                "messages": [
                    {"id": "m1", "sender": "A", "timestamp": "2026-08-21T10:00:00", "content": "keep this result"},
                    {"id": "m2", "sender": "B", "timestamp": "2026-08-21T10:01:00", "content": "ignore this"},
                ],
            }
        ],
    }
    source_path = tmp_path / "chat.json"
    source_path.write_text(json.dumps(payload), encoding="utf-8")
    normalized = tmp_path / "filtered.json"

    result = ExportService().export(
        JsonChatSource(source_path),
        ExportOptions(
            conversation_id="c1",
            output_pdf=tmp_path / "filtered.pdf",
            json_path=normalized,
            query="RESULT",
        ),
    )

    assert result.message_count == 1
    assert [message.id for message in JsonChatSource(normalized).get_messages("c1")] == ["m1"]


@pytest.mark.parametrize(
    "options",
    [
        ExportOptions(
            conversation_id="c1",
            output_pdf=Path("out.pdf"),
            start=datetime(2026, 8, 22),
            end=datetime(2026, 8, 21),
        ),
        ExportOptions(
            conversation_id="c1",
            output_pdf=Path("same-path"),
            markdown_path=Path("same-path"),
        ),
        ExportOptions(
            conversation_id="c1",
            output_pdf=Path("same-path"),
            pages_dir=Path("same-path"),
        ),
    ],
)
def test_export_rejects_invalid_ranges_and_colliding_outputs(tmp_path, options):
    payload = {
        "version": 1,
        "conversations": [{"id": "c1", "name": "Test", "messages": []}],
    }
    source_path = tmp_path / "chat.json"
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        ExportService().export(JsonChatSource(source_path), options)
