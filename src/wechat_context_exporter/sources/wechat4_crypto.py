from __future__ import annotations

import ctypes
import csv
import hashlib
import hmac
import io
import os
import re
import shutil
import sqlite3
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from Crypto.Cipher import AES

from .base import SourceError


PAGE_SIZE = 4096
SALT_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE_SIZE = IV_SIZE + HMAC_SIZE
SQLITE_HEADER = b"SQLite format 3\x00"

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    relative_path: str
    path: Path
    salt: bytes
    first_page: bytes


def collect_database_targets(db_dir: Path, relative_paths: Iterable[str] | None = None) -> list[DatabaseTarget]:
    paths: list[Path]
    if relative_paths is None:
        paths = sorted(db_dir.rglob("*.db"))
    else:
        paths = [db_dir / relative_path for relative_path in relative_paths]
    targets: list[DatabaseTarget] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size < PAGE_SIZE:
            continue
        with path.open("rb") as stream:
            first_page = stream.read(PAGE_SIZE)
        relative = str(path.relative_to(db_dir)).replace("/", "\\")
        targets.append(DatabaseTarget(relative, path, first_page[:SALT_SIZE], first_page))
    return targets


def derive_mac_key(encryption_key: bytes, salt: bytes) -> bytes:
    mac_salt = bytes(byte ^ 0x3A for byte in salt)
    return hashlib.pbkdf2_hmac("sha512", encryption_key, mac_salt, 2, dklen=32)


def derive_encryption_key(raw_key: bytes, salt: bytes) -> bytes:
    if len(raw_key) != 32:
        raise SourceError("The WeChat account key must be 32 bytes")
    return hashlib.pbkdf2_hmac("sha512", raw_key, salt, 256_000, dklen=32)


def verify_database_key(encryption_key: bytes, first_page: bytes) -> bool:
    if len(encryption_key) != 32 or len(first_page) < PAGE_SIZE:
        return False
    salt = first_page[:SALT_SIZE]
    mac_key = derive_mac_key(encryption_key, salt)
    payload = first_page[SALT_SIZE : PAGE_SIZE - HMAC_SIZE]
    expected = first_page[PAGE_SIZE - HMAC_SIZE : PAGE_SIZE]
    digest = hmac.new(mac_key, payload, hashlib.sha512)
    digest.update(struct.pack("<I", 1))
    return hmac.compare_digest(digest.digest(), expected)


def verify_account_key(raw_key: bytes, first_page: bytes) -> bool:
    if len(first_page) < PAGE_SIZE:
        return False
    encryption_key = derive_encryption_key(raw_key, first_page[:SALT_SIZE])
    return verify_database_key(encryption_key, first_page)


def decrypt_page(encryption_key: bytes, page: bytes, page_number: int) -> bytes:
    if len(page) != PAGE_SIZE:
        raise SourceError(f"Encrypted page must be {PAGE_SIZE} bytes")
    iv_start = PAGE_SIZE - RESERVE_SIZE
    iv = page[iv_start : iv_start + IV_SIZE]
    cipher = AES.new(encryption_key, AES.MODE_CBC, iv)
    if page_number == 1:
        plaintext = SQLITE_HEADER + cipher.decrypt(page[SALT_SIZE:iv_start])
    else:
        plaintext = cipher.decrypt(page[:iv_start])
    return plaintext + (b"\x00" * RESERVE_SIZE)


