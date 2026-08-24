from __future__ import annotations

import tomllib
from pathlib import Path

from wechat_context_exporter import __version__


def test_package_and_windows_versions_match() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")

    assert project["project"]["version"] == __version__
    assert f"StringStruct(u'FileVersion', u'{__version__}')" in version_info
    assert f"StringStruct(u'ProductVersion', u'{__version__}')" in version_info
