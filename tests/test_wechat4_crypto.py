from __future__ import annotations

import hashlib
import hmac
import struct

from Crypto.Cipher import AES

from wechat_context_exporter.sources.wechat4_crypto import (
    DecryptedDatabaseCache,
    HMAC_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    SQLITE_HEADER,
    _apply_encrypted_wal,
    decrypt_page,
    derive_encryption_key,
    derive_image_key,
    derive_mac_key,
    verify_account_key,
    verify_database_key,
)


def test_image_key_derivation_uses_account_configuration() -> None:
    expected = hashlib.md5(b"123456wxid_example").hexdigest()[:16].encode("ascii")

    assert derive_image_key(123456, "wxid_example") == expected
    assert len(expected) == 16


def _encrypted_first_page(raw_key: bytes) -> tuple[bytes, bytes]:
    salt = bytes(range(SALT_SIZE))
    key = derive_encryption_key(raw_key, salt)
    iv = bytes(range(16, 32))
    body = bytearray(PAGE_SIZE - RESERVE_SIZE)
    body[: len(SQLITE_HEADER)] = SQLITE_HEADER
    body[16:24] = b"WCE-test"
    body[20] = RESERVE_SIZE
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(bytes(body[SALT_SIZE:]))
    payload = ciphertext + iv
    digest = hmac.new(derive_mac_key(key, salt), payload, hashlib.sha512)
    digest.update(struct.pack("<I", 1))
    return salt + payload + digest.digest(), bytes(body) + (b"\x00" * RESERVE_SIZE)


def test_account_key_derivation_verification_and_page_decryption() -> None:
    raw_key = bytes(range(32))
    encrypted, expected = _encrypted_first_page(raw_key)
    encryption_key = derive_encryption_key(raw_key, encrypted[:SALT_SIZE])

    assert len(encrypted) == PAGE_SIZE
    assert verify_account_key(raw_key, encrypted)
    assert verify_database_key(encryption_key, encrypted)
    assert not verify_account_key(bytes(reversed(raw_key)), encrypted)
    assert decrypt_page(encryption_key, encrypted, 1) == expected


def test_invalid_raw_key_length_is_rejected() -> None:
    try:
        derive_encryption_key(b"too-short", b"0" * SALT_SIZE)
    except RuntimeError as exc:
        assert "32 bytes" in str(exc)
    else:
        raise AssertionError("short account key should fail")


def test_database_snapshot_copies_database_and_wal(tmp_path) -> None:
    db_dir = tmp_path / "db_storage"
    source = db_dir / "message" / "message_0.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"encrypted-database")
    source.with_name(source.name + "-wal").write_bytes(b"encrypted-wal")
    cache = DecryptedDatabaseCache(db_dir, raw_key=b"k" * 32)
    try:
        snapshot = cache._snapshot_database(source, r"message\message_0.db")
        assert snapshot != source
        assert snapshot.read_bytes() == b"encrypted-database"
        assert snapshot.with_name(snapshot.name + "-wal").read_bytes() == b"encrypted-wal"
    finally:
        cache.close()


def _encrypted_nonfirst_page(key: bytes, marker: bytes, iv_byte: int) -> bytes:
    plaintext = marker * (PAGE_SIZE - RESERVE_SIZE)
    iv = bytes([iv_byte]) * 16
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext)
    return ciphertext + iv + (b"\x00" * HMAC_SIZE)


def test_wal_replay_ignores_frames_after_last_commit(tmp_path) -> None:
    key = b"k" * 32
    destination = tmp_path / "plain.db"
    destination.write_bytes(b"0" * (PAGE_SIZE * 2))
    salt_1, salt_2 = 0x11223344, 0x55667788
    header = struct.pack(">IIIIIIII", 0x377F0682, 3_007_000, PAGE_SIZE, 0, salt_1, salt_2, 0, 0)

    def frame(page_number: int, commit_size: int, encrypted_page: bytes) -> bytes:
        return struct.pack(">IIIIII", page_number, commit_size, salt_1, salt_2, 0, 0) + encrypted_page

    wal = tmp_path / "plain.db-wal"
    wal.write_bytes(
        header
        + frame(2, 2, _encrypted_nonfirst_page(key, b"C", 1))
        + frame(2, 0, _encrypted_nonfirst_page(key, b"U", 2))
    )

    _apply_encrypted_wal(wal, destination, key)

    result = destination.read_bytes()
    assert len(result) == PAGE_SIZE * 2
    assert result[PAGE_SIZE : PAGE_SIZE + 32] == b"C" * 32
