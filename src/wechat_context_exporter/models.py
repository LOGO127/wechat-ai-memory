from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class ConversationKind(str, Enum):
    DIRECT = "direct"
    GROUP = "group"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    VOICE = "voice"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    name: str
    kind: ConversationKind = ConversationKind.DIRECT

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Conversation id cannot be empty")
        if not self.name.strip():
            raise ValueError("Conversation name cannot be empty")


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    sender: str
    timestamp: datetime
    type: MessageType
    content: str
    is_outgoing: bool = False
    reply_to: str | None = None
    audio_path: Path | None = None
    duration_ms: int | None = None
    transcript: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Message id cannot be empty")
        if not self.conversation_id.strip():
            raise ValueError("Message conversation_id cannot be empty")
        if not self.sender.strip():
            raise ValueError("Message sender cannot be empty")
        if self.type in {MessageType.TEXT, MessageType.IMAGE, MessageType.FILE, MessageType.VOICE} and not self.content:
            raise ValueError(f"{self.type.value} message content cannot be empty")

    @property
    def image_path(self) -> Path | None:
        return Path(self.content) if self.type is MessageType.IMAGE else None

    @property
    def voice_path(self) -> Path | None:
        return self.audio_path if self.type is MessageType.VOICE else None
