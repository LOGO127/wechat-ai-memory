from __future__ import annotations

import hashlib
import sqlite3
import struct
from pathlib import Path

import zstandard
from Crypto.Cipher import AES
from pypdf import PdfReader

from wechat_context_exporter.models import ConversationKind, MessageType
from wechat_context_exporter.service import ExportOptions, ExportService
from wechat_context_exporter.sources import wechat4_source
from wechat_context_exporter.sources.wechat4_source import WeChat4LocalSource


class _PlainDatabaseCache:
    def __init__(self, db_dir: Path, **_kwargs: object) -> None:
        self.db_dir = db_dir

    def get(self, relative_path: str) -> Path:
        return self.db_dir / Path(relative_path.replace("\\", "/"))

    def close(self) -> None:
        pass


def _create_database(path: Path, statements: list[tuple[str, tuple[object, ...]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        for statement, parameters in statements:
            connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def test_local_source_lists_conversations_and_reads_messages(tmp_path, monkeypatch) -> None:
    account = tmp_path / "wxid_me_abcd"
    db_dir = account / "db_storage"
    attachment_dir = account / "msg" / "attach"
    attachment_dir.mkdir(parents=True)
    peer = "wxid_friend"
    table = "Msg_" + hashlib.md5(peer.encode()).hexdigest()
    image_id = "0123456789abcdef0123456789abcdef"
    image_key = b"0123456789abcdef"
    xor_key = 0x5A
    image_head = b"\xff\xd8\xff\xe0" + b"H" * 28
    image_tail = b"full-resolution-image\xff\xd9"
    encrypted_head = AES.new(image_key, AES.MODE_ECB).encrypt(image_head + b"\x10" * 16)
    encoded_tail = bytes(byte ^ xor_key for byte in image_tail)
    (attachment_dir / f"{image_id}_t.dat").write_bytes(
        b"\x07\x08V2\x08\x07"
        + struct.pack("<II", len(image_head), len(image_tail))
        + b"\x00"
        + encrypted_head
        + encoded_tail
    )

    _create_database(
        db_dir / "contact" / "contact.db",
        [
            (
                "CREATE TABLE contact (username TEXT, alias TEXT, nick_name TEXT, remark TEXT)",
                (),
            ),
            (
                "INSERT INTO contact VALUES (?, ?, ?, ?)",
                (peer, "friend_alias", "好友昵称", "项目联系人"),
            ),
        ],
    )
    _create_database(
        db_dir / "session" / "session.db",
        [
            ("CREATE TABLE SessionTable (username TEXT, last_timestamp INTEGER)", ()),
            ("INSERT INTO SessionTable VALUES (?, ?)", (peer, 1_700_000_100)),
        ],
    )
    compressed = zstandard.ZstdCompressor().compress("压缩消息".encode())
    _create_database(
        db_dir / "message" / "message_0.db",
        [
            ("CREATE TABLE Name2Id (user_name TEXT)", ()),
            ("INSERT INTO Name2Id VALUES (?)", ("wxid_me",)),
            ("INSERT INTO Name2Id VALUES (?)", (peer,)),
            (
                f'CREATE TABLE "{table}" ('
                "local_id INTEGER, server_id INTEGER, create_time INTEGER, local_type INTEGER, "
                "real_sender_id INTEGER, message_content BLOB, packed_info_data BLOB, "
                "WCDB_CT_message_content INTEGER)",
                (),
            ),
            (
                f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 101, 1_700_000_000, 1, 2, "你好", None, 0),
            ),
            (
                f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (2, 102, 1_700_000_100, 1, 1, compressed, None, 4),
            ),
            (
                f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (3, 103, 1_700_000_200, 3, 2, "", b"\x00" + image_id.encode(), 0),
            ),
        ],
    )
    _create_database(
        db_dir / "message" / "message_1.db",
        [
            ("CREATE TABLE Name2Id (user_name TEXT)", ()),
            ("INSERT INTO Name2Id VALUES (?)", ("wxid_me",)),
            ("INSERT INTO Name2Id VALUES (?)", (peer,)),
            (
                f'CREATE TABLE "{table}" ('
                "local_id INTEGER, server_id INTEGER, create_time INTEGER, local_type INTEGER, "
                "real_sender_id INTEGER, message_content BLOB, packed_info_data BLOB, "
                "WCDB_CT_message_content INTEGER)",
                (),
            ),
            (
                f'INSERT INTO "{table}" VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (4, 104, 1_700_000_300, 1, 2, "第二分片消息", None, 0),
            ),
        ],
    )

    monkeypatch.setattr(wechat4_source, "capture_account_key", lambda *_args, **_kwargs: b"k" * 32)
    monkeypatch.setattr(wechat4_source, "DecryptedDatabaseCache", _PlainDatabaseCache)

    source = WeChat4LocalSource(account, image_key=image_key)
    try:
        conversations = source.list_conversations()
        messages = source.get_messages(peer)
        image_bytes = Path(messages[2].content).read_bytes()
        result = ExportService().export(
            source,
            ExportOptions(
                conversation_id=peer,
                output_pdf=tmp_path / "wechat-local.pdf",
                include_image_pages=True,
            ),
        )
        pdf_page_count = len(PdfReader(result.pdf_path).pages)
    finally:
        source.close()

    assert len(conversations) == 1
    assert conversations[0].name == "项目联系人"
    assert conversations[0].kind is ConversationKind.DIRECT
    assert [message.content for message in messages[:2]] == ["你好", "压缩消息"]
    assert [message.type for message in messages] == [
        MessageType.TEXT,
        MessageType.TEXT,
        MessageType.IMAGE,
        MessageType.TEXT,
    ]
    assert messages[0].sender == "项目联系人"
    assert messages[1].sender == "我"
    assert messages[1].is_outgoing
    assert image_bytes == image_head + image_tail
    assert messages[3].content == "第二分片消息"
    assert result.message_count == 4
    assert result.image_page_count == 1
    assert pdf_page_count == result.page_count
