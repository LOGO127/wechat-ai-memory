from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from .models import Conversation, Message, MessageType


def export_markdown(conversation: Conversation, messages: Iterable[Message], output_path: str | Path) -> Path:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {conversation.name}", "", f"Conversation ID: `{conversation.id}`", ""]
    current_date = None
    for message in messages:
        if current_date != message.timestamp.date():
            current_date = message.timestamp.date()
            lines.extend([f"## {current_date:%Y-%m-%d}", ""])
        heading = f"**{message.sender}** · {message.timestamp:%H:%M}"
        lines.extend([heading, ""])
        if message.type is MessageType.IMAGE:
            target = quote(Path(message.content).as_posix(), safe="/:._-~")
            lines.append(f"![Image attachment]({target})")
        elif message.type is MessageType.FILE:
            lines.append(f"File attachment: `{message.content}`")
        elif message.type is MessageType.VOICE:
            duration = f" ({max(1, round(message.duration_ms / 1000))}s)" if message.duration_ms else ""
            lines.append(f"Voice transcript{duration}: {message.content}")
        elif message.type is MessageType.SYSTEM:
            lines.append(f"_{message.content}_")
        else:
            lines.append(message.content)
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def export_json(conversation: Conversation, messages: Iterable[Message], output_path: str | Path) -> Path:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "conversations": [
            {
                "id": conversation.id,
                "name": conversation.name,
                "kind": conversation.kind.value,
                "messages": [
                    {
                        "id": message.id,
                        "sender": message.sender,
                        "timestamp": message.timestamp.isoformat(),
                        "type": message.type.value,
                        "content": message.content,
                        "is_outgoing": message.is_outgoing,
                        **({"reply_to": message.reply_to} if message.reply_to else {}),
                        **({"audio_path": str(message.audio_path)} if message.audio_path else {}),
                        **({"duration_ms": message.duration_ms} if message.duration_ms is not None else {}),
                        **({"transcript": message.transcript} if message.transcript else {}),
                    }
                    for message in messages
                ],
            }
        ],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
