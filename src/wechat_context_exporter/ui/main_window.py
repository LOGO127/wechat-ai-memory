from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path

from PySide6.QtCore import QDate, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Message, MessageType
from ..rendering.fonts import FontBook
from ..service import ExportOptions, ExportResult, ExportService
from ..sources import (
    ChatSource,
    JsonChatSource,
    WeChat4LocalSource,
    discover_wechat4_accounts,
)
from ..sources.wechat4_crypto import extract_image_key

APP_NAME = "微信 AI 记忆库"
APP_ID = "LocalTools.WeChatAIMemory"


def application_icon() -> QIcon:
    asset_path = Path(__file__).resolve().parents[1] / "assets" / "app-icon.svg"
    return QIcon(str(asset_path))


def asset_icon(name: str) -> QIcon:
    return QIcon(str(Path(__file__).resolve().parents[1] / "assets" / name))


class SourceLoadWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, mode: str, path: str) -> None:
        super().__init__()
        self.mode = mode
        self.path = path

    def run(self) -> None:
        try:
            if self.mode == "wechat":
                source = WeChat4LocalSource(
                    self.path or None,
                    progress=self.progress.emit,
                    cancelled=self.isInterruptionRequested,
                )
            else:
                source = JsonChatSource(self.path)
        except Exception as exc:  # Qt worker boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(source)


class MessageLoadWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: ChatSource, conversation_id: str) -> None:
        super().__init__()
        self.source = source
        self.conversation_id = conversation_id

    def run(self) -> None:
        try:
            messages = self.source.get_messages(self.conversation_id)
        except Exception as exc:  # Qt worker boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(messages)


class ImageKeyWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: WeChat4LocalSource) -> None:
        super().__init__()
        self.source = source

    def run(self) -> None:
        try:
            key = extract_image_key(
                self.source.account.attachment_dir,
                self.progress.emit,
                self.isInterruptionRequested,
            )
            if key is None:
                raise RuntimeError("未找到图片密钥。请保持微信已登录；旧版微信可打开一张原图后重试。")
            self.source.set_image_key(key)
        except Exception as exc:  # Qt worker boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(key)


class ExportWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: ChatSource, options: ExportOptions) -> None:
        super().__init__()
        self.source = source
        self.options = options

    def run(self) -> None:
        try:
            result = ExportService().export(self.source, self.options, self.progress.emit)
        except Exception as exc:  # Qt worker boundary.
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


def _section_label(text: str, number: str) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    index = QLabel(number)
    index.setObjectName("sectionIndex")
    title = QLabel(text)
    title.setObjectName("sectionTitle")
    layout.addWidget(index)
    layout.addWidget(title)
    layout.addStretch(1)
    return widget


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


def _separator() -> QFrame:
    separator = QFrame()
    separator.setObjectName("separator")
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFixedHeight(1)
    return separator


def _metric(caption: str) -> tuple[QWidget, QLabel]:
    widget = QWidget()
    widget.setObjectName("metricBlock")
    widget.setFixedHeight(46)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(6, 3, 6, 3)
    layout.setSpacing(0)
    value = QLabel("0")
    value.setObjectName("metricValue")
    value.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label = QLabel(caption)
    label.setObjectName("metricCaption")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(value)
    layout.addWidget(label)
    return widget, value


