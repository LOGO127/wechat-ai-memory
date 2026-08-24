from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from ..models import Conversation, Message
from .config import PageConfig, RenderTheme
from .fonts import FontBook


class ImagePageRenderer:
    def __init__(
        self,
        config: PageConfig | None = None,
        theme: RenderTheme | None = None,
        fonts: FontBook | None = None,
    ) -> None:
        self.config = config or PageConfig()
        self.theme = theme or RenderTheme()
        self.fonts = fonts or FontBook.discover()
        self.title_font = self.fonts.bold(32)
        self.label_font = self.fonts.bold(17)
        self.value_font = self.fonts.regular(20)
        self.small_font = self.fonts.regular(17)
        self.placeholder_font = self.fonts.regular(26)

    def render(
        self,
        conversation: Conversation,
        message: Message,
        attachment_number: int,
        attachment_count: int,
    ) -> Image.Image:
        page = Image.new("RGB", (self.config.width, self.config.height), self.theme.page)
        draw = ImageDraw.Draw(page)
        draw.rectangle((0, 0, self.config.width, 184), fill=self.theme.surface)
        draw.text((self.config.margin_x, 24), "Image attachment", font=self.title_font, fill=self.theme.ink)
        marker = f"ATTACHMENT {attachment_number} / {attachment_count}"
        marker_width = draw.textlength(marker, font=self.small_font)
        draw.text(
            (self.config.width - self.config.margin_x - marker_width, 34),
            marker,
            font=self.small_font,
            fill=self.theme.accent,
        )
        self._metadata_row(draw, 82, "Source", conversation.name)
        self._metadata_row(draw, 117, "Sender", message.sender)
        self._metadata_row(draw, 152, "Time", message.timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        frame = (
            self.config.margin_x,
            218,
            self.config.width - self.config.margin_x,
            self.config.height - self.config.footer_height - 26,
        )
        draw.rectangle(frame, fill=self.theme.surface, outline=self.theme.image_border, width=2)
        self._place_image(page, draw, message, frame)

        footer_y = self.config.height - self.config.footer_height
        draw.line((self.config.margin_x, footer_y, self.config.width - self.config.margin_x, footer_y), fill=self.theme.divider, width=2)
        draw.text(
            (self.config.margin_x, footer_y + 18),
            "Original aspect ratio preserved  |  Local export",
            font=self.small_font,
            fill=self.theme.muted,
        )
        return page

    def _metadata_row(self, draw: ImageDraw.ImageDraw, y: int, label: str, value: str) -> None:
        draw.text((self.config.margin_x, y), label.upper(), font=self.label_font, fill=self.theme.muted)
        draw.text((self.config.margin_x + 112, y - 2), value, font=self.value_font, fill=self.theme.ink)

    def _place_image(self, page: Image.Image, draw: ImageDraw.ImageDraw, message: Message, frame: tuple[int, int, int, int]) -> None:
        inset = 28
        available_width = frame[2] - frame[0] - inset * 2
        available_height = frame[3] - frame[1] - inset * 2
        try:
            with Image.open(message.content) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
                x = frame[0] + (frame[2] - frame[0] - image.width) // 2
                y = frame[1] + (frame[3] - frame[1] - image.height) // 2
                page.paste(image, (x, y))
        except (FileNotFoundError, OSError, UnidentifiedImageError):
            label = "Original image is unavailable"
            width = draw.textlength(label, font=self.placeholder_font)
            draw.text(
                ((self.config.width - width) / 2, frame[1] + (frame[3] - frame[1]) / 2),
                label,
                font=self.placeholder_font,
                fill=self.theme.muted,
            )

