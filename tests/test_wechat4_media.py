from __future__ import annotations

import struct
import sys
from io import BytesIO
from types import SimpleNamespace

import av
import pytest
from Crypto.Cipher import AES
from PIL import Image

from wechat_context_exporter.sources import wechat4_media
from wechat_context_exporter.sources.base import SourceError
from wechat_context_exporter.sources.wechat4_media import (
    V2_MAGIC,
    _wxgf_partitions,
    decode_wxgf_image,
    decrypt_v2_image,
    derive_image_xor_key,
    image_extension,
)


def test_decrypt_v2_image_and_detect_jpeg(tmp_path) -> None:
    key = b"0123456789abcdef"
    xor_key = 0x5A
    head = b"\xff\xd8\xff\xe0" + b"A" * 29
    middle = b"middle-bytes"
    tail = b"image-tail\xff\xd9"
    padding = 16 - len(head) % 16
    padded = head + bytes([padding]) * padding
    encrypted_head = AES.new(key, AES.MODE_ECB).encrypt(padded)
    encoded_tail = bytes(byte ^ xor_key for byte in tail)
    data = (
        V2_MAGIC
        + struct.pack("<II", len(head), len(tail))
        + b"\x00"
        + encrypted_head
        + middle
        + encoded_tail
    )
    source = tmp_path / "sample_t.dat"
    source.write_bytes(data)

    result = decrypt_v2_image(source, key, xor_key)

    assert result == head + middle + tail
    assert image_extension(result) == ".jpg"
    assert derive_image_xor_key(tmp_path) == xor_key


def test_unknown_image_signature_returns_none() -> None:
    assert image_extension(b"not-an-image") is None


def test_decrypt_v2_image_reads_full_padding_block_for_aligned_head(tmp_path) -> None:
    key = b"0123456789abcdef"
    xor_key = 0x50
    head = b"\xff\xd8\xff\xe0" + b"aligned-head" + b"A" * 16
    assert len(head) % 16 == 0
    padded = head + b"\x10" * 16
    tail = b"tail\xff\xd9"
    source = tmp_path / "aligned_t.dat"
    source.write_bytes(
        V2_MAGIC
        + struct.pack("<II", len(head), len(tail))
        + b"\x01"
        + AES.new(key, AES.MODE_ECB).encrypt(padded)
        + bytes(byte ^ xor_key for byte in tail)
    )

    assert decrypt_v2_image(source, key, xor_key) == head + tail


def test_wxgf_partition_parser_finds_embedded_hevc_stream() -> None:
    stream = b"\x00\x00\x00\x01\x40\x01hevc-frame"
    data = b"wxgf" + b"\x09" + len(stream).to_bytes(4, "big") + stream

    assert _wxgf_partitions(data) == [(9, len(stream))]


def test_wxgf_decoder_passes_largest_partition_to_ffmpeg(monkeypatch) -> None:
    small = b"\x00\x00\x00\x01small"
    large = b"\x00\x00\x00\x01larger-hevc-frame"
    data = (
        b"wxgf"
        + b"\x09"
        + len(small).to_bytes(4, "big")
        + small
        + len(large).to_bytes(4, "big")
        + large
    )
    output = BytesIO()
    Image.new("RGB", (24, 32), "#167b55").save(output, format="PNG")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs["input"]
        return SimpleNamespace(returncode=0, stdout=output.getvalue(), stderr=b"")

    monkeypatch.setattr(wechat4_media.subprocess, "run", fake_run)

    decoded = decode_wxgf_image(data, ffmpeg_path="ffmpeg-test")

    assert captured["command"][0] == "ffmpeg-test"
    assert captured["input"] == large
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


def _encode_hevc(image: Image.Image) -> bytes:
    output = BytesIO()
    with av.open(output, mode="w", format="hevc") as container:
        stream = container.add_stream("libx265", rate=1)
        stream.width, stream.height = image.size
        stream.pix_fmt = "gbrp"
        stream.options = {
            "x265-params": "lossless=1:log-level=error:pools=none:frame-threads=1",
        }
        frame = av.VideoFrame.from_image(image)
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return output.getvalue()


def test_wxgf_decoder_preserves_largest_lossless_image_pixels() -> None:
    original = Image.new("RGB", (80, 64))
    original.putdata(
        [((x * 7) % 256, (y * 11) % 256, (x * y) % 256) for y in range(64) for x in range(80)]
    )
    thumbnail = _encode_hevc(Image.new("RGB", (16, 16), "#167b55"))
    full_resolution = _encode_hevc(original)
    assert len(full_resolution) > len(thumbnail)
    data = (
        b"wxgf\x09"
        + len(thumbnail).to_bytes(4, "big")
        + thumbnail
        + len(full_resolution).to_bytes(4, "big")
        + full_resolution
    )

    decoded = decode_wxgf_image(data)

    with Image.open(BytesIO(decoded)) as image:
        assert image.format == "PNG"
        assert image.size == original.size
        assert image.convert("RGB").tobytes() == original.tobytes()


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"not-wxgf", "Invalid WeChat WXGF image"),
        (b"wxgf\x09" + b"\x00" * 12, "No HEVC image partition"),
        (b"wxgf\x09\x00\x00\x00\x08\x00\x00\x00\x01bad!", "Failed to decode|No image frame"),
    ],
)
def test_wxgf_decoder_reports_malformed_images(data: bytes, error: str) -> None:
    with pytest.raises(SourceError, match=error):
        decode_wxgf_image(data)


def test_wxgf_decoder_reports_missing_dependency(monkeypatch) -> None:
    stream = b"\x00\x00\x00\x01\x40\x01hevc-frame"
    data = b"wxgf\x09" + len(stream).to_bytes(4, "big") + stream
    monkeypatch.setitem(sys.modules, "av", None)

    with pytest.raises(SourceError, match="bundled PyAV decoder"):
        decode_wxgf_image(data)
