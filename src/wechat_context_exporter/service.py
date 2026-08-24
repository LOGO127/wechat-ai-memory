from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import Conversation, Message
from .pdf_exporter import PdfExporter
from .rendering import ChatRenderer, ImagePageRenderer
from .sources import ChatSource
from .text_exporters import export_json, export_markdown

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class ExportOptions:
    conversation_id: str
    output_pdf: Path
    start: datetime | None = None
    end: datetime | None = None
    include_image_pages: bool = True
    pages_dir: Path | None = None
    markdown_path: Path | None = None
    json_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ExportResult:
    pdf_path: Path
    page_count: int
    chat_page_count: int
    image_page_count: int
    message_count: int
    pages_dir: Path | None = None
    markdown_path: Path | None = None
    json_path: Path | None = None


class ExportService:
    def __init__(
        self,
        chat_renderer: ChatRenderer | None = None,
        image_renderer: ImagePageRenderer | None = None,
        pdf_exporter: PdfExporter | None = None,
    ) -> None:
        self.chat_renderer = chat_renderer or ChatRenderer()
        self.image_renderer = image_renderer or ImagePageRenderer(
            config=self.chat_renderer.config,
            theme=self.chat_renderer.theme,
            fonts=self.chat_renderer.fonts,
        )
        self.pdf_exporter = pdf_exporter or PdfExporter()

    def export(
        self,
        source: ChatSource,
        options: ExportOptions,
        progress: ProgressCallback | None = None,
    ) -> ExportResult:
        conversation = self._find_conversation(source, options.conversation_id)
        messages = source.get_messages(options.conversation_id, options.start, options.end)
        self._progress(progress, 1, 5, "Rendering chat pages")
        chat_pages = self.chat_renderer.render(conversation, messages, options.start, options.end)

        with tempfile.TemporaryDirectory(prefix="wce-") as temp_name:
            temp_dir = Path(temp_name)
            render_dir = temp_dir
            message_by_id = {message.id: message for message in messages}
            image_messages = [message for message in messages if message.image_path is not None]
            image_position = {message.id: index + 1 for index, message in enumerate(image_messages)}
            page_paths: list[Path] = []
            chat_count = 0
            image_count = 0

            for chat_page in chat_pages:
                chat_count += 1
                chat_path = render_dir / f"page_{len(page_paths) + 1:04d}_chat.png"
                chat_page.image.save(chat_path, format="PNG", optimize=True)
                page_paths.append(chat_path)
                if options.include_image_pages:
                    for message_id in chat_page.image_message_ids:
                        message = message_by_id[message_id]
                        attachment_page = self.image_renderer.render(
                            conversation,
                            message,
                            image_position[message_id],
                            len(image_messages),
                        )
                        image_count += 1
                        image_path = render_dir / f"page_{len(page_paths) + 1:04d}_image.png"
                        attachment_page.save(image_path, format="PNG", optimize=True)
                        page_paths.append(image_path)

            self._progress(progress, 2, 5, "Building PDF")
            pdf_path = self.pdf_exporter.export(page_paths, options.output_pdf, conversation.name)
            self._progress(progress, 3, 5, "Writing companion files")
            markdown_path = export_markdown(conversation, messages, options.markdown_path) if options.markdown_path else None
            json_path = export_json(conversation, messages, options.json_path) if options.json_path else None

            persistent_pages_dir = None
            if options.pages_dir is not None:
                persistent_pages_dir = options.pages_dir.expanduser().resolve()
                persistent_pages_dir.mkdir(parents=True, exist_ok=True)
                for stale_page in persistent_pages_dir.glob("page_[0-9][0-9][0-9][0-9]_*.png"):
                    stale_page.unlink()
                for page_path in page_paths:
                    (persistent_pages_dir / page_path.name).write_bytes(page_path.read_bytes())

            self._progress(progress, 5, 5, "Export complete")
            return ExportResult(
                pdf_path=pdf_path,
                page_count=len(page_paths),
                chat_page_count=chat_count,
                image_page_count=image_count,
                message_count=len(messages),
                pages_dir=persistent_pages_dir,
                markdown_path=markdown_path,
                json_path=json_path,
            )

    @staticmethod
    def _find_conversation(source: ChatSource, conversation_id: str) -> Conversation:
        for conversation in source.list_conversations():
            if conversation.id == conversation_id:
                return conversation
        raise ValueError(f"Conversation not found: {conversation_id}")

    @staticmethod
    def _progress(callback: ProgressCallback | None, current: int, total: int, label: str) -> None:
        if callback:
            callback(current, total, label)