def decrypt_database(source: Path, destination: Path, encryption_key: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as encrypted:
        first_page = encrypted.read(PAGE_SIZE)
        if not verify_database_key(encryption_key, first_page):
            raise SourceError(f"Encryption key verification failed for {source.name}")
        encrypted.seek(0)
        with destination.open("wb") as plain:
            page_number = 1
            while True:
                page = encrypted.read(PAGE_SIZE)
                if not page:
                    break
                if len(page) != PAGE_SIZE:
                    raise SourceError(f"Database size is not page-aligned: {source}")
                plain.write(decrypt_page(encryption_key, page, page_number))
                page_number += 1
    _apply_encrypted_wal(source.with_name(source.name + "-wal"), destination, encryption_key)
    connection = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    finally:
        connection.close()


def _apply_encrypted_wal(wal_path: Path, destination: Path, encryption_key: bytes) -> None:
    if not wal_path.is_file() or wal_path.stat().st_size < 32:
        return
    with wal_path.open("rb") as wal:
        header = wal.read(32)
        if len(header) != 32:
            return
        magic, _version, wal_page_size = struct.unpack(">III", header[:12])
        if magic not in {0x377F0682, 0x377F0683} or wal_page_size != PAGE_SIZE:
            raise SourceError(f"Unsupported or damaged WeChat WAL: {wal_path.name}")
        wal_salt_1, wal_salt_2 = struct.unpack(">II", header[16:24])
        frames: list[tuple[int, int, bytes]] = []
        while True:
            frame_header = wal.read(24)
            if len(frame_header) != 24:
                break
            encrypted_page = wal.read(PAGE_SIZE)
            if len(encrypted_page) != PAGE_SIZE:
                break
            page_number, commit_size, salt_1, salt_2 = struct.unpack(">IIII", frame_header[:16])
            if salt_1 != wal_salt_1 or salt_2 != wal_salt_2:
                continue
            if page_number == 0 or page_number > 1_000_000:
                continue
            frames.append((page_number, commit_size, encrypted_page))

    commit_indexes = [index for index, frame in enumerate(frames) if frame[1]]
    if not commit_indexes:
        return
    last_commit_index = commit_indexes[-1]
    last_commit_size = frames[last_commit_index][1]
    with destination.open("r+b") as plain:
        for page_number, _commit_size, encrypted_page in frames[: last_commit_index + 1]:
            plain.seek((page_number - 1) * PAGE_SIZE)
            plain.write(decrypt_page(encryption_key, encrypted_page, page_number))
        plain.truncate(last_commit_size * PAGE_SIZE)


class DecryptedDatabaseCache:
    def __init__(
        self,
        db_dir: Path,
        raw_key: bytes | None = None,
        keys: dict[str, bytes] | None = None,
    ) -> None:
        if raw_key is None and not keys:
            raise SourceError("A WeChat account key or per-database keys are required")
        self.db_dir = db_dir
        self.raw_key = raw_key
        self.keys = keys or {}
        self._temp = tempfile.TemporaryDirectory(prefix="wce-wechat4-")
        self._root = Path(self._temp.name)
        self._encrypted_root = self._root / "encrypted"
        self._decrypted_root = self._root / "decrypted"
        self._cache: dict[str, tuple[tuple[int, int, int, int], Path]] = {}

    def get(self, relative_path: str) -> Path:
        normalized = relative_path.replace("/", "\\")
        source = self.db_dir / Path(normalized.replace("\\", os.sep))
        signature = _database_signature(source)
        cached = self._cache.get(normalized)
        if cached and cached[0] == signature:
            return cached[1]
        key = self.keys.get(normalized)
        if key is None and self.raw_key is not None:
            with source.open("rb") as stream:
                salt = stream.read(SALT_SIZE)
            key = derive_encryption_key(self.raw_key, salt)
        if key is None:
            raise SourceError(f"No decryption key found for {normalized}")
        snapshot = self._snapshot_database(source, normalized)
        destination = self._decrypted_root / normalized.replace("\\", "_")
        decrypt_database(snapshot, destination, key)
        self._cache[normalized] = (signature, destination)
        return destination

    def _snapshot_database(self, source: Path, normalized: str) -> Path:
        snapshot = self._encrypted_root / normalized.replace("\\", "_")
        snapshot_wal = snapshot.with_name(snapshot.name + "-wal")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(5):
            try:
                before = _database_signature(source)
                shutil.copy2(source, snapshot)
                source_wal = source.with_name(source.name + "-wal")
                if source_wal.is_file():
                    shutil.copy2(source_wal, snapshot_wal)
                elif snapshot_wal.exists():
                    snapshot_wal.unlink()
                after = _database_signature(source)
            except OSError:
                time.sleep(0.1)
                continue
            if before == after:
                return snapshot
            time.sleep(0.1)
        raise SourceError(f"WeChat database changed repeatedly while being copied: {normalized}")

    def close(self) -> None:
        self._cache.clear()
        self._temp.cleanup()


def _database_signature(source: Path) -> tuple[int, int, int, int]:
    source_stat = source.stat()
    wal = source.with_name(source.name + "-wal")
    if wal.is_file():
        wal_stat = wal.stat()
        return source_stat.st_size, source_stat.st_mtime_ns, wal_stat.st_size, wal_stat.st_mtime_ns
    return source_stat.st_size, source_stat.st_mtime_ns, 0, 0


if os.name == "nt":
    from ctypes import wintypes

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("PartitionId", wintypes.WORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.c_void_p),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", wintypes.HMODULE),
            ("szModule", ctypes.c_wchar * 256),
            ("szExePath", ctypes.c_wchar * 260),
        ]


