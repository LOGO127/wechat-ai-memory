from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QPoint
from PySide6.QtWidgets import QApplication, QLabel

from wechat_context_exporter.models import Message, MessageType
from wechat_context_exporter.ui import main_window


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
    window.close()
