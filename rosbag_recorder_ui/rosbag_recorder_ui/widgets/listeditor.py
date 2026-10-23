"""
A small editor for a list of strings: keywords and exclude patterns.

Entries are validated as they are typed. An invalid regex is caught here,
"""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_SM, SPACE_XS
from rosbag_recorder_ui.widgets.cards import restyle


def validate_regex(pattern):
    """Return an error message, or '' when *pattern* compiles."""
    try:
        re.compile(pattern)
    except re.error as err:
        return f'Invalid regex: {err}'
    return ''


class StringListEditor(QWidget):
    """A list with an add field, a remove button and optional validation."""

    changed = Signal(list)

    def __init__(self, placeholder='', validator=None, empty_hint='', parent=None):
        super().__init__(parent)
        self._validator = validator
        self._values = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        entry = QHBoxLayout()
        entry.setSpacing(SPACE_XS + 2)
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.returnPressed.connect(self._add)
        self.input.textChanged.connect(self._validate_input)
        entry.addWidget(self.input, 1)

        self.add_button = QPushButton()
        self.add_button.setIcon(icons.icon('plus', PALETTE.text, 15))
        self.add_button.setToolTip('Add')
        self.add_button.setFixedWidth(38)
        self.add_button.clicked.connect(self._add)
        entry.addWidget(self.add_button)
        layout.addLayout(entry)

        self.error = QLabel('')
        self.error.setObjectName('CardHint')
        self.error.setStyleSheet(f'color: {PALETTE.danger};')
        self.error.setVisible(False)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMaximumHeight(132)
        self.list.setAlternatingRowColors(False)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.list)

        self.empty_label = QLabel(empty_hint)
        self.empty_label.setObjectName('CardHint')
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.remove_button = QPushButton('  Remove')
        self.remove_button.setProperty('variant', 'ghost')
        self.remove_button.setIcon(icons.icon('trash', PALETTE.text_muted, 14))
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove_selected)
        footer.addWidget(self.remove_button)
        layout.addLayout(footer)

        self._refresh()

    # ------------------------------------------------------------------

    def values(self):
        return list(self._values)

    def set_values(self, values):
        values = [str(v) for v in values if str(v).strip()]
        if values == self._values:
            return
        self._values = values
        self._refresh()

    def _validate_input(self, text):
        message = self._validator(text) if (self._validator and text.strip()) else ''
        self.error.setText(message)
        self.error.setVisible(bool(message))
        self.input.setProperty('invalid', bool(message))
        restyle(self.input)
        self.add_button.setEnabled(not message and bool(text.strip()))
        return not message

    def _add(self):
        text = self.input.text().strip()
        if not text or not self._validate_input(text):
            return
        if text in self._values:
            self.error.setText('Already in the list.')
            self.error.setVisible(True)
            return
        self._values.append(text)
        self.input.clear()
        self._refresh()
        self.changed.emit(self.values())

    def _remove_selected(self):
        selected = {item.text() for item in self.list.selectedItems()}
        if not selected:
            return
        self._values = [v for v in self._values if v not in selected]
        self._refresh()
        self.changed.emit(self.values())

    def _update_buttons(self):
        self.remove_button.setEnabled(bool(self.list.selectedItems()))

    def _refresh(self):
        self.list.clear()
        for value in self._values:
            item = QListWidgetItem(value)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.list.addItem(item)
        self.list.setVisible(bool(self._values))
        self.empty_label.setVisible(not self._values)
        self._update_buttons()
