from __future__ import annotations

import argparse
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory


def _check_wxgf(fixtures: Path) -> dict[str, object]:
    from PIL import Image

    from .sources.wechat4_media import decode_wxgf_image

    decoded = decode_wxgf_image((fixtures / "image.wxgf").read_bytes())
    with Image.open(BytesIO(decoded)) as actual, Image.open(fixtures / "expected.png") as expected:
        if actual.size != expected.size or actual.convert("RGB").tobytes() != expected.convert("RGB").tobytes():
            raise RuntimeError("WXGF output dimensions or pixels differ from the lossless fixture")
        return {"width": actual.width, "height": actual.height, "pixels_equal": True}


def _check_silk(fixtures: Path) -> dict[str, object]:
    import numpy as np
    from faster_whisper.audio import decode_audio

    from .voice import decode_silk_to_wav

    with TemporaryDirectory(prefix="wechat-runtime-audio-") as temporary:
        wav = decode_silk_to_wav(fixtures / "voice.silk", Path(temporary) / "voice.wav")
        samples = decode_audio(str(wav), sampling_rate=16_000)
    if samples.ndim != 1 or not 15_000 <= len(samples) <= 17_000 or not np.isfinite(samples).all():
        raise RuntimeError("SILK decode or audio resampling failed the one-second fixture")
    return {"samples": len(samples), "sample_rate": 16_000}


def _check_speech(_fixtures: Path) -> dict[str, object]:
    import ctranslate2

    supported = sorted(ctranslate2.get_supported_compute_types("cpu"))
    if "int8" not in supported:
        raise RuntimeError("The bundled speech runtime does not support CPU int8")
    return {"cpu_compute_types": supported}


def _check_vad(_fixtures: Path) -> dict[str, object]:
    import numpy as np
    from faster_whisper.vad import get_vad_model

    probabilities = get_vad_model()(np.zeros(512 * 32, dtype="float32"))
    if probabilities.size != 32 or not np.isfinite(probabilities).all():
        raise RuntimeError("Bundled VAD inference returned invalid probabilities")
    if (probabilities < 0).any() or (probabilities > 1).any():
        raise RuntimeError("Bundled VAD probabilities are outside [0, 1]")
    return {"frames": int(probabilities.size), "inference": "ok"}


def verify_runtime(fixture_dir: Path, report_path: Path) -> int:
    """Verify packaged native dependencies without accessing chats or downloading models."""
    checks = {}
    for name, check in (
        ("wxgf", _check_wxgf),
        ("silk_audio", _check_silk),
        ("speech_runtime", _check_speech),
        ("vad", _check_vad),
    ):
        try:
            checks[name] = {"ok": True, **check(Path(fixture_dir))}
        except Exception as exc:
            checks[name] = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
    success = all(check["ok"] for check in checks.values())
    report = {"ok": success, "checks": checks}
    report_path = Path(report_path)
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        return 2
    return 0 if success else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify packaged media and speech dependencies")
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("report_path", type=Path)
    args = parser.parse_args(argv)
    return verify_runtime(args.fixture_dir, args.report_path)
