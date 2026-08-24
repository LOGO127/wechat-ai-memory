from __future__ import annotations

from datetime import datetime, timedelta

import pytest

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
    assert renderer.config.dpi == 300
    assert all(page.image.size == renderer.config.pixel_size for page in pages)


def test_emoji_names_and_message_content_use_color_font_fallback():
    renderer = ChatRenderer()
    if renderer.fonts.emoji_path is None or renderer.fonts.emoji_path.name.casefold() != "seguiemj.ttf":
        pytest.skip("Windows color emoji font is not available")
    conversation = Conversation("c1", "🍉")
    message = Message(
        id="m1",
        conversation_id="c1",
        sender="🍉",
        timestamp=datetime(2026, 8, 24, 12),
        type=MessageType.TEXT,
        content="项目进展 🍉",
    )

    image = renderer.render(conversation, [message])[0].image
    red_pixels = sum(
        1
        for red, green, blue in image.getdata()
        if red > 160 and green < 120 and blue < 120
    )

    assert red_pixels > 100
