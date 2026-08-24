from __future__ import annotations

import os
import shutil
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
CANVAS_SIZE = (1440, 900)
GIF_SIZE = (960, 600)


@dataclass(frozen=True)
class Shot:
    image: Image.Image
    focus: tuple[int, int, int, int] | None
    cursor: tuple[int, int] | None


@dataclass(frozen=True)
class TutorialCapture:
    shots: dict[str, Shot]
    image_images: list[Image.Image]
    search_images: list[Image.Image]
    progress_images: list[Image.Image]
    pdf_pages: list[Image.Image]


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


def capture_application() -> TutorialCapture:
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

    image_focus = widget_rect(window, window.image_key_button)
    image_images = [grab(window, "02-image-ready")]
    window.status_label.setText("图片读取已启用")
    image_images.append(grab(window, "02-image-loaded"))
    shots["image"] = Shot(image_images[-1], image_focus, center(image_focus))

    range_focus = widget_rect(window, window.conversation_combo, window.start_date, window.end_date)
    shots["range"] = Shot(grab(window, "03-range"), range_focus, center(range_focus))

    search_focus = widget_rect(window, window.search_edit)
    search_images: list[Image.Image] = []
    for index, query in enumerate(["", "随", "随机", "随机种", "随机种子"]):
        window.search_edit.setText(query)
        app.processEvents()
        search_images.append(grab(window, f"04-search-{index}"))
    shots["search"] = Shot(search_images[-1], search_focus, center(search_focus))

    window.search_edit.clear()
    window.keep_pages_check.setChecked(True)
    window.companions_check.setChecked(True)
    export_focus = widget_rect(window, window.output_edit, window.companions_check, window.export_button)
    shots["export"] = Shot(
        grab(window, "05-export"),
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
    pages_dir = WORK / "ECO_project_memory_pages"
    for path in [output, output.with_suffix(".md"), output.with_suffix(".json")]:
        path.unlink(missing_ok=True)
    shutil.rmtree(pages_dir, ignore_errors=True)
    window.output_edit.setText(str(output))
    window._start_export()
    wait_until(app, lambda: window._last_result is not None, timeout=15.0)
    app.processEvents()
    window.output_edit.setText("outputs/ECO_project_memory.pdf")
    final_focus = widget_rect(window, window.open_folder_button, window.export_button)
    shots["final"] = Shot(grab(window, "06-final"), final_focus, center(final_focus))
    pdf_pages = []
    for page_path in sorted(pages_dir.glob("page_[0-9][0-9][0-9][0-9]_*.png")):
        with Image.open(page_path) as page:
            pdf_pages.append(page.convert("RGB"))
    if not pdf_pages:
        raise RuntimeError("The tutorial export did not produce rendered PDF pages")
    window.close()
    return TutorialCapture(shots, image_images, search_images, progress_images, pdf_pages)


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
    logo = Image.open(ROOT / "docs" / "images" / "app-icon.png").convert("RGBA").resize((96, 96), Image.Resampling.LANCZOS)
    frames = []
    for index in range(count):
        frame = background.copy()
        overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        overlay.alpha_composite(logo, ((CANVAS_SIZE[0] - 96) // 2, 258))
        draw = ImageDraw.Draw(overlay)
        title = "把微信聊天整理成 AI 记忆档案"
        subtitle = "本地读取  ·  图片恢复  ·  Agent-ready 归档"
        title_font = font(46, True)
        subtitle_font = font(24)
        title_box = draw.textbbox((0, 0), title, font=title_font)
        subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        draw.text(((CANVAS_SIZE[0] - title_box[2]) // 2, 390), title, font=title_font, fill="white")
        draw.text(((CANVAS_SIZE[0] - subtitle_box[2]) // 2, 462), subtitle, font=subtitle_font, fill=(221, 238, 229, 255))
        line_width = int(460 * min(1.0, (index + 1) / max(1, count - 2)))
        line_x = (CANVAS_SIZE[0] - 460) // 2
        draw.rounded_rectangle((line_x, 530, line_x + 460, 536), radius=3, fill=(255, 255, 255, 50))
        draw.rounded_rectangle((line_x, 530, line_x + line_width, 536), radius=3, fill=(8, 184, 108, 255))
        frames.append(Image.alpha_composite(frame, overlay).convert("RGB"))
    return frames


def crossfade(left: Image.Image, right: Image.Image, count: int = 4) -> list[Image.Image]:
    return [Image.blend(left, right, (index + 1) / (count + 1)) for index in range(count)]


def fit_image(image: Image.Image, maximum: tuple[int, int]) -> Image.Image:
    scale = min(maximum[0] / image.width, maximum[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def pdf_viewer_frame(pages: list[Image.Image], active_index: int) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#e7ece9").convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, CANVAS_SIZE[0], 72), fill="#1c2924")
    draw.text((28, 22), "ECO_project_memory.pdf", font=font(22, True), fill="white")
    draw.text((1170, 24), f"第 {active_index + 1} / {len(pages)} 页", font=font(18), fill="#cfe2d8")

    draw.rectangle((0, 72, 228, CANVAS_SIZE[1]), fill="#f7f9f8")
    draw.text((28, 96), "页面", font=font(18, True), fill="#52615a")
    thumb_y = 136
    for index, page in enumerate(pages[:3]):
        thumbnail = fit_image(page, (126, 178)).convert("RGBA")
        x = (228 - thumbnail.width) // 2
        outline = "#08b86c" if index == active_index else "#cbd5d0"
        draw.rounded_rectangle(
            (x - 7, thumb_y - 7, x + thumbnail.width + 7, thumb_y + thumbnail.height + 7),
            radius=5,
            fill="white",
            outline=outline,
            width=4 if index == active_index else 2,
        )
        canvas.alpha_composite(thumbnail, (x, thumb_y))
        draw.text((102, thumb_y + thumbnail.height + 12), str(index + 1), font=font(15, True), fill="#66736d")
        thumb_y += 238

    page = fit_image(pages[active_index], (590, 790)).convert("RGBA")
    page_x = 296 + (710 - page.width) // 2
    page_y = 90 + (790 - page.height) // 2
    shadow = Image.new("RGBA", (page.width + 34, page.height + 34), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rectangle((17, 17, page.width + 17, page.height + 17), fill=(23, 35, 31, 75))
    shadow = shadow.filter(ImageFilter.GaussianBlur(11))
    canvas.alpha_composite(shadow, (page_x - 17, page_y - 11))
    canvas.alpha_composite(page, (page_x, page_y))

    panel_x = 1070
    draw.text((panel_x, 180), "实际导出效果", font=font(28, True), fill="#17231f")
    draw.rounded_rectangle((panel_x, 226, panel_x + 72, 232), radius=3, fill="#08b86c")
    details = [
        "对话按时间顺序完整排版",
        "聊天图片独立高清成页",
        "可直接交给 Agent 阅读",
    ]
    for index, detail in enumerate(details):
        y = 285 + index * 82
        draw.ellipse((panel_x, y + 7, panel_x + 13, y + 20), fill="#08b86c")
        draw.text((panel_x + 28, y), detail, font=font(21), fill="#34423c")
    draw.text((panel_x, 570), "同时生成", font=font(17, True), fill="#6b7771")
    chip_x = panel_x
    for label in ["PDF", "Markdown", "JSON"]:
        label_width = draw.textbbox((0, 0), label, font=font(16, True))[2]
        chip_width = label_width + 28
        draw.rounded_rectangle((chip_x, 608, chip_x + chip_width, 648), radius=6, fill="#ffffff", outline="#c7d2cd")
        draw.text((chip_x + 14, 617), label, font=font(16, True), fill="#087f4f")
        chip_x += chip_width + 10
    draw.text((panel_x, 720), "本地生成 · 数据不上传", font=font(18), fill="#6b7771")
    return canvas.convert("RGB")


def build_timeline(capture: TutorialCapture) -> list[Image.Image]:
    shots = capture.shots
    frames = intro_frames(shots["range"].image, 20)
    previous_cursor = (CANVAS_SIZE[0] // 2, CANVAS_SIZE[1] - 54)

    connect_shot = shots["connect"]
    connect_frames = [
        render_stage(connect_shot, "01", "连接已登录的 Windows 微信", index / 21, previous_cursor)
        for index in range(22)
    ]
    frames.extend(crossfade(frames[-1], connect_frames[0]))
    frames.extend(connect_frames)
    previous_cursor = connect_shot.cursor or previous_cursor

    image_shot = shots["image"]
    image_frames = []
    for index in range(26):
        active_image = capture.image_images[0] if index < 18 else capture.image_images[1]
        active = Shot(active_image, image_shot.focus, image_shot.cursor)
        image_frames.append(render_stage(active, "02", "读取图片，恢复聊天中的原图", index / 25, previous_cursor))
    frames.extend(crossfade(frames[-1], image_frames[0]))
    frames.extend(image_frames)
    previous_cursor = image_shot.cursor or previous_cursor

    range_shot = shots["range"]
    range_frames = [
        render_stage(range_shot, "03", "选择会话和需要保留的日期", index / 21, previous_cursor)
        for index in range(22)
    ]
    frames.extend(crossfade(frames[-1], range_frames[0]))
    frames.extend(range_frames)
    previous_cursor = range_shot.cursor or previous_cursor

    search_shot = shots["search"]
    search_frames = []
    for index in range(28):
        variant = capture.search_images[min(4, max(0, (index - 8) // 4))]
        active = Shot(variant, search_shot.focus, search_shot.cursor)
        search_frames.append(render_stage(active, "04", "输入关键词，预览会立即筛选", index / 27, previous_cursor, click=False))
    frames.extend(crossfade(frames[-1], search_frames[0]))
    frames.extend(search_frames)
    previous_cursor = search_shot.cursor or previous_cursor

    export_shot = shots["export"]
    export_frames = [
        render_stage(export_shot, "05", "生成 PDF · Markdown · JSON", index / 23, previous_cursor)
        for index in range(24)
    ]
    frames.extend(crossfade(frames[-1], export_frames[0]))
    frames.extend(export_frames)

    for index in range(18):
        active = Shot(capture.progress_images[min(3, index // 5)], export_shot.focus, export_shot.cursor)
        frames.append(render_stage(active, "05", "档案正在本机生成", index / 17, export_shot.cursor, click=False))

    final_shot = shots["final"]
    final_frames = [render_stage(final_shot, "完成", "记忆档案已保存到本地", index / 15, export_shot.cursor, click=False) for index in range(16)]
    frames.extend(crossfade(frames[-1], final_frames[0]))
    frames.extend(final_frames)

    for page_index in range(min(2, len(capture.pdf_pages))):
        viewer = Shot(pdf_viewer_frame(capture.pdf_pages, page_index), None, None)
        viewer_frames = [
            render_stage(
                viewer,
                "06",
                f"查看实际导出的 PDF · 第 {page_index + 1} 页",
                index / 29,
                None,
                click=False,
            )
            for index in range(30)
        ]
        frames.extend(crossfade(frames[-1], viewer_frames[0], count=6))
        frames.extend(viewer_frames)
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

    gif_frames = [frame.resize(GIF_SIZE, Image.Resampling.LANCZOS) for frame in frames[::2]]
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
    capture = capture_application()
    frames = build_timeline(capture)
    write_media(frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
