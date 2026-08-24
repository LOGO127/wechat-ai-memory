from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "demo_result.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    candidates = [Path("C:/Windows/Fonts") / name, Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (1600, 1000), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1600, 116), fill="#18231f")
    draw.text((70, 34), "Experiment 042 · Training Summary", font=font(42, True), fill="#ffffff")
    draw.text((70, 145), "Loss by epoch", font=font(30, True), fill="#17202a")

    chart = (90, 210, 1510, 790)
    draw.rectangle(chart, fill="#ffffff", outline="#ced5d1", width=3)
    for step in range(6):
        y = chart[1] + 45 + step * 92
        draw.line((chart[0] + 80, y, chart[2] - 40, y), fill="#e3e7e5", width=2)
        draw.text((chart[0] + 18, y - 13), f"{1.0 - step * 0.18:.1f}", font=font(19), fill="#6b7671")
    x0, y0 = chart[0] + 80, chart[3] - 45
    x1 = chart[2] - 40
    draw.line((x0, chart[1] + 35, x0, y0), fill="#58645e", width=3)
    draw.line((x0, y0, x1, y0), fill="#58645e", width=3)

    train_points = []
    validation_points = []
    for epoch in range(30):
        x = x0 + epoch * (x1 - x0) / 29
        train = 0.86 * (0.91 ** epoch) + 0.08
        validation = 0.78 * (0.89 ** epoch) + 0.19 + max(0, epoch - 18) * 0.012
        train_points.append((x, y0 - train * 500))
        validation_points.append((x, y0 - validation * 500))
    draw.line(train_points, fill="#177b55", width=7, joint="curve")
    draw.line(validation_points, fill="#d66735", width=7, joint="curve")
    draw.ellipse((validation_points[18][0] - 8, validation_points[18][1] - 8, validation_points[18][0] + 8, validation_points[18][1] + 8), fill="#d66735")
    draw.text((1060, 246), "TRAIN", font=font(21, True), fill="#177b55")
    draw.text((1235, 246), "VALIDATION", font=font(21, True), fill="#d66735")

    cards = [(90, 835, 440, 940), (475, 835, 825, 940), (860, 835, 1210, 940), (1245, 835, 1510, 940)]
    labels = [("BEST EPOCH", "18"), ("VAL LOSS", "0.284"), ("ACCURACY", "91.7%"), ("SEED", "2026")]
    for rect, (label, value) in zip(cards, labels, strict=True):
        draw.rectangle(rect, fill="#ffffff", outline="#ced5d1", width=2)
        draw.text((rect[0] + 22, rect[1] + 16), label, font=font(18, True), fill="#6b7671")
        draw.text((rect[0] + 22, rect[1] + 46), value, font=font(34, True), fill="#17202a")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()

