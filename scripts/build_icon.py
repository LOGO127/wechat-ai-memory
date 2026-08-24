from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "src" / "wechat_context_exporter" / "assets" / "app-icon.svg"
ICO_PATH = ROOT / "packaging" / "windows" / "app-icon.ico"
PNG_PATH = ROOT / "docs" / "images" / "app-icon.png"


def main() -> int:
    QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG icon: {SVG_PATH}")

    image = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, 512, 512))
    painter.end()

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(PNG_PATH), "PNG"):
        raise RuntimeError(f"Could not render icon: {PNG_PATH}")
    with Image.open(PNG_PATH) as source:
        source.save(
            ICO_PATH,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    print(f"Created {ICO_PATH} and {PNG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
