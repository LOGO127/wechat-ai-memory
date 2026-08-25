from __future__ import annotations

import hashlib
import html
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

import zstandard

from ..models import Conversation, ConversationKind, Message, MessageType
from .base import SourceError
from .wechat4_crypto import DecryptedDatabaseCache, ProgressCallback
from .wechat4_discovery import WeChat4Account, select_wechat4_account
from .wechat4_key_capture import capture_account_key
from .wechat4_media import DecryptedImageCache
from .wechat4_voice import WeChatVoiceCache
from ..voice import VoiceTranscriptCache, default_voice_model, voice_placeholder


MESSAGE_TYPE_LABELS = {
    42: "[名片]",
    43: "[视频]",
    47: "[表情]",
    48: "[位置]",
    50: "[通话]",
    10000: "[系统消息]",
    10002: "[已撤回消息]",
}


class WeChat4LocalSource:
    def __init__(
        self,
        account: WeChat4Account | str | Path | None = None,
        raw_key: bytes | None = None,
        image_key: bytes | None = None,
        progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.account = account if isinstance(account, WeChat4Account) else select_wechat4_account(account)
        self.raw_key = raw_key or capture_account_key(
            self.account.account_dir,
            progress=progress,
            cancelled=cancelled,
        )
        self._databases = DecryptedDatabaseCache(self.account.db_dir, raw_key=self.raw_key)
        self._images = DecryptedImageCache(self.account.attachment_dir, image_key)
        self._voices = WeChatVoiceCache(self._databases, self.account.id)
        self._voice_transcripts = VoiceTranscriptCache()
        self._contacts = self._load_contacts()
        self._message_locations = self._index_message_tables(progress)
        self._conversations = self._load_conversations()
        self._own_wxid = _account_wxid(self.account)

    def list_conversations(self) -> list[Conversation]:
        return list(self._conversations)

    def get_messages(
        self,
        conversation_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Message]:
        conversation = next((item for item in self._conversations if item.id == conversation_id), None)
        if conversation is None:
            raise SourceError(f"Unknown WeChat conversation: {conversation_id}")
        locations = self._message_locations.get(conversation_id, [])
        if not locations:
            raise SourceError(f"No message table was found for {conversation.name}")
        messages: list[Message] = []
        for relative_path, table in locations:
            db_path = self._databases.get(relative_path)
            with _connect(db_path) as connection:
                columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                required = {"local_id", "create_time", "local_type", "real_sender_id", "message_content"}
                if not required.issubset(columns):
                    missing = ", ".join(sorted(required - columns))
                    raise SourceError(f"Unsupported WeChat message schema; missing {missing}")
                selected = [
                    "m.local_id",
                    "m.create_time",
                    "m.local_type",
                    "m.real_sender_id",
                    "m.message_content",
                    "n.user_name AS sender_wxid",
                ]
                selected.append("m.server_id" if "server_id" in columns else "0 AS server_id")
                selected.append(
                    'm."WCDB_CT_message_content" AS content_compression'
                    if "WCDB_CT_message_content" in columns
                    else "0 AS content_compression"
                )
                selected.append(
                    "m.packed_info_data AS packed_info_data"
                    if "packed_info_data" in columns
                    else "NULL AS packed_info_data"
                )
                where: list[str] = []
                parameters: list[int] = []
                if start is not None:
                    where.append("m.create_time >= ?")
                    parameters.append(int(start.timestamp()))
                if end is not None:
                    where.append("m.create_time <= ?")
                    parameters.append(int(end.timestamp()))
                where_sql = " WHERE " + " AND ".join(where) if where else ""
                rows = connection.execute(
                    f'SELECT {", ".join(selected)} FROM "{table}" m '
                    f"LEFT JOIN Name2Id n ON n.rowid = m.real_sender_id"
                    f"{where_sql} ORDER BY m.create_time ASC, m.local_id ASC",
                    parameters,
                ).fetchall()
                own_sender_id = self._own_sender_id(connection)
            messages.extend(
                self._message_from_row(conversation, row, own_sender_id, relative_path)
                for row in rows
            )
        return sorted(messages, key=lambda message: (message.timestamp, message.id))

    def close(self) -> None:
        self._images.close()
        self._databases.close()

    def set_image_key(self, image_key: bytes) -> None:
        self._images.close()
        self._images = DecryptedImageCache(self.account.attachment_dir, image_key)

    def _load_contacts(self) -> dict[str, str]:
        path = self._databases.get(r"contact\contact.db")
        with _connect(path) as connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info("contact")')}
            if "username" not in columns:
                raise SourceError("Unsupported WeChat contact database schema")
            fields = [field for field in ("username", "alias", "nick_name", "remark") if field in columns]
            rows = connection.execute(f'SELECT {", ".join(fields)} FROM contact').fetchall()
        contacts: dict[str, str] = {}
        for row in rows:
            values = dict(row)
            username = str(values.get("username") or "").strip()
            if not username:
                continue
            display = (
                str(values.get("remark") or "").strip()
                or str(values.get("nick_name") or "").strip()
                or str(values.get("alias") or "").strip()
                or username
            )
            contacts[username] = display
        return contacts

    def _load_conversations(self) -> list[Conversation]:
        path = self._databases.get(r"session\session.db")
        with _connect(path) as connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info("SessionTable")')}
            if "username" not in columns:
                raise SourceError("Unsupported WeChat session database schema")
            timestamp = "last_timestamp" if "last_timestamp" in columns else "0"
            rows = connection.execute(
                f"SELECT username, {timestamp} AS last_timestamp FROM SessionTable "
                "WHERE username IS NOT NULL AND username <> '' ORDER BY last_timestamp DESC"
            ).fetchall()
        conversations: list[Conversation] = []
        seen: set[str] = set()
        for row in rows:
            username = str(row["username"])
            if username in seen or username not in self._message_locations:
                continue
            seen.add(username)
            name = self._contacts.get(username) or _fallback_conversation_name(username)
            kind = ConversationKind.GROUP if "@chatroom" in username else ConversationKind.DIRECT
            conversations.append(Conversation(username, name, kind))
        return conversations

    def _index_message_tables(
        self,
        progress: ProgressCallback | None,
    ) -> dict[str, list[tuple[str, str]]]:
        locations: dict[str, list[tuple[str, str]]] = {}
        message_paths = _message_database_paths(self.account.db_dir)
        total = len(message_paths)
        for index, source in enumerate(message_paths, start=1):
            if progress:
                progress(index, total, f"正在索引消息分片 {index}/{total}")
            relative = str(source.relative_to(self.account.db_dir)).replace("/", "\\")
            db_path = self._databases.get(relative)
            with _connect(db_path) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    )
                }
                has_name_map = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='Name2Id'"
                ).fetchone()
                if not has_name_map:
                    continue
                usernames = connection.execute("SELECT user_name FROM Name2Id").fetchall()
            for row in usernames:
                username = str(row[0] or "").strip()
                if not username:
                    continue
                table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
                if table in tables:
                    locations.setdefault(username, []).append((relative, table))
        if not locations:
            raise SourceError("No readable WeChat message tables were found")
        return locations

    def _own_sender_id(self, connection: sqlite3.Connection) -> int | None:
        row = connection.execute("SELECT rowid FROM Name2Id WHERE user_name=?", (self._own_wxid,)).fetchone()
        return int(row[0]) if row else None

    def _message_from_row(
        self,
        conversation: Conversation,
        row: sqlite3.Row,
        own_sender_id: int | None,
        source_database: str,
    ) -> Message:
        raw_type = int(row["local_type"] or 0)
        message_type = raw_type & 0xFFFF
        content = _decode_content(row["message_content"], row["content_compression"])
        prefix_sender, content = _strip_group_prefix(content)
        local_id = int(row["local_id"] or 0)
        server_id = int(row["server_id"] or 0)
        sender_wxid = str(row["sender_wxid"] or prefix_sender or "")
        outgoing = own_sender_id is not None and int(row["real_sender_id"] or 0) == own_sender_id
        if outgoing:
            sender = "我"
        elif conversation.kind is ConversationKind.GROUP:
            sender = self._contacts.get(sender_wxid, sender_wxid or "群成员")
        else:
            sender = conversation.name

        model_type = MessageType.TEXT
        rendered_content = content
        audio_path: Path | None = None
        duration_ms: int | None = None
        transcript: str | None = None
        if message_type == 3:
            identifiers = _image_identifiers(row["packed_info_data"], content)
            image_path = self._images.resolve(identifiers)
            if image_path is not None:
                model_type = MessageType.IMAGE
                rendered_content = str(image_path)
            else:
                model_type = MessageType.SYSTEM
                rendered_content = "[图片]"
        elif message_type == 49:
            model_type = MessageType.FILE
            rendered_content = _type_49_content(content, raw_type)
        elif message_type == 34:
            model_type = MessageType.VOICE
            duration_ms = _voice_duration(content)
            audio_path = self._voices.resolve(
                source_database,
                conversation.id,
                local_id,
                server_id,
            )
            transcript = (
                self._voice_transcripts.load(audio_path, default_voice_model())
                if audio_path
                else None
            )
            rendered_content = transcript or voice_placeholder(duration_ms, audio_path is not None)
        elif message_type in MESSAGE_TYPE_LABELS:
            model_type = MessageType.SYSTEM
            rendered_content = MESSAGE_TYPE_LABELS[message_type]
        elif message_type != 1:
            model_type = MessageType.SYSTEM
            rendered_content = f"[消息类型 {message_type}]"
        elif not rendered_content:
            model_type = MessageType.SYSTEM
            rendered_content = "[空消息]"

        timestamp = int(row["create_time"] or 0)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        source_id = Path(source_database).stem
        message_id = str(server_id) if server_id else f"{conversation.id}:{source_id}:{local_id}"
        return Message(
            id=message_id,
            conversation_id=conversation.id,
            sender=sender,
            timestamp=datetime.fromtimestamp(timestamp),
            type=model_type,
            content=rendered_content,
            is_outgoing=outgoing,
            audio_path=audio_path,
            duration_ms=duration_ms,
            transcript=transcript,
        )


