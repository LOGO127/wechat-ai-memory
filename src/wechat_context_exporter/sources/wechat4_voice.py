from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from ..voice import app_data_dir
from .wechat4_crypto import DecryptedDatabaseCache


class WeChatVoiceCache:
    def __init__(
        self,
        databases: DecryptedDatabaseCache,
        account_id: str,
        root: Path | None = None,
    ) -> None:
        self._databases = databases
        account_hash = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
        self._root = (root or app_data_dir() / "voice-audio") / account_hash

    def resolve(
        self,
        message_database: str,
        conversation_id: str,
        local_id: int,
        server_id: int,
    ) -> Path | None:
        media_database = _media_database_path(message_database)
        if media_database is None:
            return None
        try:
            db_path = self._databases.get(media_database)
        except (FileNotFoundError, OSError, RuntimeError):
            return None
        try:
            connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            conversation_row = connection.execute(
                "SELECT rowid FROM Name2Id WHERE user_name=?",
                (conversation_id,),
            ).fetchone()
            if not conversation_row:
                return None
            chat_name_id = int(conversation_row[0])
            row = None
            if server_id:
                row = connection.execute(
                    "SELECT voice_data FROM VoiceInfo WHERE chat_name_id=? AND svr_id=? LIMIT 1",
                    (chat_name_id, server_id),
                ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT voice_data FROM VoiceInfo WHERE chat_name_id=? AND local_id=? LIMIT 1",
                    (chat_name_id, local_id),
                ).fetchone()
        except sqlite3.Error:
            return None
        finally:
            if "connection" in locals():
                connection.close()
        if not row or not row[0]:
            return None
        data = bytes(row[0])
        digest = hashlib.sha256(data).hexdigest()
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / f"{digest}.silk"
        if not target.is_file():
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        return target


def _media_database_path(message_database: str) -> str | None:
    normalized = message_database.replace("/", "\\")
    path = Path(normalized)
    name = path.name
    if not name.startswith("message_") or not name.endswith(".db"):
        return None
    return str(path.with_name("media_" + name.removeprefix("message_")))
