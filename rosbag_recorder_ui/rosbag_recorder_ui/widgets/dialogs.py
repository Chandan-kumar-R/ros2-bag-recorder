"""
Dialogs.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.theme import MONO_STACK, PALETTE, SPACE_LG, SPACE_MD, SPACE_SM


class MessageDialog(QDialog):
    """A titled message with an optional collapsible detail block."""

    def __init__(self, parent, tone, title, message, detail='',
                 confirm_text='OK', cancel_text=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.setModal(True)

        color = PALETTE.state_color('danger' if tone == 'error' else tone)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        layout.setSpacing(SPACE_MD)

        header = QHBoxLayout()
        header.setSpacing(SPACE_MD - 2)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(
            {'error': 'error', 'warning': 'warning', 'success': 'check'}.get(tone, 'info'),
            color, 24))
        glyph.setAlignment(Qt.AlignTop)
        header.addWidget(glyph)

        text_column = QVBoxLayout()
        text_column.setSpacing(SPACE_SM - 2)
        heading = QLabel(title)
        heading.setStyleSheet('font-size: 15px; font-weight: 600;')
        heading.setWordWrap(True)
        text_column.addWidget(heading)
        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet(f'color: {PALETTE.text_muted};')
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_column.addWidget(body)
        header.addLayout(text_column, 1)
        layout.addLayout(header)

        self._detail_box = None
        if detail:
            self._detail_box = QPlainTextEdit(detail)
            self._detail_box.setReadOnly(True)
            self._detail_box.setVisible(False)
            self._detail_box.setMaximumHeight(150)
            self._detail_box.setStyleSheet(
                f'font-family: {MONO_STACK}; font-size: 11px; '
                f'color: {PALETTE.text_muted};')
            layout.addWidget(self._detail_box)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SM)
        if detail:
            self._detail_button = QPushButton('Show details')
            self._detail_button.setProperty('variant', 'ghost')
            self._detail_button.clicked.connect(self._toggle_detail)
            buttons.addWidget(self._detail_button)
        buttons.addStretch(1)

        if cancel_text:
            cancel = QPushButton(cancel_text)
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)

        confirm = QPushButton(confirm_text)
        confirm.setProperty('variant', 'primary' if tone != 'error' or not cancel_text
                            else 'primary')
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _toggle_detail(self):
        visible = not self._detail_box.isVisible()
        self._detail_box.setVisible(visible)
        self._detail_button.setText('Hide details' if visible else 'Show details')
        self.adjustSize()


def show_error(parent, title, message, detail=''):
    MessageDialog(parent, 'error', title, message, detail).exec()


def show_info(parent, title, message, detail=''):
    MessageDialog(parent, 'info', title, message, detail).exec()


def confirm(parent, title, message, confirm_text='Confirm', tone='warning', detail=''):
    """Ask before anything that cannot be undone; True when the user agreed."""
    dialog = MessageDialog(parent, tone, title, message, detail,
                           confirm_text=confirm_text, cancel_text='Cancel')
    return dialog.exec() == QDialog.Accepted
