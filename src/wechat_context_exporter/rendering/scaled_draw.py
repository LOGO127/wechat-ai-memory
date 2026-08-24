from __future__ import annotations

from typing import Any

from PIL import ImageDraw


class ScaledDraw:
    """Expose logical 150-DPI coordinates while drawing on a denser canvas."""

    def __init__(self, draw: ImageDraw.ImageDraw, scale: float) -> None:
        self._draw = draw
        self.scale = scale

    def text(self, xy, text, **kwargs) -> None:
        self._draw.text(self._point(xy), text, **kwargs)

    def textlength(self, text, **kwargs) -> float:
        return self._draw.textlength(text, **kwargs) / self.scale

    def textbbox(self, xy, text, **kwargs):
        box = self._draw.textbbox(self._point(xy), text, **kwargs)
        return tuple(value / self.scale for value in box)

    def rectangle(self, xy, **kwargs) -> None:
        self._draw.rectangle(self._box(xy), **self._scaled_width(kwargs))

    def rounded_rectangle(self, xy, radius=0, **kwargs) -> None:
        self._draw.rounded_rectangle(
            self._box(xy),
            radius=max(0, round(radius * self.scale)),
            **self._scaled_width(kwargs),
        )

    def line(self, xy, **kwargs) -> None:
        self._draw.line(self._box(xy), **self._scaled_width(kwargs))

    def _point(self, xy) -> tuple[int, int]:
        return round(xy[0] * self.scale), round(xy[1] * self.scale)

    def _box(self, xy) -> tuple[int, ...]:
        return tuple(round(value * self.scale) for value in xy)

    def _scaled_width(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        scaled = dict(kwargs)
        if "width" in scaled:
            scaled["width"] = max(1, round(scaled["width"] * self.scale))
        return scaled
