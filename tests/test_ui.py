from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QPoint, QSettings
from PySide6.QtWidgets import QApplication, QLabel

from wechat_context_exporter.models import Message, MessageType
from wechat_context_exporter.ui import main_window
from wechat_context_exporter.sources import JsonChatSource


def test_workspace_always_starts_with_local_wechat_even_after_json_was_used(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("sourceMode", "json")
    settings.setValue("jsonSourcePath", str((Path.cwd() / "examples" / "demo_chat.json").resolve()))
    monkeypatch.setattr(main_window, "QSettings", lambda *_args: settings)
    monkeypatch.setattr(main_window, "discover_wechat4_accounts", lambda: [])

    window = main_window.MainWindow()
    app.processEvents()

    assert window.source_mode.currentData() == "wechat"
    assert window.source_label.text() == "账户目录"
    assert window.load_button.text() == "连接微信"
    assert window.image_key_button.isVisibleTo(window)
    window.close()


def test_conversation_picker_supports_case_insensitive_contains_search(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "discover_wechat4_accounts", lambda: [])
    window = main_window.MainWindow()
    window.conversation_combo.addItem("ECO 项目讨论群", "eco")
    window.conversation_combo.addItem("产品发布", "release")
    window.conversation_combo.addItem("Alice", "alice")

    completer = window.conversation_combo.completer()
    assert len(window.conversation_combo.lineEdit().actions()) == 1
    completer.setCompletionPrefix("项目")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "ECO 项目讨论群"
    completer.setCompletionPrefix("ali")
    assert completer.completionCount() == 1
    assert completer.currentCompletion() == "Alice"

    window.conversation_combo.setCurrentIndex(0)
    window._conversation_search_edited("发布")
    assert window.conversation_combo.currentIndex() == -1
    assert window.conversation_combo.currentText() == "发布"
    window._conversation_completion_selected("产品发布")
    assert window.conversation_combo.currentData() == "release"
    window.close()


def test_date_range_calendar_selection_and_ordering(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "discover_wechat4_accounts", lambda: [])
    window = main_window.MainWindow()
    window.start_date.setDate(QDate(2026, 8, 10))
    window.end_date.setDate(QDate(2026, 8, 20))

    menu, calendar = window._create_calendar_menu(window.start_date)
    calendar.clicked.emit(QDate(2026, 8, 12))
    assert window.start_date.date() == QDate(2026, 8, 12)
    assert not menu.isVisible()

    window.start_date.setDate(QDate(2026, 8, 25))
    assert window.end_date.date() == QDate(2026, 8, 25)
    window.end_date.setDate(QDate(2026, 8, 5))
    assert window.start_date.date() == QDate(2026, 8, 5)
    assert not window.start_calendar_button.icon().isNull()
    assert not window.end_calendar_button.icon().isNull()
    window.close()


def test_memory_workspace_search_and_metrics(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window, "discover_wechat4_accounts", lambda: [])
    window = main_window.MainWindow()
    window._messages = [
        Message("1", "chat", "张三", datetime(2026, 8, 21, 9), MessageType.TEXT, "workflow 完成"),
        Message("2", "chat", "李四", datetime(2026, 8, 22, 9), MessageType.IMAGE, "result.png"),
    ]
    window.start_date.setDate(QDate(2026, 8, 21))
    window.end_date.setDate(QDate(2026, 8, 22))
    window._refresh_preview()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "微信 AI 记忆库"
    assert not window.windowIcon().isNull()
    assert window.source_edit.objectName() == "sourcePathField"
    assert window.output_edit.objectName() == "outputPathField"
    assert window.minimumHeight() == 760
    assert window.source_mode.geometry().bottom() < window.source_label.geometry().top()
    assert window.source_edit.geometry().bottom() < window.load_button.geometry().top()
    assert window.preview_table.rowCount() == 2
    assert window.message_metric.text() == "2"
    assert window.image_metric.text() == "1"
    assert window.day_metric.text() == "2"
    for metric in (window.message_metric, window.image_metric, window.day_metric):
        assert metric.geometry().bottom() < metric.parentWidget().height()
    metric_block = window.message_metric.parentWidget()
    caption = metric_block.findChild(QLabel, "metricCaption")
    caption_bottom = caption.mapTo(window, QPoint(0, caption.height())).y()
    archive_top = window.archive_section.mapTo(window, QPoint(0, 0)).y()
    assert archive_top - caption_bottom >= 12

    window.search_edit.setText("workflow")
    app.processEvents()

    assert window.preview_table.rowCount() == 1
    assert window.message_metric.text() == "1"
    window._image_reading_enabled = True
    window._messages_loaded(window._messages)
    assert window.status_label.text() == "图片读取已启用 · 消息读取完成"
    assert window.preview_table.rowCount() == 1
    window.close()


def test_gui_loads_json_and_exports_the_visible_search_results(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda *_args: settings)
    monkeypatch.setattr(main_window, "discover_wechat4_accounts", lambda: [])
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(main_window.QMessageBox, "critical", lambda *_args: None)
    window = main_window.MainWindow()

    window.source_mode.setCurrentIndex(window.source_mode.findData("json"))
    window.source_edit.setText(str((Path.cwd() / "examples" / "demo_chat.json").resolve()))
    window._load_source()
    _wait_until(app, lambda: window._source is not None)
    _wait_until(app, lambda: window._message_worker is not None and not window._message_worker.isRunning())
    app.processEvents()

    assert window.preview_table.rowCount() == 8
    file_rows = [
        window.preview_table.item(row, 3).text()
        for row in range(window.preview_table.rowCount())
        if window.preview_table.item(row, 2).text() == "文件"
    ]
    assert file_rows == ["experiment_run_042.log"]
    window.search_edit.setText("随机种子")
    app.processEvents()
    assert window.preview_table.rowCount() == 1

    output = tmp_path / "filtered.pdf"
    window.output_edit.setText(str(output))
    window.companions_check.setChecked(True)
    window._start_export()
    _wait_until(app, lambda: window._last_result is not None)
    app.processEvents()

    assert output.is_file()
    exported = JsonChatSource(output.with_suffix(".json")).get_messages("eco-project")
    assert [message.id for message in exported] == ["m006"]
    assert window.status_label.text() == "1 页 · 1 条消息"
    window.close()


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out while waiting for Qt background work")
        app.processEvents()
        time.sleep(0.01)
