from __future__ import annotations

from datetime import datetime, timedelta

from wechat_context_exporter.models import Conversation, Message, MessageType
from wechat_context_exporter.rendering import ChatRenderer


def test_pagination_preserves_all_messages_without_oversized_pages():
    conversation = Conversation("c1", "Pagination test")
    messages = [
        Message(
            id=f"m{index:03d}",
            conversation_id="c1",
            sender="Alice" if index % 2 else "Bob",
            timestamp=datetime(2026, 8, 1, 8) + timedelta(minutes=index),
            type=MessageType.TEXT,
            content=("A bounded message with enough text to exercise wrapping. " * 4).strip(),
            is_outgoing=index % 2 == 0,
        )
        for index in range(48)
    ]

    renderer = ChatRenderer()
    pages = renderer.render(conversation, messages)
    rendered_ids = {message_id for page in pages for message_id in page.message_ids}
    assert len(pages) > 1
    assert rendered_ids == {message.id for message in messages}
    assert all(page.image.size == (renderer.config.width, renderer.config.height) for page in pages)