@contextmanager
def _connect(path: Path):
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _account_wxid(account: WeChat4Account) -> str:
    match = re.match(r"^(.*)_[0-9a-fA-F]{4}$", account.id)
    return match.group(1) if match else account.id


def _message_database_paths(db_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in (db_dir / "message").glob("message_*.db")
        if path.stem.removeprefix("message_").isdigit()
    )


def _fallback_conversation_name(username: str) -> str:
    if "@chatroom" in username:
        return f"群聊 {username.split('@', 1)[0]}"
    return username


def _decode_content(value: object, compression: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes):
        return str(value)
    data = value
    if int(compression or 0) == 4 or data.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            data = zstandard.ZstdDecompressor().decompress(data)
        except zstandard.ZstdError:
            return ""
    return data.decode("utf-8", errors="replace")


def _strip_group_prefix(content: str) -> tuple[str | None, str]:
    match = re.match(r"^([^\s:]{1,80}):(?:\n| )", content)
    if not match:
        return None, content
    return match.group(1), content[match.end():]


def _image_identifiers(*values: object) -> list[str]:
    seen: set[str] = set()
    identifiers: list[str] = []
    pattern = re.compile(rb"(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
    for value in values:
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, str):
            data = value.encode("utf-8", errors="ignore")
        elif isinstance(value, bytes):
            data = value
        else:
            continue
        for match in pattern.finditer(data):
            normalized = match.group(0).decode("ascii").casefold()
            if normalized not in seen:
                seen.add(normalized)
                identifiers.append(normalized)
    return identifiers