class WeChatProcessMemory:
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    MEM_COMMIT = 0x1000
    PAGE_GUARD = 0x100
    PAGE_NOACCESS = 0x01
    WRITABLE = {0x04, 0x08, 0x40, 0x80}

    def __init__(self, process_name: str = "Weixin.exe", pid: int | None = None) -> None:
        if os.name != "nt":
            raise SourceError("WeChat 4.x local access is supported on Windows only")
        self.process_name = process_name
        self.pid = pid or self._find_process_id()
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.kernel32.VirtualQueryEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(MEMORY_BASIC_INFORMATION),
            ctypes.c_size_t,
        ]
        self.handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_INFORMATION | self.PROCESS_VM_READ,
            False,
            self.pid,
        )
        if not self.handle:
            error = ctypes.get_last_error()
            raise SourceError(
                f"Cannot read WeChat process memory (Windows error {error}). "
                "Run this application as administrator."
            )

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.kernel32.CloseHandle(self.handle)
            self.handle = None

    def read(self, address: int, size: int) -> bytes | None:
        if size <= 0:
            return None
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        ok = self.kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read),
        )
        return buffer.raw[: read.value] if ok and read.value else None

    def __enter__(self) -> "WeChatProcessMemory":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def regions(self, writable_first: bool = False, max_size: int = 500 * 1024 * 1024) -> list[tuple[int, int, bool]]:
        regions: list[tuple[int, int, bool]] = []
        address = 0
        max_address = 0x7FFFFFFFFFFF
        info = MEMORY_BASIC_INFORMATION()
        while address < max_address:
            queried = self.kernel32.VirtualQueryEx(
                self.handle,
                ctypes.c_void_p(address),
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not queried:
                break
            base = int(info.BaseAddress or 0)
            size = int(info.RegionSize)
            readable = (
                info.State == self.MEM_COMMIT
                and size > 0
                and size <= max_size
                and not (info.Protect & self.PAGE_GUARD)
                and not (info.Protect & self.PAGE_NOACCESS)
            )
            if readable:
                protection = info.Protect & 0xFF
                regions.append((base, size, protection in self.WRITABLE))
            next_address = base + max(size, 0x1000)
            if next_address <= address:
                break
            address = next_address
        if writable_first:
            regions.sort(key=lambda item: not item[2])
        return regions

    def iter_region_chunks(self, base: int, size: int, chunk_size: int = 4 * 1024 * 1024, overlap: int = 256):
        offset = 0
        tail = b""
        while offset < size:
            requested = min(chunk_size, size - offset)
            buffer = ctypes.create_string_buffer(requested)
            read = ctypes.c_size_t()
            ok = self.kernel32.ReadProcessMemory(
                self.handle,
                ctypes.c_void_p(base + offset),
                buffer,
                requested,
                ctypes.byref(read),
            )
            if ok and read.value:
                data = tail + buffer.raw[: read.value]
                yield data
                tail = data[-overlap:]
            else:
                tail = b""
            offset += requested

    def _find_process_id(self) -> int:
        candidates = _process_candidates(self.process_name)
        if not candidates:
            raise SourceError("WeChat is not running. Open and sign in to WeChat, then try again.")
        return max(candidates)[1]


def _process_candidates(process_name: str) -> list[tuple[int, int]]:
    import locale
    import subprocess

    command = ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV", "/NH"]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        check=False,
    )
    candidates: list[tuple[int, int]] = []
    for fields in csv.reader(io.StringIO(result.stdout)):
        if len(fields) < 2 or fields[0].casefold() != process_name.casefold():
            continue
        try:
            pid = int(fields[1])
        except ValueError:
            continue
        digits = re.sub(r"\D", "", fields[4]) if len(fields) >= 5 else ""
        working_set = int(digits) if digits else 0
        candidates.append((working_set, pid))
    return sorted(candidates, reverse=True)


