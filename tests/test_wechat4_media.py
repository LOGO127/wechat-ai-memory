from __future__ import annotations

import struct

from Crypto.Cipher import AES

from wechat_context_exporter.sources.wechat4_media import (
    V2_MAGIC,
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
