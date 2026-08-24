from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont


@dataclass(slots=True)
class FontBook:
    regular_path: Path
    bold_path: Path

    @classmethod
    def discover(cls) -> "FontBook":
        candidates = _font_candidates()
        regular = next((path for path in candidates["regular"] if path.exists()), None)
        bold = next((path for path in candidates["bold"] if path.exists()), None)
        if regular is None:
            raise RuntimeError(
                "No usable TrueType font found. Install Microsoft YaHei, Noto Sans CJK, or DejaVu Sans."
            )
        return cls(regular_path=regular, bold_path=bold or regular)

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.regular_path), size=size)

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.bold_path), size=size)


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
    }

