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
                    id=str(item["id"]),
                    name=str(item["name"]),
                    kind=ConversationKind(item.get("kind", "direct")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError(f"Invalid conversation at index {index}: {exc}") from exc
            if conversation.id in seen_conversations:
                raise SourceError(f"Duplicate conversation id: {conversation.id}")
            seen_conversations.add(conversation.id)
            self._conversations.append(conversation)

            parsed: list[Message] = []
            items = item.get("messages", [])
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
            timestamp = _parse_timestamp(str(raw["timestamp"]))
            message_type = MessageType(raw.get("type", "text"))
            content = str(raw.get("content", ""))
            if message_type is MessageType.IMAGE:
                content = str((self.path.parent / content).resolve()) if not Path(content).is_absolute() else content
            return Message(
                id=str(raw["id"]),
                conversation_id=conversation_id,
                sender=str(raw["sender"]),
                timestamp=timestamp,
                type=message_type,
                content=content,
                is_outgoing=bool(raw.get("is_outgoing", False)),
                reply_to=str(raw["reply_to"]) if raw.get("reply_to") is not None else None,
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

