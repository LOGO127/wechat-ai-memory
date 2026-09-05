from __future__ import annotations

import argparse
import json
import os
import subprocess
from io import BytesIO
from pathlib import Path


def create_fixtures(root: Path) -> None:
    import av
    import pysilk
    from PIL import Image

    root.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (80, 64))
    image.putdata([((x * 7) % 256, (y * 11) % 256, (x * y) % 256) for y in range(64) for x in range(80)])
    image.save(root / "expected.png")
    output = BytesIO()
    with av.open(output, mode="w", format="hevc") as container:
        stream = container.add_stream("libx265", rate=1)
        stream.width, stream.height = image.size
        stream.pix_fmt = "gbrp"
        stream.options = {"x265-params": "lossless=1:log-level=error:pools=none:frame-threads=1"}
        for packet in stream.encode(av.VideoFrame.from_image(image)):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    hevc = output.getvalue()
    (root / "image.wxgf").write_bytes(b"wxgf\x09" + len(hevc).to_bytes(4, "big") + hevc)
    with (root / "voice.silk").open("wb") as voice:
        pysilk.encode(BytesIO(b"\x00\x00" * 24_000), voice, sample_rate=24_000, bit_rate=24_000)


def run_smoke(executable: Path, output: Path) -> dict[str, object]:
    executable = executable.resolve(strict=True)
    report = output.resolve()
    work_dir = report.parent
    fixtures = work_dir / "runtime-fixtures"
    create_fixtures(fixtures)
    report.unlink(missing_ok=True)
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE"):
        environment.pop(key, None)
    system_root = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join(str(path) for path in (system_root / "System32", system_root))
    environment.update(QT_QPA_PLATFORM="offscreen", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    result = subprocess.run(
        [str(executable), "--verify-runtime", str(fixtures), str(report)],
        cwd=work_dir,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )
    if not report.is_file():
        raise RuntimeError(f"Packaged runtime produced no report (exit {result.returncode}): {result.stderr[-1000:]!r}")
    payload = json.loads(report.read_text(encoding="utf-8"))
    required = ("wxgf", "silk_audio", "speech_runtime", "vad")
    if result.returncode or not payload.get("ok") or not all(payload.get("checks", {}).get(name, {}).get("ok") for name in required):
        raise RuntimeError(f"Packaged runtime smoke failed (exit {result.returncode}): {payload}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.exe, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
