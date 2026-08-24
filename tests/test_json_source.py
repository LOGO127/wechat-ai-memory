from __future__ import annotations

import json
from datetime import datetime

import pytest

from wechat_context_exporter.models import ConversationKind, MessageType
from wechat_context_exporter.sources import JsonChatSource, SourceError


def test_source_parses_relative_images_and_filters_inclusively(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"not inspected by the source")
    payload = {
        "version": 1,
        "conversations": [
            {
                "id": "c1",
                "name": "Team",
                "kind": "group",
                "messages": [
                    {"id": "m2", "sender": "B", "timestamp": "2026-08-22T11:00:00", "type": "image", "content": "image.png"},
                    {"id": "m1", "sender": "A", "timestamp": "2026-08-21T10:00:00", "type": "text", "content": "hello"},
                ],
            }
        ],
    }
    source_path = tmp_path / "chat.json"
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    source = JsonChatSource(source_path)
    conversation = source.list_conversations()[0]
    assert conversation.kind is ConversationKind.GROUP
    messages = source.get_messages("c1", datetime(2026, 8, 21), datetime(2026, 8, 22, 11))
    assert [message.id for message in messages] == ["m1", "m2"]
    assert messages[1].type is MessageType.IMAGE
    assert messages[1].image_path == image.resolve()


def test_source_rejects_unknown_schema_version(tmp_path):
    source_path = tmp_path / "chat.json"
    source_path.write_text('{"version": 2, "conversations": []}', encoding="utf-8")
    with pytest.raises(SourceError, match="version: 1"):
        JsonChatSource(source_path)