def extract_database_keys(
    db_dir: Path,
    relative_paths: Iterable[str] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, bytes]:
    targets = collect_database_targets(db_dir, relative_paths)
    if not targets:
        raise SourceError(f"No encrypted WeChat databases found under {db_dir}")
    by_salt: dict[bytes, list[DatabaseTarget]] = {}
    for target in targets:
        by_salt.setdefault(target.salt, []).append(target)

    found: dict[str, bytes] = {}
    candidate_keys: set[bytes] = set()
    pattern = re.compile(rb"x'([0-9a-fA-F]{64,192})'")
    with WeChatProcessMemory() as memory:
        regions = memory.regions()
        total = len(regions)
        for index, (base, size, _writable) in enumerate(regions, start=1):
            if progress and (index == 1 or index % 25 == 0):
                progress(index, total, f"Scanning WeChat memory ({len(found)}/{len(targets)} keys)")
            for chunk in memory.iter_region_chunks(base, size):
                for match in pattern.finditer(chunk):
                    hex_value = match.group(1)
                    if len(hex_value) < 64:
                        continue
                    try:
                        key = bytes.fromhex(hex_value[:64].decode("ascii"))
                    except ValueError:
                        continue
                    if key in candidate_keys:
                        continue
                    candidate_keys.add(key)
                    salt_hint = None
                    if len(hex_value) >= 96:
                        try:
                            salt_hint = bytes.fromhex(hex_value[-32:].decode("ascii"))
                        except ValueError:
                            salt_hint = None
                    candidates = by_salt.get(salt_hint, []) if salt_hint else targets
                    for target in candidates:
                        if target.relative_path in found:
                            continue
                        if verify_database_key(key, target.first_page):
                            found[target.relative_path] = key
            if len(found) == len(targets):
                break

    if candidate_keys and len(found) < len(targets):
        for target in targets:
            if target.relative_path in found:
                continue
            for key in candidate_keys:
                if verify_database_key(key, target.first_page):
                    found[target.relative_path] = key
                    break
    return found


def find_v2_image_sample(attachment_dir: Path) -> Path | None:
    candidates = sorted(
        attachment_dir.rglob("*_t.dat"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates[:200]:
        try:
            with path.open("rb") as stream:
                magic = stream.read(6)
            if magic == b"\x07\x08V2\x08\x07":
                return path
        except OSError:
            continue
    return None


def derive_image_key(cfg_dword: int, wxid: str) -> bytes:
    material = f"{cfg_dword}{wxid}".encode("utf-8")
    return hashlib.md5(material).hexdigest()[:16].encode("ascii")


def _find_weixin_module(pid: int) -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
    kernel32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MODULEENTRY32W)]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    invalid = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid:
        return None
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szModule.casefold() == "weixin.dll":
                return int(entry.modBaseAddr or 0), int(entry.modBaseSize)
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Module32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _read_remote_string(memory: WeChatProcessMemory, address: int) -> str:
    size_data = memory.read(address + 16, 8)
    if not size_data:
        return ""
    size = struct.unpack("<Q", size_data)[0]
    if not 1 <= size <= 512:
        return ""
    if size <= 15:
        data = memory.read(address, size)
    else:
        pointer_data = memory.read(address, 8)
        if not pointer_data:
            return ""
        data = memory.read(struct.unpack("<Q", pointer_data)[0], size)
    return data.decode("utf-8", errors="replace") if data else ""


