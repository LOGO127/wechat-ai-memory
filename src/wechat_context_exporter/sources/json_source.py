from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Conversation, ConversationKind, Message, MessageType
from .base import SourceError


class JsonChatSource:
    """Read the stable, documented JSON interchange format used by the app."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._conversations: list[Conversation] = []
        self._messages: dict[str, list[Message]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SourceError(f"JSON source not found: {self.path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceError(f"Cannot read JSON source: {exc}") from exc

        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise SourceError("JSON source must be an object with version: 1")
        conversations = raw.get("conversations")
        if not isinstance(conversations, list):
            raise SourceError("JSON source must contain a conversations array")

        seen_conversations: set[str] = set()
        seen_messages: set[str] = set()
        for index, item in enumerate(conversations):
            if not isinstance(item, dict):
                raise SourceError(f"Conversation at index {index} must be an object")
            try:
                conversation = Conversation(
                    id=_required_string(item, "id"),
                    name=_required_string(item, "name"),
                    kind=ConversationKind(_optional_string(item, "kind", "direct")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError(f"Invalid conversation at index {index}: {exc}") from exc
            if conversation.id in seen_conversations:
                raise SourceError(f"Duplicate conversation id: {conversation.id}")
            seen_conversations.add(conversation.id)
            self._conversations.append(conversation)

            parsed: list[Message] = []
            items = item.get("messages")
            if not isinstance(items, list):
                raise SourceError(f"messages for {conversation.id} must be an array")
            for message_index, message_item in enumerate(items):
                message = self._parse_message(conversation.id, message_index, message_item)
                if message.id in seen_messages:
                    raise SourceError(f"Duplicate message id: {message.id}")
                seen_messages.add(message.id)
                parsed.append(message)
            self._messages[conversation.id] = sorted(parsed, key=lambda message: message.timestamp)

    def _parse_message(self, conversation_id: str, index: int, raw: Any) -> Message:
        if not isinstance(raw, dict):
            raise SourceError(f"Message {index} in {conversation_id} must be an object")
        try:
            timestamp = _parse_timestamp(_required_string(raw, "timestamp"))
            message_type = MessageType(_optional_string(raw, "type", "text"))
            content = _required_string(raw, "content")
            if message_type in {MessageType.IMAGE, MessageType.FILE} and content:
                content = str((self.path.parent / content).resolve()) if not Path(content).is_absolute() else content
            audio_path = raw.get("audio_path")
            if audio_path is not None and not isinstance(audio_path, str):
                raise TypeError("audio_path must be a string or null")
            if audio_path:
                audio_path = str(
                    (self.path.parent / audio_path).resolve()
                    if not Path(audio_path).is_absolute()
                    else Path(audio_path)
                )
            duration_ms = raw.get("duration_ms")
            if duration_ms is not None and (not isinstance(duration_ms, int) or duration_ms < 0):
                raise TypeError("duration_ms must be a non-negative integer or null")
            transcript = raw.get("transcript")
            if transcript is not None and not isinstance(transcript, str):
                raise TypeError("transcript must be a string or null")
            is_outgoing = raw.get("is_outgoing", False)
            if not isinstance(is_outgoing, bool):
                raise TypeError("is_outgoing must be a boolean")
            reply_to = raw.get("reply_to")
            if reply_to is not None and not isinstance(reply_to, str):
                raise TypeError("reply_to must be a string or null")
            return Message(
                id=_required_string(raw, "id"),
                conversation_id=conversation_id,
                sender=_required_string(raw, "sender"),
                timestamp=timestamp,
                type=message_type,
                content=content,
                is_outgoing=is_outgoing,
                reply_to=reply_to,
                audio_path=Path(audio_path) if audio_path else None,
                duration_ms=duration_ms,
                transcript=transcript,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f"Invalid message {index} in {conversation_id}: {exc}") from exc

    def list_conversations(self) -> list[Conversation]:
        return list(self._conversations)

    def get_messages(
        self,
        conversation_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Message]:
        if conversation_id not in self._messages:
            raise SourceError(f"Unknown conversation id: {conversation_id}")
        return [
            message
            for message in self._messages[conversation_id]
            if (start is None or message.timestamp >= start) and (end is None or message.timestamp <= end)
        ]


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(normalized)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone().replace(tzinfo=None)
        return timestamp
    except ValueError as exc:
        raise ValueError(f"timestamp must be ISO 8601, got {value!r}") from exc


def _required_string(raw: dict[str, Any], key: str) -> str:
    if key not in raw:
        raise KeyError(key)
    value = raw[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_string(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value
