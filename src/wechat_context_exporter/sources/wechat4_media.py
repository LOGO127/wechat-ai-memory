from __future__ import annotations

import collections
import struct
import tempfile
from pathlib import Path

from Crypto.Cipher import AES

from .base import SourceError


V2_MAGIC = b"\x07\x08V2\x08\x07"


def derive_image_xor_key(attachment_dir: Path, sample_limit: int = 32) -> int | None:
    candidates = sorted(
        attachment_dir.rglob("*_t.dat"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    votes: collections.Counter[int] = collections.Counter()
    for path in candidates[:sample_limit]:
        try:
            with path.open("rb") as stream:
                if stream.read(6) != V2_MAGIC:
                    continue
                stream.seek(-2, 2)
                tail = stream.read(2)
        except OSError:
            continue
        if len(tail) != 2:
            continue
        first = tail[0] ^ 0xFF
        second = tail[1] ^ 0xD9
        if first == second:
            votes[first] += 1
    return votes.most_common(1)[0][0] if votes else None


def decrypt_v2_image(source: Path, aes_key: bytes, xor_key: int) -> bytes:
    if len(aes_key) != 16:
        raise SourceError("The WeChat image AES key must be 16 bytes")
    data = source.read_bytes()
    if len(data) < 31 or data[:6] != V2_MAGIC:
        raise SourceError(f"Unsupported WeChat image format: {source.name}")
    aes_size, xor_size = struct.unpack("<II", data[6:14])
    # WeChat applies PKCS#7 to this segment, so an already aligned plaintext
    # still receives a complete 16-byte padding block.
    encrypted_size = aes_size + (16 - (aes_size % 16))
    aes_start = 15
    aes_end = aes_start + encrypted_size
    xor_start = len(data) - xor_size
    if aes_end > xor_start or xor_start < aes_start:
        raise SourceError(f"Invalid WeChat image layout: {source.name}")
    decrypted_padded = AES.new(aes_key, AES.MODE_ECB).decrypt(data[aes_start:aes_end])
    padding = decrypted_padded[-1] if decrypted_padded else 0
    if not 1 <= padding <= 16 or decrypted_padded[-padding:] != bytes([padding]) * padding:
        raise SourceError(f"Invalid WeChat image padding: {source.name}")
    decrypted_head = decrypted_padded[:-padding]
    if len(decrypted_head) != aes_size:
        raise SourceError(f"Invalid WeChat image AES length: {source.name}")
    middle = data[aes_end:xor_start]
    tail = bytes(byte ^ xor_key for byte in data[xor_start:])
    return decrypted_head + middle + tail


def image_extension(data: bytes) -> str | None:
    signatures = (
        (b"\xff\xd8\xff", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"RIFF", ".webp"),
    )
    for signature, extension in signatures:
        if data.startswith(signature):
            return extension
    return None


class DecryptedImageCache:
    def __init__(self, attachment_dir: Path, aes_key: bytes | None) -> None:
        self.attachment_dir = attachment_dir
        self.aes_key = aes_key
        self.xor_key = derive_image_xor_key(attachment_dir)
        self._temp = tempfile.TemporaryDirectory(prefix="wce-images-")
        self._root = Path(self._temp.name)
        self._index: dict[str, list[Path]] | None = None
        self._cache: dict[Path, Path] = {}

    def resolve(self, identifiers: list[str]) -> Path | None:
        if self.aes_key is None or self.xor_key is None:
            return None
        if self._index is None:
            self._index = self._build_index()
        for identifier in identifiers:
            paths = self._index.get(identifier.casefold(), [])
            for source in sorted(paths, key=_image_variant_rank):
                result = self._decrypt(source)
                if result is not None:
                    return result
        return None

    def close(self) -> None:
        self._cache.clear()
        self._index = None
        self._temp.cleanup()

    def _build_index(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        for path in self.attachment_dir.rglob("*.dat"):
            stem = path.stem
            if stem.endswith(("_t", "_h")):
                stem = stem[:-2]
            index.setdefault(stem.casefold(), []).append(path)
        return index

    def _decrypt(self, source: Path) -> Path | None:
        cached = self._cache.get(source)
        if cached and cached.is_file():
            return cached
        try:
            data = decrypt_v2_image(source, self.aes_key or b"", self.xor_key or 0)
        except (OSError, SourceError, ValueError):
            return None
        extension = image_extension(data)
        if extension is None:
            return None
        destination = self._root / f"{source.stem}{extension}"
        destination.write_bytes(data)
        self._cache[source] = destination
        return destination


def _image_variant_rank(path: Path) -> tuple[int, int]:
    if path.stem.endswith("_t"):
        variant = 2
    elif path.stem.endswith("_h"):
        variant = 1
    else:
        variant = 0
    try:
        size = -path.stat().st_size
    except OSError:
        size = 0
    return variant, size
