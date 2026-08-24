from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageConfig:
    width: int = 1240
    height: int = 1754
    margin_x: int = 72
    header_height: int = 122
    footer_height: int = 58
    dpi: int = 150

    @property
    def content_top(self) -> int:
        return self.header_height

    @property
    def content_bottom(self) -> int:
        return self.height - self.footer_height

    @property
    def content_height(self) -> int:
        return self.content_bottom - self.content_top


@dataclass(frozen=True, slots=True)
class RenderTheme:
    page: str = "#F7F8FA"
    surface: str = "#FFFFFF"
    ink: str = "#17202A"
    muted: str = "#68737D"
    divider: str = "#DCE1E5"
    incoming: str = "#FFFFFF"
    outgoing: str = "#DFF4E5"
    accent: str = "#167B55"
    image_border: str = "#C9D0D5"

