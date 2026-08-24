from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QWidget

from wechat_context_exporter.sources import JsonChatSource
from wechat_context_exporter.ui import main_window

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "readme-tutorial"
MEDIA = ROOT / "docs" / "media"
DEMO_JSON = ROOT / "examples" / "demo_chat.json"
MP4_PATH = MEDIA / "wechat-ai-memory-tutorial.mp4"
GIF_PATH = MEDIA / "wechat-ai-memory-tutorial.gif"
FPS = 12
CANVAS_SIZE = (1280, 720)


@dataclass(frozen=True)
class Shot:
    image: Image.Image
    focus: tuple[int, int, int, int] | None
    cursor: tuple[int, int] | None


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["msyhbd.ttc", "simhei.ttf"] if bold else ["msyh.ttc", "simhei.ttf"]
    candidates = [Path("C:/Windows/Fonts") / name for name in names]
    candidates.extend(
        Path("/usr/share/fonts/truetype/dejavu") / name
        for name in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"])
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def wait_until(app: QApplication, predicate: Callable[[], bool], timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out while preparing the tutorial capture")
        app.processEvents()
        time.sleep(0.01)


def widget_rect(window: QWidget, *widgets: QWidget, padding: int = 8) -> tuple[int, int, int, int]:
    rectangles = []
    for widget in widgets:
        point = widget.mapTo(window, QPoint(0, 0))
        rectangles.append((point.x(), point.y(), point.x() + widget.width(), point.y() + widget.height()))
    return (
        min(rect[0] for rect in rectangles) - padding,
        min(rect[1] for rect in rectangles) - padding,
        max(rect[2] for rect in rectangles) + padding,
        max(rect[3] for rect in rectangles) + padding,
    )


def center(rectangle: tuple[int, int, int, int]) -> tuple[int, int]:
    return ((rectangle[0] + rectangle[2]) // 2, (rectangle[1] + rectangle[3]) // 2)


def grab(window: main_window.MainWindow, name: str) -> Image.Image:
    QApplication.processEvents()
    path = WORK / f"{name}.png"
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Could not capture {path}")
    with Image.open(path) as captured:
        return captured.convert("RGB").resize(CANVAS_SIZE, Image.Resampling.LANCZOS)


def capture_application() -> tuple[dict[str, Shot], list[Image.Image]]:
    WORK.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(WORK / "tutorial.ini"), QSettings.Format.IniFormat)
    settings.clear()
    main_window.QSettings = lambda *_args: settings
    main_window.discover_wechat4_accounts = list
    main_window.QMessageBox.information = lambda *_args: None
    main_window.QMessageBox.critical = lambda *_args: None

    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow()
    window.resize(*CANVAS_SIZE)
    window.show()
    app.processEvents()

    window.source_edit.setText("微信 4.x 数据目录（自动检测）")
    connect_focus = widget_rect(window, window.source_edit, window.load_button)
    shots: dict[str, Shot] = {
        "connect": Shot(grab(window, "01-connect"), connect_focus, center(widget_rect(window, window.load_button))),
    }

    source = JsonChatSource(DEMO_JSON)
    window._source_loaded(source)
    wait_until(app, lambda: window._message_worker is not None and not window._message_worker.isRunning())
    app.processEvents()
    window.source_edit.setText("微信 4.x 数据目录（已连接）")
    window.image_key_button.setEnabled(True)
    window.output_edit.setText("outputs/ECO_project_memory.pdf")
    range_focus = widget_rect(window, window.conversation_combo, window.start_date, window.end_date)
    shots["range"] = Shot(grab(window, "02-range"), range_focus, center(range_focus))

    search_focus = widget_rect(window, window.search_edit)
    search_images: list[Image.Image] = []
    for index, query in enumerate(["", "随", "随机", "随机种", "随机种子"]):
        window.search_edit.setText(query)
        app.processEvents()
        search_images.append(grab(window, f"03-search-{index}"))
    shots["search"] = Shot(search_images[-1], search_focus, center(search_focus))

    window.search_edit.clear()
    window.companions_check.setChecked(True)
    export_focus = widget_rect(window, window.output_edit, window.companions_check, window.export_button)
    shots["export"] = Shot(
        grab(window, "04-export"),
        export_focus,
        center(widget_rect(window, window.export_button)),
    )

    progress_images: list[Image.Image] = []
    window._set_busy(True)
    for index, label in enumerate(["筛选消息...", "生成 PDF...", "写入 Markdown...", "写入 JSON..."]):
        window._operation_progress(index + 1, 4, label)
        progress_images.append(grab(window, f"05-progress-{index}"))
    window._set_busy(False)

    output = WORK / "ECO_project_memory.pdf"
    for path in [output, output.with_suffix(".md"), output.with_suffix(".json")]:
        path.unlink(missing_ok=True)
    window.output_edit.setText(str(output))
    window._start_export()
    wait_until(app, lambda: window._last_result is not None, timeout=15.0)
    app.processEvents()
    window.output_edit.setText("outputs/ECO_project_memory.pdf")
    final_focus = widget_rect(window, window.open_folder_button, window.export_button)
    shots["final"] = Shot(grab(window, "06-final"), final_focus, center(final_focus))
    window.close()
    return shots, search_images + progress_images


def ease(value: float) -> float:
    return value * value * (3 - 2 * value)


def draw_cursor(draw: ImageDraw.ImageDraw, position: tuple[int, int], pulse: float = 0.0) -> None:
    x, y = position
    if pulse > 0:
        radius = int(18 + pulse * 20)
        alpha = int(180 * (1 - pulse))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(8, 184, 108, alpha), width=4)
    shadow = [(x + 3, y + 3), (x + 3, y + 29), (x + 10, y + 23), (x + 17, y + 37), (x + 24, y + 33), (x + 17, y + 20), (x + 29, y + 19)]
    arrow = [(x, y), (x, y + 28), (x + 8, y + 22), (x + 15, y + 36), (x + 22, y + 32), (x + 15, y + 19), (x + 28, y + 18)]
    draw.polygon(shadow, fill=(0, 0, 0, 90))
    draw.polygon(arrow, fill=(255, 255, 255, 255), outline=(23, 35, 31, 255))


def render_stage(
    shot: Shot,
    step: str,
    caption: str,
    progress: float,
    cursor_from: tuple[int, int] | None,
    click: bool = True,
) -> Image.Image:
    frame = shot.image.convert("RGBA")
    overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if shot.focus:
        pulse = (1 + __import__("math").sin(progress * __import__("math").pi * 2)) / 2
        x0, y0, x1, y1 = shot.focus
        draw.rounded_rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), radius=10, outline=(8, 184, 108, 55), width=8)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=8, outline=(8, 184, 108, int(190 + 65 * pulse)), width=3)

    label_font = font(15, True)
    caption_font = font(22, True)
    label_box = draw.textbbox((0, 0), step, font=label_font)
    caption_box = draw.textbbox((0, 0), caption, font=caption_font)
    width = 22 + (label_box[2] - label_box[0]) + 18 + (caption_box[2] - caption_box[0]) + 26
    x0 = (CANVAS_SIZE[0] - width) // 2
    draw.rounded_rectangle((x0, 14, x0 + width, 62), radius=8, fill=(23, 35, 31, 238))
    draw.rounded_rectangle((x0 + 10, 24, x0 + 10 + label_box[2] - label_box[0] + 12, 52), radius=5, fill=(8, 184, 108, 255))
    draw.text((x0 + 16, 28), step, font=label_font, fill="white")
    draw.text((x0 + 40 + label_box[2] - label_box[0], 24), caption, font=caption_font, fill="white")

    if shot.cursor:
        start = cursor_from or shot.cursor
        amount = ease(min(progress * 1.35, 1.0))
        position = (
            int(start[0] + (shot.cursor[0] - start[0]) * amount),
            int(start[1] + (shot.cursor[1] - start[1]) * amount),
        )
        pulse = max(0.0, min(1.0, (progress - 0.72) / 0.28)) if click else 0.0
        draw_cursor(draw, position, pulse)
    return Image.alpha_composite(frame, overlay).convert("RGB")


