from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from ..models import Conversation, Message, MessageType
from .config import PageConfig, RenderTheme
from .fonts import FontBook, draw_text_with_fallback, text_length_with_fallback
from .scaled_draw import ScaledDraw


@dataclass(slots=True)
class RenderedChatPage:
    image: Image.Image
    message_ids: list[str]
    image_message_ids: list[str]


@dataclass(slots=True)
class _DateBlock:
    label: str
    height: int = 52


@dataclass(slots=True)
class _MessageBlock:
    message: Message
    lines: list[str]
    width: int
    height: int
    continuation: bool = False
    thumbnail: Image.Image | None = None


class ChatRenderer:
    def __init__(
        self,
        config: PageConfig | None = None,
        theme: RenderTheme | None = None,
        fonts: FontBook | None = None,
    ) -> None:
        self.config = config or PageConfig()
        self.theme = theme or RenderTheme()
        self.fonts = fonts or FontBook.discover()
        self.title_font = self.fonts.bold(self.config.pixels(34))
        self.title_emoji_font = self.fonts.emoji(self.config.pixels(34))
        self.header_meta_font = self.fonts.regular(self.config.pixels(18))
        self.sender_font = self.fonts.bold(self.config.pixels(20))
        self.sender_emoji_font = self.fonts.emoji(self.config.pixels(20))
        self.body_font = self.fonts.regular(self.config.pixels(25))
        self.body_emoji_font = self.fonts.emoji(self.config.pixels(25))
        self.small_font = self.fonts.regular(self.config.pixels(17))
        self.small_emoji_font = self.fonts.emoji(self.config.pixels(17))
        self.date_font = self.fonts.bold(self.config.pixels(17))
        self.empty_font = self.fonts.regular(self.config.pixels(26))

    def render(
        self,
        conversation: Conversation,
        messages: Iterable[Message],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[RenderedChatPage]:
        message_list = list(messages)
        blocks = self._build_blocks(message_list)
        pages = self._paginate(blocks)
        if not pages:
            pages = [[]]
        return [
            self._draw_page(conversation, page, index + 1, len(pages), start, end)
            for index, page in enumerate(pages)
        ]

    def _build_blocks(self, messages: list[Message]) -> list[_DateBlock | _MessageBlock]:
        scratch = Image.new("RGB", (8, 8))
        draw = ScaledDraw(ImageDraw.Draw(scratch), self.config.scale)
        blocks: list[_DateBlock | _MessageBlock] = []
        current_date = None
        max_text_width = 720
        line_height = 38
        max_lines = 30

        for message in messages:
            if current_date != message.timestamp.date():
                current_date = message.timestamp.date()
                blocks.append(_DateBlock(current_date.strftime("%Y-%m-%d")))

            if message.type is MessageType.IMAGE:
                thumbnail = self._load_thumbnail(message.image_path, max_text_width, 390)
                width = round(thumbnail.width / self.config.scale) if thumbnail else 580
                thumbnail_height = round(thumbnail.height / self.config.scale) if thumbnail else 220
                height = 30 + thumbnail_height + 44
                blocks.append(_MessageBlock(message, [], max(width + 30, 250), height, thumbnail=thumbnail))
                continue

            content = self._display_content(message)
            lines = _wrap_text(draw, content, self.body_font, self.body_emoji_font, max_text_width)
            chunks = [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)] or [[""]]
            for chunk_index, chunk in enumerate(chunks):
                line_width = max(
                    (
                        int(text_length_with_fallback(draw, line, self.body_font, self.body_emoji_font))
                        for line in chunk
                    ),
                    default=0,
                )
                width = min(max_text_width + 36, max(260, line_width + 36))
                height = 30 + len(chunk) * line_height + 30
                if message.reply_to and chunk_index == 0:
                    height += 38
                blocks.append(
                    _MessageBlock(
                        message=message,
                        lines=chunk,
                        width=width,
                        height=height,
                        continuation=chunk_index > 0,
                    )
                )
        return blocks

    def _paginate(self, blocks: list[_DateBlock | _MessageBlock]) -> list[list[_DateBlock | _MessageBlock]]:
        pages: list[list[_DateBlock | _MessageBlock]] = []
        current: list[_DateBlock | _MessageBlock] = []
        used = 0
        index = 0
        while index < len(blocks):
            block = blocks[index]
            required = block.height
            if isinstance(block, _DateBlock) and index + 1 < len(blocks):
                required += blocks[index + 1].height
            if current and used + required > self.config.content_height:
                pages.append(current)
                current = []
                used = 0
                continue
            if current and used + block.height > self.config.content_height:
                pages.append(current)
                current = []
                used = 0
                continue
            current.append(block)
            used += block.height
            index += 1
        if current:
            pages.append(current)
        return pages

    def _draw_page(
        self,
        conversation: Conversation,
        blocks: list[_DateBlock | _MessageBlock],
        page_number: int,
        page_count: int,
        start: datetime | None,
        end: datetime | None,
    ) -> RenderedChatPage:
        page = Image.new("RGB", self.config.pixel_size, self.theme.page)
        draw = ScaledDraw(ImageDraw.Draw(page), self.config.scale)
        self._draw_header(draw, conversation, start, end)
        y = self.config.content_top
        message_ids: list[str] = []
        image_ids: list[str] = []
        for block in blocks:
            if isinstance(block, _DateBlock):
                self._draw_date(draw, block, y)
            else:
                self._draw_message(draw, page, block, y)
                if block.message.id not in message_ids:
                    message_ids.append(block.message.id)
                if block.message.type is MessageType.IMAGE and block.message.id not in image_ids:
                    image_ids.append(block.message.id)
            y += block.height

        if not blocks:
            empty = "No messages in the selected time range"
            box = draw.textbbox((0, 0), empty, font=self.empty_font)
            draw.text(
                ((self.config.width - (box[2] - box[0])) / 2, self.config.height / 2),
                empty,
                font=self.empty_font,
                fill=self.theme.muted,
            )
        self._draw_footer(draw, page_number, page_count)
        return RenderedChatPage(page, message_ids, image_ids)

    def _draw_header(
        self,
        draw: ImageDraw.ImageDraw,
        conversation: Conversation,
        start: datetime | None,
        end: datetime | None,
    ) -> None:
        draw.rectangle((0, 0, self.config.width, self.config.header_height), fill=self.theme.surface)
        draw_text_with_fallback(
            draw,
            (self.config.margin_x, 24),
            conversation.name,
            self.title_font,
            self.title_emoji_font,
            self.theme.ink,
        )
        kind = "Group chat" if conversation.kind.value == "group" else "Direct chat"
        date_range = _format_range(start, end)
        draw.text(
            (self.config.margin_x, 73),
            f"{kind}  |  {date_range}",
            font=self.header_meta_font,
            fill=self.theme.muted,
        )
        label = "WECHAT CONTEXT"
        label_width = draw.textlength(label, font=self.small_font)
        draw.text(
            (self.config.width - self.config.margin_x - label_width, 34),
            label,
            font=self.small_font,
            fill=self.theme.accent,
        )
        draw.line(
            (self.config.margin_x, self.config.header_height - 1, self.config.width - self.config.margin_x, self.config.header_height - 1),
            fill=self.theme.divider,
            width=2,
        )

    def _draw_date(self, draw: ImageDraw.ImageDraw, block: _DateBlock, y: int) -> None:
        width = draw.textlength(block.label, font=self.date_font)
        x = (self.config.width - width) / 2
        draw.rounded_rectangle((x - 18, y + 10, x + width + 18, y + 40), radius=8, fill="#E8ECEF")
        draw.text((x, y + 13), block.label, font=self.date_font, fill=self.theme.muted)

    def _draw_message(self, draw: ImageDraw.ImageDraw, page: Image.Image, block: _MessageBlock, y: int) -> None:
        message = block.message
        if message.type is MessageType.SYSTEM:
            self._draw_system_message(draw, block, y)
            return

        left = self.config.margin_x + 18
        if message.is_outgoing:
            left = self.config.width - self.config.margin_x - 18 - block.width
        sender = f"{message.sender} (continued)" if block.continuation else message.sender
        time_text = message.timestamp.strftime("%H:%M")
        draw_text_with_fallback(
            draw,
            (left, y + 3),
            sender,
            self.sender_font,
            self.sender_emoji_font,
            self.theme.ink,
        )
        time_width = draw.textlength(time_text, font=self.small_font)
        draw.text((left + block.width - time_width, y + 6), time_text, font=self.small_font, fill=self.theme.muted)

        bubble_top = y + 30
        bubble_bottom = y + block.height - 14
        bubble = self.theme.outgoing if message.is_outgoing else self.theme.incoming
        draw.rounded_rectangle((left, bubble_top, left + block.width, bubble_bottom), radius=12, fill=bubble)

        if message.type is MessageType.IMAGE:
            if block.thumbnail:
                thumbnail_width = round(block.thumbnail.width / self.config.scale)
                thumbnail_height = round(block.thumbnail.height / self.config.scale)
                image_x = left + (block.width - thumbnail_width) // 2
                image_y = bubble_top + 15
                page.paste(
                    block.thumbnail,
                    (self.config.pixels(image_x), self.config.pixels(image_y)),
                )
                draw.rounded_rectangle(
                    (image_x, image_y, image_x + thumbnail_width, image_y + thumbnail_height),
                    radius=6,
                    outline=self.theme.image_border,
                    width=2,
                )
            else:
                self._draw_missing_image(draw, left + 15, bubble_top + 15, block.width - 30, bubble_bottom - bubble_top - 30)
            return

        text_y = bubble_top + 15
        if message.reply_to and not block.continuation:
            draw.rounded_rectangle(
                (left + 16, text_y, left + block.width - 16, text_y + 30),
                radius=5,
                fill="#EDF0F2",
            )
            draw_text_with_fallback(
                draw,
                (left + 27, text_y + 4),
                f"Reply to {message.reply_to}",
                self.small_font,
                self.small_emoji_font,
                self.theme.muted,
            )
            text_y += 38
        for line in block.lines:
            draw_text_with_fallback(
                draw,
                (left + 18, text_y),
                line,
                self.body_font,
                self.body_emoji_font,
                self.theme.ink,
            )
            text_y += 38

    def _draw_system_message(self, draw: ImageDraw.ImageDraw, block: _MessageBlock, y: int) -> None:
        width = min(
            self.config.width - self.config.margin_x * 2,
            max(
                (
                    text_length_with_fallback(draw, line, self.small_font, self.small_emoji_font)
                    for line in block.lines
                ),
                default=0,
            )
            + 36,
        )
        x = (self.config.width - width) / 2
        draw.rounded_rectangle((x, y + 10, x + width, y + block.height - 12), radius=8, fill="#E8ECEF")
        text_y = y + 23
        for line in block.lines:
            line_width = text_length_with_fallback(draw, line, self.small_font, self.small_emoji_font)
            draw_text_with_fallback(
                draw,
                ((self.config.width - line_width) / 2, text_y),
                line,
                self.small_font,
                self.small_emoji_font,
                self.theme.muted,
            )
            text_y += 30

    def _draw_missing_image(self, draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int) -> None:
        draw.rectangle((x, y, x + width, y + height), fill="#F0F2F3", outline=self.theme.image_border, width=2)
        label = "Image unavailable"
        label_width = draw.textlength(label, font=self.body_font)
        draw.text((x + (width - label_width) / 2, y + height / 2 - 14), label, font=self.body_font, fill=self.theme.muted)

    def _draw_footer(self, draw: ImageDraw.ImageDraw, page_number: int, page_count: int) -> None:
        y = self.config.height - self.config.footer_height
        draw.line((self.config.margin_x, y, self.config.width - self.config.margin_x, y), fill=self.theme.divider, width=2)
        draw.text((self.config.margin_x, y + 18), "Local export  |  Agent-readable context", font=self.small_font, fill=self.theme.muted)
        counter = f"Chat page {page_number} / {page_count}"
        counter_width = draw.textlength(counter, font=self.small_font)
        draw.text((self.config.width - self.config.margin_x - counter_width, y + 18), counter, font=self.small_font, fill=self.theme.muted)

    def _load_thumbnail(self, path: Path | None, max_width: int, max_height: int) -> Image.Image | None:
        if path is None:
            return None
        try:
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail(
                    (self.config.pixels(max_width), self.config.pixels(max_height)),
                    Image.Resampling.LANCZOS,
                )
                return image.copy()
        except (FileNotFoundError, OSError, UnidentifiedImageError):
            return None

    @staticmethod
    def _display_content(message: Message) -> str:
        if message.type is MessageType.FILE:
            return f"File attachment: {Path(message.content).name}"
        return message.content


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, emoji_font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        tokens = re.findall(r"[A-Za-z0-9_./:%+@#-]+\s*|.", paragraph)
        for token in tokens:
            candidate = current + token
            if current and text_length_with_fallback(draw, candidate, font, emoji_font) > max_width:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = candidate
            while text_length_with_fallback(draw, current, font, emoji_font) > max_width:
                split_at = len(current) - 1
                while split_at > 1 and text_length_with_fallback(
                    draw, current[:split_at], font, emoji_font
                ) > max_width:
                    split_at -= 1
                lines.append(current[:split_at].rstrip())
                current = current[split_at:].lstrip()
        lines.append(current.rstrip())
    return lines


def _format_range(start: datetime | None, end: datetime | None) -> str:
    if start and end:
        return f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
    if start:
        return f"From {start:%Y-%m-%d}"
    if end:
        return f"Through {end:%Y-%m-%d}"
    return "All available messages"