def _image_key_from_config(memory: WeChatProcessMemory, ciphertext: bytes) -> bytes | None:
    module = _find_weixin_module(memory.pid)
    if module is None:
        return None
    base, module_size = module
    if not base or not 0 < module_size < 0x40000000:
        return None
    image = memory.read(base, module_size)
    if not image or len(image) != module_size:
        return None
    landmark = b"global_config"
    position = -1
    for offset in range(len(image) - 8, 15, -8):
        if struct.unpack_from("<I", image, offset)[0] != len(landmark):
            continue
        capacity = struct.unpack_from("<I", image, offset + 8)[0]
        if capacity and (capacity | 0x0F) == 0x0F and image[offset - 16 : offset - 3] == landmark:
            position = offset
            break
    if position < 0:
        return None
    signatures = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"wxgf", b"GIF")
    for pointer_back in (0x138, 0x130):
        owner_data = memory.read(base + position - pointer_back, 8)
        if not owner_data:
            continue
        owner = struct.unpack("<Q", owner_data)[0]
        config_data = memory.read(owner + 0x68, 8)
        if not config_data:
            continue
        config = struct.unpack("<Q", config_data)[0]
        if not 0x10000 <= config < 0x800000000000:
            continue
        dword_data = memory.read(config + 0x40, 4)
        wxid = _read_remote_string(memory, config + 0x48)
        if not dword_data or not wxid:
            continue
        key = derive_image_key(struct.unpack("<I", dword_data)[0], wxid)
        if AES.new(key, AES.MODE_ECB).decrypt(ciphertext).startswith(signatures):
            return key
    return None


def extract_image_key(
    attachment_dir: Path,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> bytes | None:
    sample_path = find_v2_image_sample(attachment_dir)
    if sample_path is None:
        return None
    with sample_path.open("rb") as stream:
        header = stream.read(15)
        ciphertext = stream.read(16)
    if len(header) < 15 or len(ciphertext) != 16:
        return None
    magic = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"wxgf", b"GIF")
    pattern_16 = re.compile(rb"(?<![A-Za-z0-9])([A-Za-z0-9]{16})(?![A-Za-z0-9])")
    pattern_32 = re.compile(rb"(?<![A-Za-z0-9])([A-Za-z0-9]{32})(?![A-Za-z0-9])")

    def valid(key: bytes) -> bool:
        return AES.new(key, AES.MODE_ECB).decrypt(ciphertext).startswith(magic)

    processes = _process_candidates("Weixin.exe")
    if not processes:
        raise SourceError("WeChat is not running. Open and sign in to WeChat, then try again.")
    tested: set[bytes] = set()
    opened = 0
    for process_index, (_working_set, pid) in enumerate(processes, start=1):
        if cancelled and cancelled():
            raise SourceError("图片读取已取消")
        if progress:
            progress(process_index, len(processes), f"正在扫描微信进程 {process_index}/{len(processes)}")
        try:
            memory = WeChatProcessMemory(pid=pid)
        except SourceError:
            continue
        opened += 1
        with memory:
            config_key = _image_key_from_config(memory, ciphertext)
            if config_key is not None:
                return config_key
            regions = memory.regions(writable_first=True, max_size=50 * 1024 * 1024)
            for base, size, _writable in regions:
                if cancelled and cancelled():
                    raise SourceError("图片读取已取消")
                for chunk in memory.iter_region_chunks(base, size, overlap=64):
                    for match in pattern_32.finditer(chunk):
                        candidate = match.group(1)[:16]
                        if candidate not in tested:
                            tested.add(candidate)
                            if valid(candidate):
                                return candidate
                    for match in pattern_16.finditer(chunk):
                        candidate = match.group(1)
                        if candidate not in tested:
                            tested.add(candidate)
                            if valid(candidate):
                                return candidate
    if not opened:
        raise SourceError("Cannot read any WeChat process memory. Run this application as administrator.")
    return None