def intro_frames(base: Image.Image, count: int) -> list[Image.Image]:
    background = ImageEnhance.Brightness(base).enhance(0.42).filter(ImageFilter.GaussianBlur(1.4)).convert("RGBA")
    logo = Image.open(ROOT / "docs" / "images" / "app-icon.png").convert("RGBA").resize((88, 88), Image.Resampling.LANCZOS)
    frames = []
    for index in range(count):
        frame = background.copy()
        overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        overlay.alpha_composite(logo, ((CANVAS_SIZE[0] - 88) // 2, 198))
        draw = ImageDraw.Draw(overlay)
        title = "把微信聊天整理成 AI 记忆档案"
        subtitle = "本地读取  ·  精准筛选  ·  一键归档"
        title_font = font(42, True)
        subtitle_font = font(22)
        title_box = draw.textbbox((0, 0), title, font=title_font)
        subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        draw.text(((CANVAS_SIZE[0] - title_box[2]) // 2, 315), title, font=title_font, fill="white")
        draw.text(((CANVAS_SIZE[0] - subtitle_box[2]) // 2, 382), subtitle, font=subtitle_font, fill=(221, 238, 229, 255))
        line_width = int(420 * min(1.0, (index + 1) / max(1, count - 2)))
        draw.rounded_rectangle((430, 445, 850, 451), radius=3, fill=(255, 255, 255, 50))
        draw.rounded_rectangle((430, 445, 430 + line_width, 451), radius=3, fill=(8, 184, 108, 255))
        frames.append(Image.alpha_composite(frame, overlay).convert("RGB"))
    return frames


def crossfade(left: Image.Image, right: Image.Image, count: int = 4) -> list[Image.Image]:
    return [Image.blend(left, right, (index + 1) / (count + 1)) for index in range(count)]


def build_timeline(shots: dict[str, Shot], dynamic: list[Image.Image]) -> list[Image.Image]:
    frames = intro_frames(shots["range"].image, 20)
    previous_cursor = (CANVAS_SIZE[0] // 2, CANVAS_SIZE[1] - 54)

    stages = [
        ("01", "连接已登录的 Windows 微信", shots["connect"], 22),
        ("02", "选择会话和需要保留的日期", shots["range"], 22),
    ]
    for step, caption, shot, count in stages:
        rendered = [render_stage(shot, step, caption, index / (count - 1), previous_cursor) for index in range(count)]
        frames.extend(crossfade(frames[-1], rendered[0]))
        frames.extend(rendered)
        previous_cursor = shot.cursor or previous_cursor

    search_images = dynamic[:5]
    search_shot = shots["search"]
    search_frames = []
    for index in range(28):
        variant = search_images[min(4, max(0, (index - 8) // 4))]
        active = Shot(variant, search_shot.focus, search_shot.cursor)
        search_frames.append(render_stage(active, "03", "输入关键词，预览会立即筛选", index / 27, previous_cursor, click=False))
    frames.extend(crossfade(frames[-1], search_frames[0]))
    frames.extend(search_frames)
    previous_cursor = search_shot.cursor or previous_cursor

    export_shot = shots["export"]
    export_frames = [
        render_stage(export_shot, "04", "生成 PDF · Markdown · JSON", index / 23, previous_cursor)
        for index in range(24)
    ]
    frames.extend(crossfade(frames[-1], export_frames[0]))
    frames.extend(export_frames)

    progress_images = dynamic[5:]
    for index in range(18):
        active = Shot(progress_images[min(3, index // 5)], export_shot.focus, export_shot.cursor)
        frames.append(render_stage(active, "04", "档案正在本机生成", index / 17, export_shot.cursor, click=False))

    final_shot = shots["final"]
    final_frames = [
        render_stage(final_shot, "完成", "记忆档案已安全保存到本地", index / 27, export_shot.cursor, click=False)
        for index in range(28)
    ]
    frames.extend(crossfade(frames[-1], final_frames[0]))
    frames.extend(final_frames)
    return frames


def write_media(frames: list[Image.Image]) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(
        MP4_PATH,
        fps=FPS,
        codec="libx264",
        quality=8,
        macro_block_size=None,
        ffmpeg_log_level="error",
        output_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    ) as writer:
        for frame in frames:
            writer.append_data(np.asarray(frame))

    gif_frames = [frame.resize((960, 540), Image.Resampling.LANCZOS) for frame in frames[::2]]
    palette = gif_frames[0].quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    indexed = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in gif_frames
    ]
    indexed[0].save(
        GIF_PATH,
        save_all=True,
        append_images=indexed[1:],
        duration=round(2000 / FPS),
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Created {MP4_PATH} ({MP4_PATH.stat().st_size / 1024 / 1024:.2f} MiB)")
    print(f"Created {GIF_PATH} ({GIF_PATH.stat().st_size / 1024 / 1024:.2f} MiB)")


def main() -> int:
    shots, dynamic = capture_application()
    frames = build_timeline(shots, dynamic)
    write_media(frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
