from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Conversation, Message


class SourceError(RuntimeError):
    """Raised when a chat source cannot be read or validated."""


class ChatSource(Protocol):
    def list_conversations(self) -> list[Conversation]: ...

    def get_messages(
        self,
        conversation_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Message]: ...

