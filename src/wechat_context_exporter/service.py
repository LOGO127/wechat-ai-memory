from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import Conversation, Message, MessageType
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
    query: str | None = None


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
        self._validate_options(options)
        conversation = self._find_conversation(source, options.conversation_id)
        messages = source.get_messages(options.conversation_id, options.start, options.end)
        messages = self._filter_messages(messages, options.query)
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
            companion_messages = self._materialize_attachments(messages, options)
            markdown_path = (
                export_markdown(
                    conversation,
                    self._relative_attachment_paths(companion_messages, options.markdown_path),
                    options.markdown_path,
                )
                if options.markdown_path
                else None
            )
            json_path = (
                export_json(
                    conversation,
                    self._relative_attachment_paths(companion_messages, options.json_path),
                    options.json_path,
                )
                if options.json_path
                else None
            )

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
    def _validate_options(options: ExportOptions) -> None:
        if options.start is not None and options.end is not None and options.start > options.end:
            raise ValueError("Start date/time must not be after end date/time")

        destinations = [options.output_pdf, options.markdown_path, options.json_path]
        resolved = [path.expanduser().resolve() for path in destinations if path is not None]
        if len(resolved) != len(set(resolved)):
            raise ValueError("PDF, Markdown, and JSON output paths must be different")
        if options.pages_dir is not None and options.pages_dir.expanduser().resolve() in resolved:
            raise ValueError("Rendered pages directory must be different from output file paths")

    @staticmethod
    def _filter_messages(messages: list[Message], query: str | None) -> list[Message]:
        normalized = (query or "").strip().casefold()
        if not normalized:
            return messages
        return [
            message
            for message in messages
            if normalized in message.sender.casefold()
            or normalized in message.content.casefold()
            or normalized in message.type.value.casefold()
        ]

    @staticmethod
    def _materialize_attachments(messages: list[Message], options: ExportOptions) -> list[Message]:
        if options.markdown_path is None and options.json_path is None:
            return messages

        assets_dir = options.output_pdf.expanduser().resolve().with_name(f"{options.output_pdf.stem}_assets")
        copied: dict[Path, Path] = {}
        materialized: list[Message] = []
        for index, message in enumerate(messages, start=1):
            if message.type not in {MessageType.IMAGE, MessageType.FILE}:
                materialized.append(message)
                continue
            source = Path(message.content).expanduser().resolve()
            if not source.is_file():
                materialized.append(message)
                continue
            target = copied.get(source)
            if target is None:
                assets_dir.mkdir(parents=True, exist_ok=True)
                safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", message.id).strip("._")[:80] or "attachment"
                suffix = source.suffix if 1 < len(source.suffix) <= 10 else ".bin"
                target = assets_dir / f"{index:04d}_{safe_id}{suffix}"
                if source != target:
                    shutil.copy2(source, target)
                copied[source] = target
            materialized.append(replace(message, content=str(target)))
        return materialized

    @staticmethod
    def _relative_attachment_paths(messages: list[Message], output_path: Path) -> list[Message]:
        output_dir = output_path.expanduser().resolve().parent
        relative: list[Message] = []
        for message in messages:
            if message.type not in {MessageType.IMAGE, MessageType.FILE}:
                relative.append(message)
                continue
            content = Path(message.content)
            if not content.is_absolute():
                relative.append(message)
                continue
            try:
                portable = Path(os.path.relpath(content, output_dir)).as_posix()
            except ValueError:
                portable = content.as_posix()
            relative.append(replace(message, content=portable))
        return relative

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
