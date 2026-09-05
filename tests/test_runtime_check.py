from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import package_runtime_smoke
from scripts.package_runtime_smoke import create_fixtures
from wechat_context_exporter import runtime_check


def test_runtime_check_decodes_synthetic_media_and_runs_native_speech(tmp_path) -> None:
    fixtures = tmp_path / "fixtures"
    create_fixtures(fixtures)
    report = tmp_path / "runtime-report.json"

    assert runtime_check.main([str(fixtures), str(report)]) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["checks"]["wxgf"]["pixels_equal"] is True
    assert payload["checks"]["vad"]["frames"] == 32


def test_runtime_check_reports_each_failure_and_continues(tmp_path, monkeypatch) -> None:
    def missing_runtime(_fixtures):
        raise ImportError("missing native runtime")

    monkeypatch.setattr(runtime_check, "_check_speech", missing_runtime)
    monkeypatch.setattr(runtime_check, "_check_vad", lambda _: {"frames": 32})
    report = tmp_path / "reports" / "runtime.json"

    assert runtime_check.verify_runtime(tmp_path / "missing", report) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["checks"]["wxgf"]["error_type"] == "FileNotFoundError"
    assert payload["checks"]["silk_audio"]["error_type"] == "FileNotFoundError"
    assert payload["checks"]["speech_runtime"]["error"] == "missing native runtime"
    assert payload["checks"]["vad"]["ok"] is True


def test_packaged_smoke_cannot_accept_a_stale_success_report(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "app.exe"
    executable.touch()
    report = tmp_path / "runtime.json"
    report.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(package_runtime_smoke, "create_fixtures", lambda _: None)
    monkeypatch.setattr(
        package_runtime_smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr=b"missing DLL"),
    )

    with pytest.raises(RuntimeError, match="produced no report.*missing DLL"):
        package_runtime_smoke.run_smoke(executable, report)
