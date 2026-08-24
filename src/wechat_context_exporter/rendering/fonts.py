from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import ImageDraw, ImageFont


@dataclass(slots=True)
class FontBook:
    regular_path: Path
    bold_path: Path
    emoji_path: Path | None = None

    @classmethod
    def discover(cls) -> "FontBook":
        candidates = _font_candidates()
        regular = next((path for path in candidates["regular"] if path.exists()), None)
        bold = next((path for path in candidates["bold"] if path.exists()), None)
        emoji = next((path for path in candidates["emoji"] if path.exists()), None)
        if regular is None:
            raise RuntimeError(
                "No usable TrueType font found. Install Microsoft YaHei, Noto Sans CJK, or DejaVu Sans."
            )
        return cls(regular_path=regular, bold_path=bold or regular, emoji_path=emoji)

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)

    def emoji(self, size: int) -> ImageFont.FreeTypeFont | None:
        if self.emoji_path is None:
            return None
        return ImageFont.truetype(str(self.emoji_path), size=size)


def text_length_with_fallback(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    emoji_font: ImageFont.FreeTypeFont | None,
) -> float:
    return sum(draw.textlength(run, font=selected) for run, selected, _ in _font_runs(text, font, emoji_font))


def draw_text_with_fallback(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    emoji_font: ImageFont.FreeTypeFont | None,
    fill: str,
) -> float:
    x, y = position
    start = x
    for run, selected, is_emoji in _font_runs(text, font, emoji_font):
        if is_emoji:
            try:
                draw.text((x, y), run, font=selected, embedded_color=True, fill=fill)
            except (OSError, ValueError):
                draw.text((x, y), run, font=selected, fill=fill)
        else:
            draw.text((x, y), run, font=selected, fill=fill)
        x += draw.textlength(run, font=selected)
    return x - start


def _font_runs(
    text: str,
    font: ImageFont.FreeTypeFont,
    emoji_font: ImageFont.FreeTypeFont | None,
) -> Iterable[tuple[str, ImageFont.FreeTypeFont, bool]]:
    if not text:
        return
    if emoji_font is None:
        yield text, font, False
        return
    start = 0
    current_is_emoji = _is_emoji_character(text[0])
    for index, character in enumerate(text[1:], start=1):
        is_emoji = _is_emoji_character(character)
        if is_emoji != current_is_emoji:
            yield text[start:index], emoji_font if current_is_emoji else font, current_is_emoji
            start = index
            current_is_emoji = is_emoji
    yield text[start:], emoji_font if current_is_emoji else font, current_is_emoji


def _is_emoji_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2300 <= codepoint <= 0x23FF
        or 0x1F1E6 <= codepoint <= 0x1F1FF
        or codepoint in {0x200D, 0x20E3, 0xFE0E, 0xFE0F}
    )


def _font_candidates() -> dict[str, list[Path]]:
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    return {
        "regular": [
            windows / "msyh.ttc",
            windows / "msyh.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        ],
        "bold": [
            windows / "msyhbd.ttc",
            windows / "msyhbd.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        ],
        "emoji": [
            windows / "seguiemj.ttf",
            Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
            Path("/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf"),
            Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
        ],
    }
