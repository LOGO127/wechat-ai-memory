from __future__ import annotations

import argparse
import sys
from datetime import datetime, time
from pathlib import Path

from .service import ExportOptions, ExportService
from .sources import JsonChatSource, SourceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat-context-exporter",
        description="Build an agent-readable memory archive from a local JSON chat source.",
    )
    parser.add_argument("--source", required=True, type=Path, help="Path to a version 1 chat JSON file")
    parser.add_argument("--conversation", help="Conversation id; omit to list available conversations")
    parser.add_argument("--output", type=Path, help="Destination PDF path")
    parser.add_argument("--start", type=_parse_start, help="Inclusive ISO 8601 start date/time")
    parser.add_argument("--end", type=_parse_end, help="Inclusive ISO 8601 end date/time")
    parser.add_argument("--no-image-pages", action="store_true", help="Do not insert full-page image attachments")
    parser.add_argument("--pages-dir", type=Path, help="Keep the rendered PNG pages in this directory")
    parser.add_argument("--markdown", type=Path, help="Also write a Markdown transcript")
    parser.add_argument("--json", dest="json_output", type=Path, help="Also write normalized filtered JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = JsonChatSource(args.source)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    conversations = source.list_conversations()
    if not args.conversation:
        print("Available conversations:")
        for conversation in conversations:
            count = len(source.get_messages(conversation.id))
            print(f"  {conversation.id}\t{conversation.name}\t{count} messages")
        return 0
    if not args.output:
        print("error: --output is required when --conversation is set", file=sys.stderr)
        return 2

    options = ExportOptions(
        conversation_id=args.conversation,
        output_pdf=args.output,
        start=args.start,
        end=args.end,
        include_image_pages=not args.no_image_pages,
        pages_dir=args.pages_dir,
        markdown_path=args.markdown,
        json_path=args.json_output,
    )
    try:
        result = ExportService().export(source, options, _print_progress)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Created {result.pdf_path} ({result.page_count} pages, "
        f"{result.message_count} messages, {result.image_page_count} image pages)"
    )
    return 0


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO 8601 date/time: {value}") from exc


def _parse_start(value: str) -> datetime:
    parsed = _parse_datetime(value)
    return datetime.combine(parsed.date(), time.min) if len(value) == 10 else parsed


def _parse_end(value: str) -> datetime:
    parsed = _parse_datetime(value)
    return datetime.combine(parsed.date(), time.max) if len(value) == 10 else parsed


def _print_progress(current: int, total: int, label: str) -> None:
    print(f"[{current}/{total}] {label}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
