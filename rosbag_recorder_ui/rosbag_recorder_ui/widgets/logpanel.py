"""
The log viewer.

Log lines arrive from /rosout as fast as the recorder produces them,
and the UI is expected to keep up. The view is therefore buffered and repainted
"""
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import clock_time
from rosbag_recorder_ui.core.theme import MONO_STACK, PALETTE, SPACE_SM, SPACE_XS
from rosbag_recorder_ui.ros.ros_link import (
    LEVEL_DEBUG,
    LEVEL_ERROR,
    LEVEL_FATAL,
    LEVEL_INFO,
    LEVEL_WARN,
    LogRecord,
)

MAX_RECORDS = 4000
REPAINT_INTERVAL_MS = 350

# INFO is the overwhelming majority of what /rosout carries, so it is left
# grey: colouring it would make the log a wall of accent and leave nothing for
# the two levels that actually want the operator's eye.
LEVEL_COLORS = {
    LEVEL_DEBUG: PALETTE.text_dim,
    LEVEL_INFO: PALETTE.text_muted,
    LEVEL_WARN: PALETTE.warning,
    LEVEL_ERROR: PALETTE.danger,
    LEVEL_FATAL: PALETTE.danger,
}


class LogPanel(QWidget):
    """Filterable log view over everything the recorder and bridge say."""

    counts_changed = Signal(int, int)   # warnings, errors

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records = []
        self._pending = []
        self._min_level = LEVEL_INFO
        self._search = ''
        self._follow = True
        self.warning_count = 0
        self.error_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        layout.addLayout(self._build_toolbar())

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_RECORDS)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setStyleSheet(
            f'font-family: {MONO_STACK}; font-size: 12px; '
            f'background: {PALETTE.bg_sunken}; border: 1px solid {PALETTE.border};'
            'border-radius: 8px; padding: 8px;')
        self.view.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        layout.addWidget(self.view, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(REPAINT_INTERVAL_MS)

    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(SPACE_XS + 2)

        self._level_buttons = {}
        for label, level in (('INFO', LEVEL_INFO), ('WARN', LEVEL_WARN),
                             ('ERROR', LEVEL_ERROR)):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty('variant', 'ghost')
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(level == LEVEL_INFO)
            button.clicked.connect(lambda _c=False, lvl=level: self.set_min_level(lvl))
            button.setFixedWidth(62)
            button.setStyleSheet('font-size: 11px; font-weight: 700; letter-spacing: 0.6px;')
            self._level_buttons[level] = button
            row.addWidget(button)

        row.addSpacing(SPACE_SM)
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('Filter log…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.search.setMaximumWidth(280)
        row.addWidget(self.search, 1)

        self.summary = QLabel('')
        self.summary.setObjectName('CardHint')
        row.addWidget(self.summary)

        self.follow_button = QPushButton()
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(True)
        self.follow_button.setProperty('variant', 'ghost')
        self.follow_button.setIcon(icons.icon('chevron-down', PALETTE.text_muted, 14))
        self.follow_button.setToolTip('Follow new messages')
        self.follow_button.setFixedWidth(32)
        self.follow_button.toggled.connect(self._set_follow)
        row.addWidget(self.follow_button)

        clear = QPushButton()
        clear.setProperty('variant', 'ghost')
        clear.setIcon(icons.icon('trash', PALETTE.text_muted, 14))
        clear.setToolTip('Clear the log view')
        clear.setFixedWidth(32)
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        return row

    # -- input ----------------------------------------------------------

    def append(self, record):
        self._records.append(record)
        if len(self._records) > MAX_RECORDS:
            del self._records[:len(self._records) - MAX_RECORDS]
        if record.level >= LEVEL_ERROR:
            self.error_count += 1
        elif record.level == LEVEL_WARN:
            self.warning_count += 1
        if self._passes(record):
            self._pending.append(record)
        if record.level >= LEVEL_WARN:
            self.counts_changed.emit(self.warning_count, self.error_count)

    def log(self, level, message, name='dashboard'):
        """Add a locally generated line, so UI events sit in the same timeline."""
        self.append(LogRecord(time.time(), level, name, message))

    # -- filtering ------------------------------------------------------

    def set_min_level(self, level):
        self._min_level = level
        for value, button in self._level_buttons.items():
            button.setChecked(value == level)
        self._rebuild()

    def _on_search(self, text):
        self._search = text.strip().lower()
        self._rebuild()

    def _passes(self, record):
        if record.level < self._min_level:
            return False
        if self._search and self._search not in record.message.lower() \
                and self._search not in record.name.lower():
            return False
        return True

    def _rebuild(self):
        self.view.clear()
        self._pending = [r for r in self._records if self._passes(r)]
        self._flush(force=True)

    def clear(self):
        self._records = []
        self._pending = []
        self.warning_count = 0
        self.error_count = 0
        self.view.clear()
        self.counts_changed.emit(0, 0)
        self._update_summary()

    # -- rendering ------------------------------------------------------

    def _set_follow(self, follow):
        self._follow = follow
        if follow:
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().maximum())

    def _on_scrolled(self, value):
        bar = self.view.verticalScrollBar()
        at_bottom = value >= bar.maximum() - 4
        if at_bottom != self._follow:
            self._follow = at_bottom
            self.follow_button.blockSignals(True)
            self.follow_button.setChecked(at_bottom)
            self.follow_button.blockSignals(False)

    def _flush(self, force=False):
        if not self._pending:
            if force:
                self._update_summary()
            return
        batch, self._pending = self._pending, []
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.End)

        for record in batch:
            self._write(cursor, f'{clock_time(record.stamp)} ', PALETTE.text_dim)
            self._write(cursor, f'{record.level_name:<5} ',
                        LEVEL_COLORS.get(record.level, PALETTE.text_muted), bold=True)
            self._write(cursor, record.message.replace('\n', ' ') + '\n', PALETTE.text)

        if self._follow:
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._update_summary()

    @staticmethod
    def _write(cursor, text, color, bold=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(700)
        cursor.insertText(text, fmt)

    def _update_summary(self):
        shown = sum(1 for r in self._records if self._passes(r))
        parts = [f'{shown} shown']
        if self.warning_count:
            parts.append(f'{self.warning_count} warning'
                         f'{"s" if self.warning_count != 1 else ""}')
        if self.error_count:
            parts.append(f'{self.error_count} error'
                         f'{"s" if self.error_count != 1 else ""}')
        self.summary.setText(' · '.join(parts))