def _type_49_content(content: str, raw_type: int) -> str:
    subtype = raw_type >> 32
    title = _xml_value(content, "title")
    if subtype == 57:
        quoted_name = _xml_value(content, "displayname")
        quoted_content = _xml_value(content, "content")
        suffix = f"（引用 {quoted_name}: {quoted_content[:80]}）" if quoted_name else ""
        return (title or "[引用消息]") + suffix
    labels = {
        1: "链接",
        3: "音乐",
        4: "视频链接",
        5: "文件",
        6: "小程序",
        8: "位置",
        17: "实时位置",
        19: "聊天记录",
        21: "小程序",
        33: "小程序",
        36: "链接",
    }
    label = labels.get(subtype, "文件/链接")
    return f"[{label}] {title}".strip()


def _xml_value(content: str, tag: str) -> str:
    if not content:
        return ""
    try:
        root = ElementTree.fromstring(content)
        node = root.find(f".//{tag}")
        if node is not None and node.text:
            return html.unescape(node.text).strip()
    except ElementTree.ParseError:
        pass
    match = re.search(fr"<{tag}>([\s\S]*?)</{tag}>", content, re.IGNORECASE)
    return html.unescape(match.group(1)).strip() if match else ""


def _voice_duration(content: str) -> int | None:
    if not content:
        return None
    try:
        root = ElementTree.fromstring(content)
        node = root.find(".//voicemsg")
        value = node.attrib.get("voicelength") if node is not None else None
    except ElementTree.ParseError:
        match = re.search(r'<voicemsg\b[^>]*\bvoicelength=["\'](\d+)["\']', content, re.IGNORECASE)
        value = match.group(1) if match else None
    try:
        duration = int(value) if value else 0
    except ValueError:
        return None
    return duration if duration > 0 else None
