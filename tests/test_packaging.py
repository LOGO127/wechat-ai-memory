from pathlib import Path
import runpy
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def test_qt_hook_only_removes_unused_plugins(monkeypatch):
    plugins = [
        ("qt/plugins/platforms/qwindows.dll", "PySide6/plugins/platforms"),
        ("qt/plugins/imageformats/qsvg.dll", "PySide6/plugins/imageformats"),
        ("qt/plugins/iconengines/qsvgicon.dll", "PySide6/plugins/iconengines"),
        ("qt/plugins/imageformats/qjpeg.dll", "PySide6/plugins/imageformats"),
        ("qt/plugins/platforminputcontexts/QtVirtualKeyboardPlugin.dll", "PySide6/plugins/platforminputcontexts"),
        ("qt/plugins/imageformats/qpdf.dll", "PySide6/plugins/imageformats"),
    ]
    qt_hook = ModuleType("PyInstaller.utils.hooks.qt")
    qt_hook.add_qt6_dependencies = lambda _: (["PySide6.QtCore"], plugins, [("qt.qm", "translations")])
    monkeypatch.setitem(sys.modules, qt_hook.__name__, qt_hook)

    result = runpy.run_path(str(ROOT / "packaging/windows/hooks/hook-PySide6.QtGui.py"))

    assert result["binaries"] == plugins[:4]
    assert result["hiddenimports"] == ["PySide6.QtCore"]
    assert result["datas"] == [("qt.qm", "translations")]