class ConversationSearchDialog(QDialog):
    def __init__(
        self,
        choices: list[tuple[str, object]],
        selected_data: object | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("conversationSearchDialog")
        self.setWindowTitle("选择联系人或群聊")
        self.setModal(True)
        self.resize(430, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel("选择联系人或群聊")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("conversationDialogSearch")
        self.search_edit.setPlaceholderText("输入名称进行搜索")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.addAction(asset_icon("search.svg"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(self._filter_choices)
        layout.addWidget(self.search_edit)

        self.choice_list = QListWidget()
        self.choice_list.setObjectName("conversationChoiceList")
        self.choice_list.setAlternatingRowColors(True)
        self.choice_list.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.choice_list, 1)
        for name, data in choices:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.choice_list.addItem(item)
            if data == selected_data:
                self.choice_list.setCurrentItem(item)
        if self.choice_list.currentItem() is None and self.choice_list.count():
            self.choice_list.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.select_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.select_button.setText("选择")
        self.select_button.setObjectName("dialogPrimary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search_edit.setFocus()

    def _filter_choices(self, query: str) -> None:
        folded = query.strip().casefold()
        first_visible: QListWidgetItem | None = None
        for index in range(self.choice_list.count()):
            item = self.choice_list.item(index)
            visible = not folded or folded in item.text().casefold()
            item.setHidden(not visible)
            if visible and first_visible is None:
                first_visible = item
        current = self.choice_list.currentItem()
        if current is None or current.isHidden():
            self.choice_list.setCurrentItem(first_visible)
        self.select_button.setEnabled(first_visible is not None)

    def _accept_selection(self) -> None:
        current = self.choice_list.currentItem()
        if current is not None and not current.isHidden():
            self.accept()

    def selected_data(self) -> object | None:
        current = self.choice_list.currentItem()
        return current.data(Qt.ItemDataRole.UserRole) if current is not None else None


class DatePickerDialog(QDialog):
    def __init__(
        self,
        title: str,
        selected: QDate,
        minimum: QDate,
        maximum: QDate,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("datePickerDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(390, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)

        navigation = QHBoxLayout()
        navigation.setSpacing(8)
        self.previous_button = QToolButton()
        self.next_button = QToolButton()
        for button in (self.previous_button, self.next_button):
            button.setObjectName("calendarNavButton")
            button.setFixedSize(34, 34)
        self.previous_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.month_label = QLabel()
        self.month_label.setObjectName("calendarMonthLabel")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.month_label, 1)
        navigation.addWidget(self.next_button)
        layout.addLayout(navigation)

        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("rangeCalendar")
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setGridVisible(False)
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setMinimumDate(minimum)
        self.calendar.setMaximumDate(maximum)
        self.calendar.setSelectedDate(selected)
        self.calendar.setCurrentPage(selected.year(), selected.month())
        weekend = QTextCharFormat()
        weekend.setForeground(QColor("#c45d16"))
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend)
        self.calendar.currentPageChanged.connect(self._update_month)
        self.calendar.activated.connect(lambda _date: self.accept())
        layout.addWidget(self.calendar, 1)

        footer = QHBoxLayout()
        self.today_button = QPushButton("今天")
        cancel_button = QPushButton("取消")
        confirm_button = QPushButton("确定")
        confirm_button.setObjectName("dialogPrimary")
        footer.addWidget(self.today_button)
        footer.addStretch(1)
        footer.addWidget(cancel_button)
        footer.addWidget(confirm_button)
        layout.addLayout(footer)

        self.previous_button.clicked.connect(lambda: self._change_month(-1))
        self.next_button.clicked.connect(lambda: self._change_month(1))
        self.today_button.clicked.connect(self._select_today)
        cancel_button.clicked.connect(self.reject)
        confirm_button.clicked.connect(self.accept)
        self._update_month(selected.year(), selected.month())

    def _change_month(self, offset: int) -> None:
        current = QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1)
        target = current.addMonths(offset)
        self.calendar.setCurrentPage(target.year(), target.month())

    def _select_today(self) -> None:
        today = QDate.currentDate()
        if self.calendar.minimumDate() <= today <= self.calendar.maximumDate():
            self.calendar.setSelectedDate(today)
            self.calendar.setCurrentPage(today.year(), today.month())

    def _update_month(self, year: int, month: int) -> None:
        self.month_label.setText(f"{year} 年 {month} 月")
        current = QDate(year, month, 1)
        minimum = QDate(self.calendar.minimumDate().year(), self.calendar.minimumDate().month(), 1)
        maximum = QDate(self.calendar.maximumDate().year(), self.calendar.maximumDate().month(), 1)
        self.previous_button.setEnabled(current > minimum)
        self.next_button.setEnabled(current < maximum)

    def selected_date(self) -> QDate:
        return self.calendar.selectedDate()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(application_icon())
        self.resize(1280, 820)
        self.setMinimumSize(1020, 760)
        self._source: ChatSource | None = None
        self._messages: list[Message] = []
        self._source_worker: SourceLoadWorker | None = None
        self._message_worker: MessageLoadWorker | None = None
        self._image_worker: ImageKeyWorker | None = None
        self._export_worker: ExportWorker | None = None
        self._last_result: ExportResult | None = None
        self._image_reading_enabled = False
        self._closing = False
        self._settings = QSettings("LocalTools", "WeChatContextExporter")
        self._build_ui()
        self._restore_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(24, 14, 24, 14)
        top_layout.setSpacing(12)
        brand_mark = QLabel()
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(38, 38)
        brand_mark.setPixmap(application_icon().pixmap(38, 38))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        title = QLabel("微信 AI 记忆库")
        title.setObjectName("pageTitle")
        edition = QLabel("WECHAT MEMORY ARCHIVE")
        edition.setObjectName("editionLabel")
        brand_text.addWidget(title)
        brand_text.addWidget(edition)
        top_layout.addWidget(brand_mark)
        top_layout.addLayout(brand_text)
        top_layout.addStretch(1)
        privacy_label = QLabel("本地只读")
        privacy_label.setObjectName("privacyBadge")
        self.connection_badge = QLabel("未连接")
        self.connection_badge.setObjectName("connectionBadge")
        self.connection_badge.setProperty("state", "idle")
        top_layout.addWidget(privacy_label)
        top_layout.addWidget(self.connection_badge)
        root_layout.addWidget(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(318)
        sidebar.setMaximumWidth(390)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        form_scroll = QScrollArea()
        form_scroll.setObjectName("sidebarScroll")
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_form = QWidget()
        sidebar_form.setObjectName("sidebarForm")
        side_layout = QVBoxLayout(sidebar_form)
        side_layout.setContentsMargins(22, 10, 16, 4)
        side_layout.setSpacing(4)
        side_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        side_layout.addWidget(_section_label("数据源", "01"))
        side_layout.addWidget(_field_label("来源类型"))
        self.source_mode = QComboBox()
        self.source_mode.addItem("本机微信", "wechat")
        self.source_mode.addItem("JSON 文件", "json")
        self.source_mode.currentIndexChanged.connect(self._source_mode_changed)
        side_layout.addWidget(self.source_mode)
        self.source_label = QLabel("账户目录")
        self.source_label.setObjectName("fieldLabel")
        side_layout.addWidget(self.source_label)
        self.source_edit = QLineEdit()
        self.source_edit.setObjectName("sourcePathField")
        self.source_edit.returnPressed.connect(self._load_source)
        self.source_browse_button = QPushButton()
        self.source_browse_button.setObjectName("iconButton")
        self.source_browse_button.setFixedSize(40, 40)
        self.source_browse_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.source_browse_button.setToolTip("选择数据位置")
        self.source_browse_button.clicked.connect(self._browse_source)
        source_path_layout = QHBoxLayout()
        source_path_layout.setSpacing(8)
        source_path_layout.addWidget(self.source_edit, 1)
        source_path_layout.addWidget(self.source_browse_button)
        side_layout.addLayout(source_path_layout)
        self.load_button = QPushButton("连接微信")
        self.load_button.setObjectName("connectButton")
        self.load_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        self.load_button.clicked.connect(self._load_source)
        self.image_key_button = QPushButton("读取图片")
        self.image_key_button.setObjectName("secondaryButton")
        self.image_key_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.image_key_button.setEnabled(False)
        self.image_key_button.setToolTip("从已登录的微信进程读取图片解密密钥")
        self.image_key_button.clicked.connect(self._load_image_key)
        connection_actions = QHBoxLayout()
        connection_actions.setSpacing(8)
        connection_actions.addWidget(self.load_button, 1)
        connection_actions.addWidget(self.image_key_button, 1)
        side_layout.addLayout(connection_actions)

        side_layout.addWidget(_separator())
        side_layout.addWidget(_section_label("记忆范围", "02"))
        side_layout.addWidget(_field_label("联系人 / 群聊"))
        self.conversation_combo = QComboBox()
        self.conversation_combo.setPlaceholderText("选择联系人或群聊")
        self.conversation_combo.currentIndexChanged.connect(self._conversation_changed)
        self.conversation_search_button = QToolButton()
        self.conversation_search_button.setObjectName("scopeSearchButton")
        self.conversation_search_button.setIcon(asset_icon("search.svg"))
        self.conversation_search_button.setToolTip("搜索联系人或群聊")
        self.conversation_search_button.setFixedSize(40, 40)
        self.conversation_search_button.setEnabled(False)
        self.conversation_search_button.clicked.connect(self._open_conversation_search)
        conversation_layout = QHBoxLayout()
        conversation_layout.setSpacing(8)
        conversation_layout.addWidget(self.conversation_combo, 1)
        conversation_layout.addWidget(self.conversation_search_button)
        side_layout.addLayout(conversation_layout)
        side_layout.addWidget(_field_label("时间范围"))
        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        for date_edit in (self.start_date, self.end_date):
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setDate(QDate.currentDate())
            date_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            date_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            date_edit.setObjectName("dateInput")
        self.start_date.dateChanged.connect(self._start_date_changed)
        self.end_date.dateChanged.connect(self._end_date_changed)

        self.start_calendar_button = QToolButton()
        self.end_calendar_button = QToolButton()
        for button, tooltip in (
            (self.start_calendar_button, "从日历选择开始日期"),
            (self.end_calendar_button, "从日历选择结束日期"),
        ):
            button.setObjectName("calendarButton")
            button.setIcon(asset_icon("calendar-days.svg"))
            button.setToolTip(tooltip)
            button.setFixedSize(34, 40)
        self.start_calendar_button.clicked.connect(
            lambda: self._show_date_calendar(self.start_date, self.start_calendar_button)
        )
        self.end_calendar_button.clicked.connect(
            lambda: self._show_date_calendar(self.end_date, self.end_calendar_button)
        )

        date_layout = QHBoxLayout()
        date_layout.setSpacing(12)
        for caption, date_edit, button in (
            ("开始", self.start_date, self.start_calendar_button),
            ("结束", self.end_date, self.end_calendar_button),
        ):
            picker_layout = QVBoxLayout()
            picker_layout.setSpacing(3)
            picker_label = QLabel(caption)
            picker_label.setObjectName("dateCaption")
            picker_layout.addWidget(picker_label)
            field_layout = QHBoxLayout()
            field_layout.setSpacing(0)
            field_layout.addWidget(date_edit, 1)
            field_layout.addWidget(button)
            picker_layout.addLayout(field_layout)
            date_layout.addLayout(picker_layout, 1)
        side_layout.addLayout(date_layout)

        date_metrics_gap = QWidget()
        date_metrics_gap.setFixedHeight(8)
        side_layout.addWidget(date_metrics_gap)
        self.metrics_panel = QFrame()
        self.metrics_panel.setObjectName("metricsPanel")
        self.metrics_panel.setFixedHeight(48)
        metrics_layout = QHBoxLayout(self.metrics_panel)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(0)
        message_metric, self.message_metric = _metric("消息")
        image_metric, self.image_metric = _metric("图片")
        day_metric, self.day_metric = _metric("活跃日")
        for index, metric in enumerate((message_metric, image_metric, day_metric)):
            if index:
                divider = QFrame()
                divider.setObjectName("metricDivider")
                divider.setFixedWidth(1)
                metrics_layout.addWidget(divider)
            metrics_layout.addWidget(metric, 1)
        side_layout.addWidget(self.metrics_panel)

        metrics_archive_gap = QWidget()
        metrics_archive_gap.setFixedHeight(12)
        side_layout.addWidget(metrics_archive_gap)
        self.archive_section = _section_label("归档设置", "03")
        side_layout.addWidget(self.archive_section)
        side_layout.addWidget(_field_label("PDF 文件"))
        self.output_edit = QLineEdit()
        self.output_edit.setObjectName("outputPathField")
        self.output_edit.setPlaceholderText("选择保存位置")
        browse_output = QPushButton()
        browse_output.setObjectName("iconButton")
        browse_output.setFixedSize(40, 40)
        browse_output.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        browse_output.setToolTip("选择 PDF 保存位置")
        browse_output.clicked.connect(self._browse_output)
        output_layout = QHBoxLayout()
        output_layout.setSpacing(8)
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(browse_output)
        side_layout.addLayout(output_layout)
        self.image_pages_check = QCheckBox("高清图片独立成页")
        self.image_pages_check.setChecked(True)
        self.keep_pages_check = QCheckBox("保留渲染 PNG")
        self.companions_check = QCheckBox("生成 Markdown 与 JSON")
        side_layout.addWidget(self.image_pages_check)
        side_layout.addWidget(self.keep_pages_check)
        side_layout.addWidget(self.companions_check)
        side_layout.addStretch(1)

        self.open_folder_button = QPushButton("打开归档目录")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        self.export_button = QPushButton("生成记忆档案")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._start_export)
        form_scroll.setWidget(sidebar_form)
        sidebar_layout.addWidget(form_scroll, 1)
        sidebar_actions = QWidget()
        sidebar_actions.setObjectName("sidebarActions")
        sidebar_actions_layout = QVBoxLayout(sidebar_actions)
        sidebar_actions_layout.setContentsMargins(22, 8, 22, 10)
        sidebar_actions_layout.setSpacing(5)
        sidebar_actions_layout.addWidget(self.open_folder_button)
        sidebar_actions_layout.addWidget(self.export_button)
        sidebar_layout.addWidget(sidebar_actions)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        preview_layout = QVBoxLayout(workspace)
        preview_layout.setContentsMargins(26, 20, 26, 18)
        preview_layout.setSpacing(12)
        preview_header = QHBoxLayout()
        preview_heading = QVBoxLayout()
        preview_heading.setSpacing(2)
        preview_title = QLabel("记忆预览")
        preview_title.setObjectName("workspaceTitle")
        self.preview_summary = QLabel("暂无消息")
        self.preview_summary.setObjectName("subtitle")
        preview_heading.addWidget(preview_title)
        preview_heading.addWidget(self.preview_summary)
        preview_header.addLayout(preview_heading)
        preview_header.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchField")
        self.search_edit.setPlaceholderText("搜索发送者或消息内容")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(300)
        self.search_edit.textChanged.connect(self._refresh_preview)
        preview_header.addWidget(self.search_edit)
        preview_layout.addLayout(preview_header)

        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(["时间", "发送者", "类型", "内容"])
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setShowGrid(False)
        self.preview_table.setWordWrap(False)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(40)
        header = self.preview_table.horizontalHeader()
        header.setMinimumSectionSize(80)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 144)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 124)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 82)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        preview_layout.addWidget(self.preview_table)

        splitter.addWidget(sidebar)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([350, 930])
        root_layout.addWidget(splitter, 1)

        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        action_layout = QHBoxLayout(status_bar)
        action_layout.setContentsMargins(22, 8, 22, 8)
        action_layout.setSpacing(12)
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setMinimumWidth(220)
        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress, 1)
        local_note = QLabel("数据仅在本机处理")
        local_note.setObjectName("footerNote")
        local_note.setMinimumWidth(110)
        local_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        action_layout.addWidget(local_note)
        root_layout.addWidget(status_bar)

        self.setCentralWidget(root)
        self.setStyleSheet(_STYLESHEET)
        self._source_mode_changed()

    def _source_mode_changed(self) -> None:
        mode = str(self.source_mode.currentData())
        local = mode == "wechat"
        self._image_reading_enabled = False
        self.image_key_button.setText("读取图片")
        self.source_label.setText("账户目录" if local else "JSON 文件")
        self.source_edit.setPlaceholderText("自动检测微信 4.x 数据目录" if local else "选择 version 1 JSON 文件")
        self.load_button.setText("连接微信" if local else "加载")
        self.image_key_button.setVisible(local)
        saved = str(self._settings.value(f"{mode}SourcePath", ""))
        if saved and Path(saved).exists():
            self.source_edit.setText(saved)
        elif local:
            accounts = discover_wechat4_accounts()
            self.source_edit.setText(str(accounts[0].account_dir) if accounts else "")
        else:
            self.source_edit.clear()
        if self._source is not None:
            self._close_source()
            self.conversation_combo.clear()
            self.conversation_search_button.setEnabled(False)
            self.preview_table.setRowCount(0)
            self.preview_summary.setText("暂无消息")
            self.export_button.setEnabled(False)
            self.image_key_button.setEnabled(False)
        self.search_edit.clear()
        self._reset_metrics()

    def _browse_source(self) -> None:
        if self.source_mode.currentData() == "wechat":
            path = QFileDialog.getExistingDirectory(self, "选择微信账户目录", self.source_edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择聊天 JSON", self.source_edit.text(), "JSON files (*.json)"
            )
        if path:
            self.source_edit.setText(path)

    def _load_source(self) -> None:
        mode = str(self.source_mode.currentData())
        path = self.source_edit.text().strip()
        if not path:
            QMessageBox.information(self, "缺少数据位置", "请选择数据位置。")
            return
        if mode == "wechat":
            answer = QMessageBox.question(
                self,
                "连接本机微信",
                "连接时会重启微信一次，并可能要求扫码确认。微信原始数据库不会被修改。是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._close_source()
        self._set_busy(True)
        self._set_connection_state("正在连接", "busy")
        self.status_label.setText("正在连接...")
        self.progress.setRange(0, 0)
        self._source_worker = SourceLoadWorker(mode, path)
        self._source_worker.progress.connect(self._operation_progress)
        self._source_worker.completed.connect(self._source_loaded)
        self._source_worker.failed.connect(self._source_failed)
        self._source_worker.start()

    def _source_loaded(self, source: ChatSource) -> None:
        self._source = source
        self._settings.setValue(
            f"{self.source_mode.currentData()}SourcePath",
            self.source_edit.text().strip(),
        )
        self.conversation_combo.blockSignals(True)
        self.conversation_combo.clear()
        for conversation in source.list_conversations():
            self.conversation_combo.addItem(conversation.name, conversation.id)
        if self.conversation_combo.count():
            self.conversation_combo.setCurrentIndex(0)
        self.conversation_combo.blockSignals(False)
        self.conversation_search_button.setEnabled(self.conversation_combo.count() > 0)
        self.image_key_button.setEnabled(isinstance(source, WeChat4LocalSource))
        self._set_busy(False)
        self.progress.setRange(0, 4)
        self.progress.setValue(4)
        self._set_connection_state("已连接", "connected")
        self.status_label.setText(f"已连接，{self.conversation_combo.count()} 个会话")
        self._conversation_changed()

    def _source_failed(self, error: str) -> None:
        self._set_busy(False)
        self.progress.setRange(0, 4)
        self.progress.setValue(0)
        if self._closing:
            return
        self._set_connection_state("连接失败", "error")
        self.status_label.setText("连接失败")
        QMessageBox.critical(self, "无法连接数据", error)

    def _open_conversation_search(self) -> None:
        if self.conversation_combo.count() == 0:
            return
        choices = [
            (self.conversation_combo.itemText(index), self.conversation_combo.itemData(index))
            for index in range(self.conversation_combo.count())
        ]
        dialog = ConversationSearchDialog(choices, self.conversation_combo.currentData(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        index = self.conversation_combo.findData(dialog.selected_data())
        if index >= 0:
            self.conversation_combo.setCurrentIndex(index)

    def _conversation_changed(self) -> None:
        if not self._source or self.conversation_combo.currentIndex() < 0:
            return
        self._messages = []
        self.preview_table.setRowCount(0)
        self.export_button.setEnabled(False)
        self.conversation_combo.setEnabled(False)
        self.conversation_search_button.setEnabled(False)
        self.status_label.setText("正在读取消息...")
        self.progress.setRange(0, 0)
        self._message_worker = MessageLoadWorker(self._source, str(self.conversation_combo.currentData()))
        self._message_worker.completed.connect(self._messages_loaded)
        self._message_worker.failed.connect(self._messages_failed)
        self._message_worker.start()

    def _messages_loaded(self, messages: list[Message]) -> None:
        self._messages = messages
        self.conversation_combo.setEnabled(True)
        self.conversation_search_button.setEnabled(True)
        self.progress.setRange(0, 4)
        self.progress.setValue(4)
        if messages:
            first = QDate(messages[0].timestamp.year, messages[0].timestamp.month, messages[0].timestamp.day)
            last = QDate(messages[-1].timestamp.year, messages[-1].timestamp.month, messages[-1].timestamp.day)
            self.start_date.blockSignals(True)
            self.end_date.blockSignals(True)
            self.start_date.setDate(first)
            self.end_date.setDate(last)
            self.start_date.blockSignals(False)
            self.end_date.blockSignals(False)
        status = "图片读取已启用 · 消息读取完成" if self._image_reading_enabled else "消息读取完成"
        self.status_label.setText(status)
        self.export_button.setEnabled(True)
        self._suggest_output_path()
        self._refresh_preview()

    def _messages_failed(self, error: str) -> None:
        self.conversation_combo.setEnabled(True)
        self.conversation_search_button.setEnabled(True)
        self.progress.setRange(0, 4)
        self.progress.setValue(0)
        if self._closing:
            return
        self.status_label.setText("消息读取失败")
        self.export_button.setEnabled(False)
        QMessageBox.critical(self, "无法读取消息", error)

    def _refresh_preview(self) -> None:
        start, end = self._selected_range()
        ranged_messages = [message for message in self._messages if start <= message.timestamp <= end]
        query = self.search_edit.text().strip().casefold()
        if query:
            messages = [
                message
                for message in ranged_messages
                if query in message.sender.casefold()
                or query in message.content.casefold()
                or query in message.type.value.casefold()
            ]
        else:
            messages = ranged_messages
        visible = messages[:200]
        self.preview_table.setRowCount(len(visible))
        type_labels = {
            MessageType.TEXT: "文本",
            MessageType.IMAGE: "图片",
            MessageType.FILE: "文件",
            MessageType.SYSTEM: "系统",
        }
        type_colors = {
            MessageType.TEXT: "#087f4f",
            MessageType.IMAGE: "#c45d16",
            MessageType.FILE: "#2563a6",
            MessageType.SYSTEM: "#6b7280",
        }
        for row, message in enumerate(visible):
            content = (
                Path(message.content).name
                if message.type in (MessageType.IMAGE, MessageType.FILE)
                else message.content
            )
            content = content.replace("\n", " ")
            if len(content) > 180:
                content = content[:177] + "..."
            values = [
                message.timestamp.strftime("%Y-%m-%d %H:%M"),
                message.sender,
                type_labels[message.type],
                content,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 2):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    item.setForeground(QColor(type_colors[message.type]))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if column == 3:
                    item.setToolTip(message.content)
                self.preview_table.setItem(row, column, item)
        suffix = " · 仅显示前 200 条" if len(messages) > 200 else ""
        if query:
            summary = f"{len(messages):,} 条匹配 · 当前范围 {len(ranged_messages):,} 条{suffix}"
        else:
            summary = f"{len(messages):,} 条消息{suffix}"
        self.preview_summary.setText(summary)
        self.message_metric.setText(f"{len(messages):,}")
        self.image_metric.setText(f"{sum(message.type is MessageType.IMAGE for message in messages):,}")
        self.day_metric.setText(f"{len({message.timestamp.date() for message in messages}):,}")

    def _load_image_key(self) -> None:
        if not isinstance(self._source, WeChat4LocalSource):
            return
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("正在读取图片密钥...")
        self._image_worker = ImageKeyWorker(self._source)
        self._image_worker.progress.connect(self._operation_progress)
        self._image_worker.completed.connect(self._image_key_loaded)
        self._image_worker.failed.connect(self._image_key_failed)
        self._image_worker.start()

    def _image_key_loaded(self, _key: bytes) -> None:
        self._image_reading_enabled = True
        self.image_key_button.setText("图片已启用")
        self._set_busy(False)
        self.progress.setRange(0, 4)
        self.progress.setValue(4)
        self._conversation_changed()

    def _image_key_failed(self, error: str) -> None:
        self._image_reading_enabled = False
        self.image_key_button.setText("读取图片")
        self._set_busy(False)
        self.progress.setRange(0, 4)
        self.progress.setValue(0)
        if self._closing:
            return
        self.status_label.setText("图片密钥读取失败")
        QMessageBox.critical(self, "无法读取图片", error)

    def _suggest_output_path(self) -> None:
        if self.output_edit.text().strip() or self.conversation_combo.currentIndex() < 0:
            return
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.conversation_combo.currentText()
        )
        output_dir = Path.cwd() / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_edit.setText(str(output_dir / f"{safe_name}_memory.pdf"))

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", self.output_edit.text(), "PDF files (*.pdf)")
        if path:
            self.output_edit.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def _start_export(self) -> None:
        if not self._source or self.conversation_combo.currentIndex() < 0:
            QMessageBox.information(self, "尚未选择会话", "请先连接数据并选择会话。")
            return
        output_text = self.output_edit.text().strip()
        if not output_text:
            self._browse_output()
            output_text = self.output_edit.text().strip()
            if not output_text:
                return
        output = Path(output_text).expanduser().resolve()
        start, end = self._selected_range()
        options = ExportOptions(
            conversation_id=str(self.conversation_combo.currentData()),
            output_pdf=output,
            start=start,
            end=end,
            include_image_pages=self.image_pages_check.isChecked(),
            pages_dir=output.with_name(f"{output.stem}_pages") if self.keep_pages_check.isChecked() else None,
            markdown_path=output.with_suffix(".md") if self.companions_check.isChecked() else None,
            json_path=output.with_suffix(".json") if self.companions_check.isChecked() else None,
            query=self.search_edit.text().strip() or None,
        )
        self._settings.setValue("outputPath", str(output))
        self._set_busy(True)
        self._export_worker = ExportWorker(self._source, options)
        self._export_worker.progress.connect(self._operation_progress)
        self._export_worker.completed.connect(self._export_completed)
        self._export_worker.failed.connect(self._export_failed)
        self._export_worker.start()

    def _operation_progress(self, current: int, total: int, label: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.status_label.setText(label)

    def _export_completed(self, result: ExportResult) -> None:
        self._last_result = result
        self._set_busy(False)
        self.progress.setValue(self.progress.maximum())
        self.status_label.setText(f"{result.page_count} 页 · {result.message_count} 条消息")
        self.open_folder_button.setEnabled(True)
        QMessageBox.information(self, "导出完成", f"已生成：\n{result.pdf_path}")

    def _export_failed(self, error: str) -> None:
        self._set_busy(False)
        self.progress.setValue(0)
        if self._closing:
            return
        self.status_label.setText("导出失败")
        QMessageBox.critical(self, "导出失败", error)

    def _set_busy(self, busy: bool) -> None:
        self.load_button.setEnabled(not busy)
        self.source_mode.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        self.source_browse_button.setEnabled(not busy)
        self.conversation_search_button.setEnabled(
            not busy and self._source is not None and self.conversation_combo.count() > 0
        )
        self.export_button.setEnabled(
            not busy and self._source is not None and self.conversation_combo.currentIndex() >= 0
        )
        self.image_key_button.setEnabled(not busy and isinstance(self._source, WeChat4LocalSource))

    def _set_connection_state(self, text: str, state: str) -> None:
        self.connection_badge.setText(text)
        self.connection_badge.setProperty("state", state)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def _reset_metrics(self) -> None:
        self.message_metric.setText("0")
        self.image_metric.setText("0")
        self.day_metric.setText("0")

    def _open_output_folder(self) -> None:
        if self._last_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_result.pdf_path.parent)))

    def _selected_range(self) -> tuple[datetime, datetime]:
        start_date = self.start_date.date().toPython()
        end_date = self.end_date.date().toPython()
        return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)

    def _start_date_changed(self, selected: QDate) -> None:
        if selected > self.end_date.date():
            self.end_date.blockSignals(True)
            self.end_date.setDate(selected)
            self.end_date.blockSignals(False)
        self._refresh_preview()

    def _end_date_changed(self, selected: QDate) -> None:
        if selected < self.start_date.date():
            self.start_date.blockSignals(True)
            self.start_date.setDate(selected)
            self.start_date.blockSignals(False)
        self._refresh_preview()

    def _show_date_calendar(self, date_edit: QDateEdit, _anchor: QToolButton) -> None:
        title = "选择开始日期" if date_edit is self.start_date else "选择结束日期"
        dialog = DatePickerDialog(
            title,
            date_edit.date(),
            date_edit.minimumDate(),
            date_edit.maximumDate(),
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            date_edit.setDate(dialog.selected_date())

    def _restore_settings(self) -> None:
        mode = "wechat"
        self.source_mode.setCurrentIndex(self.source_mode.findData(mode))
        source_path = str(self._settings.value(f"{mode}SourcePath", ""))
        legacy_path = str(self._settings.value("sourcePath", ""))
        if not source_path and legacy_path and Path(legacy_path).exists():
            legacy = Path(legacy_path)
            if (mode == "json" and legacy.is_file()) or (mode == "wechat" and legacy.is_dir()):
                self._settings.setValue(f"{mode}SourcePath", legacy_path)
        output_path = str(self._settings.value("outputPath", ""))
        if output_path:
            self.output_edit.setText(output_path)
        self._source_mode_changed()

    def _close_source(self) -> None:
        if self._source is not None and hasattr(self._source, "close"):
            self._source.close()  # type: ignore[attr-defined]
        self._source = None
        self._image_reading_enabled = False
        self.image_key_button.setText("读取图片")
        self._set_connection_state("未连接", "idle")

    def closeEvent(self, event: QCloseEvent) -> None:
        workers = (
            self._source_worker,
            self._message_worker,
            self._image_worker,
            self._export_worker,
        )
        running = [worker for worker in workers if worker is not None and worker.isRunning()]
        if running:
            self._closing = True
            for worker in running:
                worker.requestInterruption()
            self.status_label.setText("正在结束后台任务...")
            event.ignore()
            QTimer.singleShot(250, self.close)
            return
        self._close_source()
        super().closeEvent(event)


_STYLESHEET = """
QMainWindow, QWidget#appRoot {
    background: #f3f5f4;
}
QWidget {
    color: #1d2622;
    font-size: 13px;
}
QLabel {
    background: transparent;
}
QFrame#topBar {
    background: #ffffff;
    border-bottom: 1px solid #dfe5e1;
}
QLabel#brandMark {
    background: transparent;
}
QLabel#pageTitle {
    color: #17211c;
    font-size: 18px;
    font-weight: 700;
}
QLabel#editionLabel {
    color: #7b8580;
    font-size: 9px;
}
QLabel#privacyBadge, QLabel#connectionBadge {
    border-radius: 5px;
    padding: 5px 9px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#privacyBadge {
    background: #eef1f0;
    color: #56615b;
}
QLabel#connectionBadge[state="idle"] {
    background: #edf0ef;
    color: #69736e;
}
QLabel#connectionBadge[state="busy"] {
    background: #fff1e8;
    color: #a64b12;
}
QLabel#connectionBadge[state="connected"] {
    background: #e5f7ed;
    color: #087f4f;
}
QLabel#connectionBadge[state="error"] {
    background: #fdebea;
    color: #b42318;
}
QFrame#sidebar {
    background: #fafcfb;
    border-right: 1px solid #dfe5e1;
}
QScrollArea#sidebarScroll, QScrollArea#sidebarScroll > QWidget > QWidget,
QWidget#sidebarForm, QWidget#sidebarActions {
    background: #fafcfb;
    border: 0;
}
QWidget#workspace {
    background: #f6f8f7;
}
QLabel#sectionIndex {
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    border-radius: 4px;
    background: #e5f7ed;
    color: #087f4f;
    font-size: 10px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#sectionTitle {
    color: #27322c;
    font-size: 13px;
    font-weight: 700;
}
QFrame#metricsPanel {
    background: #f3f7f5;
    border: 1px solid #dce5e0;
    border-radius: 6px;
}
QWidget#metricBlock {
    background: transparent;
    border: 0;
}
QFrame#metricDivider {
    background: #d8e2dd;
    border: 0;
    margin-top: 9px;
    margin-bottom: 9px;
}
QLabel#metricValue {
    color: #17211c;
    font-size: 15px;
    font-weight: 700;
}
QLabel#metricCaption {
    color: #75817b;
    font-size: 10px;
}
QLabel#fieldLabel {
    color: #64706a;
    font-size: 11px;
    font-weight: 600;
    padding-top: 2px;
}
QFrame#separator {
    border: 0;
    background: #e5e9e7;
    margin-top: 5px;
    margin-bottom: 5px;
}
QLabel#dateCaption {
    color: #64706a;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workspaceTitle {
    color: #17211c;
    font-size: 20px;
    font-weight: 700;
}
QLabel#subtitle {
    color: #6d7772;
    font-size: 11px;
}
QLineEdit, QComboBox, QDateEdit {
    min-height: 38px;
    background: #ffffff;
    border: 1px solid #ced7d2;
    border-radius: 6px;
    padding: 0 10px;
    selection-background-color: #07c160;
}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover {
    border-color: #9eadA5;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid #07a851;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {
    color: #919b96;
    background: #eef1ef;
}
QLineEdit#searchField {
    background: #ffffff;
    padding-left: 12px;
}
QDateEdit#dateInput {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    padding: 0 8px;
}
QToolButton#calendarButton {
    background: #ffffff;
    border: 1px solid #ced7d2;
    border-left: 0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    padding: 7px;
}
QToolButton#calendarButton:hover {
    background: #f0f4f2;
    border-color: #9eada5;
}
QToolButton#scopeSearchButton {
    background: #ffffff;
    border: 1px solid #ced7d2;
    border-radius: 6px;
    padding: 9px;
}
QToolButton#scopeSearchButton:hover {
    background: #f0f4f2;
    border-color: #9eada5;
}
QComboBox::drop-down, QDateEdit::drop-down {
    border: 0;
    width: 26px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #ced7d2;
    selection-background-color: #e5f7ed;
    selection-color: #17211c;
    padding: 4px;
}
QDialog#conversationSearchDialog, QDialog#datePickerDialog {
    background: #f8faf9;
}
QLabel#dialogTitle {
    color: #17211c;
    font-size: 18px;
    font-weight: 700;
}
QLabel#calendarMonthLabel {
    color: #27322c;
    font-size: 15px;
    font-weight: 700;
}
QListWidget#conversationChoiceList {
    background: #ffffff;
    alternate-background-color: #f8faf9;
    border: 1px solid #dce3df;
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}
QListWidget#conversationChoiceList::item {
    min-height: 38px;
    padding: 0 10px;
    border-radius: 4px;
}
QListWidget#conversationChoiceList::item:selected {
    color: #087f4f;
    background: #e5f7ed;
}
QToolButton#calendarNavButton {
    background: #ffffff;
    border: 1px solid #d7dfdb;
    border-radius: 5px;
    padding: 7px;
}
QToolButton#calendarNavButton:hover {
    background: #eef5f1;
    border-color: #9eada5;
}
QCalendarWidget#rangeCalendar {
    background: #ffffff;
    border: 1px solid #dce3df;
    border-radius: 6px;
}
QCalendarWidget#rangeCalendar QAbstractItemView:enabled {
    color: #27322c;
    background: #ffffff;
    selection-background-color: #07c160;
    selection-color: #ffffff;
    outline: 0;
}
QPushButton#dialogPrimary {
    background: #07c160;
    color: #ffffff;
    border-color: #07c160;
}
QPushButton#dialogPrimary:hover {
    background: #06ad56;
    border-color: #06ad56;
}
QPushButton {
    min-height: 38px;
    border: 1px solid #c8d1cc;
    border-radius: 6px;
    background: #ffffff;
    color: #27322c;
    padding: 0 13px;
    font-weight: 600;
}
QPushButton:hover {
    background: #f0f4f2;
    border-color: #aab7b0;
}
QPushButton:pressed {
    background: #e6ece9;
}
QPushButton:disabled {
    color: #9da6a1;
    border-color: #dde2df;
    background: #eef1ef;
}
QPushButton#iconButton {
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
}
QPushButton#connectButton {
    color: #087f4f;
    border-color: #8fd9b2;
    background: #f0fbf5;
}
QPushButton#connectButton:hover {
    background: #e3f7ec;
}
QPushButton#primaryButton {
    min-height: 44px;
    background: #07c160;
    color: #ffffff;
    border-color: #07c160;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #06ad56;
    border-color: #06ad56;
}
QPushButton#primaryButton:disabled {
    background: #b6c6bd;
    border-color: #b6c6bd;
    color: #f3f6f4;
}
QCheckBox {
    min-height: 24px;
    color: #46514b;
    spacing: 8px;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f9fbfa;
    border: 1px solid #dce3df;
    border-radius: 6px;
    padding: 0;
    selection-background-color: #dff5e9;
    selection-color: #17211c;
}
QTableWidget::item {
    border-bottom: 1px solid #edf0ee;
    padding: 6px 8px;
}
QHeaderView::section {
    background: #eef2f0;
    color: #58635d;
    border: 0;
    border-bottom: 1px solid #d7dfdb;
    padding: 9px 8px;
    font-size: 11px;
    font-weight: 700;
}
QScrollBar:vertical {
    background: #f2f5f3;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #bdc8c2;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter#mainSplitter::handle {
    background: #dfe5e1;
    width: 1px;
}
QFrame#statusBar {
    background: #ffffff;
    border-top: 1px solid #dfe5e1;
}
QLabel#statusLabel, QLabel#footerNote {
    color: #69736e;
    font-size: 11px;
}
QProgressBar {
    max-height: 5px;
    border: 0;
    border-radius: 2px;
    background: #e4e9e6;
}
QProgressBar::chunk {
    border-radius: 2px;
    background: #07c160;
}
QToolTip {
    background: #26312b;
    color: #ffffff;
    border: 0;
    padding: 6px;
}
"""


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("LocalTools")
    app.setWindowIcon(application_icon())
    app.setStyle("Fusion")
    try:
        font_id = QFontDatabase.addApplicationFont(str(FontBook.discover().regular_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    except RuntimeError:
        pass
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
