from __future__ import annotations

from wechat_context_exporter.cli import main
from wechat_context_exporter.sources import JsonChatSource


def test_cli_lists_conversations(capsys):
    assert main(["--source", "examples/demo_chat.json"]) == 0
    captured = capsys.readouterr()
    assert "eco-project" in captured.out
    assert "8 messages" in captured.out


def test_cli_exports_filtered_roundtrip_json(tmp_path):
    output = tmp_path / "filtered.pdf"
    normalized = tmp_path / "filtered.json"

    result = main(
        [
            "--source",
            "examples/demo_chat.json",
            "--conversation",
            "eco-project",
            "--query",
            "随机种子",
            "--output",
            str(output),
            "--json",
            str(normalized),
        ]
    )

    assert result == 0
    assert output.is_file()
    messages = JsonChatSource(normalized).get_messages("eco-project")
    assert [message.id for message in messages] == ["m006"]


def test_cli_rejects_reversed_date_range(tmp_path, capsys):
    result = main(
        [
            "--source",
            "examples/demo_chat.json",
            "--conversation",
            "eco-project",
            "--start",
            "2026-08-22",
            "--end",
            "2026-08-21",
            "--output",
            str(tmp_path / "invalid.pdf"),
        ]
    )

    assert result == 1
    assert "must not be after" in capsys.readouterr().err
