# Contributing

Thank you for helping improve WeChat AI Memory.

## Development

The local WeChat adapter targets Windows and WeChat 4.x. Create the project
environment and run the test suite with:

```powershell
py -3 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -e ".[gui,dev]"
.\.venv-gui\Scripts\python.exe -m pytest
```

Keep changes scoped and add focused tests for message parsing, database or
media compatibility, rendering, and user-facing workflows.

## Privacy Rules

- Never commit real chat databases, encryption keys, account identifiers, or exported conversations.
- Use `examples/demo_chat.json` and synthetic fixtures in tests.
- Redact usernames, paths, QR codes, and message content from screenshots and issue reports.
- Do not add telemetry or remote data transfer without an explicit opt-in design and review.

## Pull Requests

Describe the affected WeChat version, behavior before and after the change,
and the verification performed. Compatibility discoveries should include a
minimal synthetic fixture whenever possible.
