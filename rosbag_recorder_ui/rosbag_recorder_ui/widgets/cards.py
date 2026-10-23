"""Card primitives: the containers every page is built out of."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import NA
from rosbag_recorder_ui.core.theme import (
    PALETTE,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
)


def restyle(widget):
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class Card(QFrame):
    """A bordered surface. ``tone`` drives the accent used by the stylesheet."""

    def __init__(self, parent=None, tone='', padding=SPACE_LG):
        super().__init__(parent)
        self.setObjectName('Card')
        self.setProperty('tone', tone)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(SPACE_MD)

    def layout(self):
        return self._layout

    def set_tone(self, tone):
        if self.property('tone') != tone:
            self.setProperty('tone', tone)
            restyle(self)


class SectionCard(Card):
    """A card with a title row, and optional widgets docked to the right of it."""

    def __init__(self, title, subtitle='', icon_name='', parent=None, tone=''):
        super().__init__(parent, tone=tone)
        # Title row and subtitle are separate rows so a two-line header never
        # leaves the icon floating between them.
        header = QHBoxLayout()
        header.setSpacing(SPACE_SM)
        self._indent = 0

        if icon_name:
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap(icon_name, PALETTE.text_muted, 16))
            glyph.setFixedWidth(18)
            self._indent = 18 + SPACE_SM
            header.addWidget(glyph, 0, Qt.AlignVCenter)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName('SectionTitle')
        header.addWidget(self.title_label, 0, Qt.AlignVCenter)
        header.addStretch(1)

        self._header = header
        self._layout.addLayout(header)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName('CardHint')
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setContentsMargins(self._indent, 0, 0, 0)
        self.subtitle_label.setVisible(bool(subtitle))
        self._layout.addWidget(self.subtitle_label)
        self._layout.setSpacing(SPACE_SM)

        self.body = QVBoxLayout()
        self.body.setSpacing(SPACE_MD)
        self.body.setContentsMargins(0, SPACE_XS, 0, 0)
        self._layout.addLayout(self.body)

    def add_header_widget(self, widget):
        self._header.addWidget(widget, 0, Qt.AlignVCenter)

    def set_subtitle(self, text):
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))


class StatCard(Card):
    """
    One number, prominently. The label is a constant; the value changes.

    ``set_value`` accepts already-formatted strings so the caller keeps control
    of what 'unknown' looks like.
    """

    def __init__(self, label, value=NA, hint='', icon_name='', parent=None,
                 compact=False):
        super().__init__(parent, padding=SPACE_MD if compact else SPACE_LG)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._layout.setSpacing(SPACE_XS)

        top = QHBoxLayout()
        top.setSpacing(SPACE_SM)
        self.label = QLabel(label.upper())
        self.label.setObjectName('CardLabel')
        top.addWidget(self.label)
        top.addStretch(1)
        self.glyph = QLabel()
        if icon_name:
            self.glyph.setPixmap(icons.pixmap(icon_name, PALETTE.text_dim, 15))
        top.addWidget(self.glyph)
        self._layout.addLayout(top)

        self.value = QLabel(value)
        self.value.setObjectName('CardValueSm' if compact else 'CardValue')
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._layout.addWidget(self.value)

        self.hint = QLabel(hint)
        self.hint.setObjectName('CardHint')
        self.hint.setVisible(bool(hint))
        self._layout.addWidget(self.hint)

    def set_value(self, text, color=None):
        self.value.setText(str(text))
        self.value.setStyleSheet(f'color: {color};' if color else '')

    def set_hint(self, text, color=None):
        self.hint.setText(text or '')
        self.hint.setVisible(bool(text))
        self.hint.setStyleSheet(f'color: {color};' if color else '')

    def set_icon(self, icon_name, color=None):
        self.glyph.setPixmap(icons.pixmap(icon_name, color or PALETTE.text_dim, 15))


class KeyValueList(QWidget):
    """
    A two-column read-out.

    Used for topic details and recording summaries, where the field set is
    fixed and only the values change.
    """

    def __init__(self, parent=None, key_width=132, spacing=SPACE_SM):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(SPACE_MD)
        self._grid.setVerticalSpacing(spacing)
        self._grid.setColumnMinimumWidth(0, key_width)
        self._grid.setColumnStretch(1, 1)
        self._rows = {}

    def set(self, key, value, color=None, mono=True, tooltip=''):
        row = self._rows.get(key)
        if row is None:
            index = self._grid.rowCount()
            name = QLabel(key)
            name.setObjectName('CardLabel')
            name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label = QLabel()
            value_label.setObjectName('Mono' if mono else '')
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._grid.addWidget(name, index, 0)
            self._grid.addWidget(value_label, index, 1)
            row = (name, value_label)
            self._rows[key] = row
        _name, value_label = row
        value_label.setText(str(value))
        value_label.setStyleSheet(f'color: {color};' if color else '')
        value_label.setToolTip(tooltip)
        return value_label

    def set_visible(self, key, visible):
        row = self._rows.get(key)
        if row:
            for widget in row:
                widget.setVisible(visible)

    def clear_values(self, placeholder=NA):
        for key in self._rows:
            self.set(key, placeholder)


class EmptyState(QWidget):
    """What a page shows when it has nothing to show. Never a blank rectangle."""

    def __init__(self, icon_name, title, body='', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_SM)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.addStretch(1)

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, PALETTE.text_dim, 36, width=1.4))
        glyph.setAlignment(Qt.AlignCenter)
        layout.addWidget(glyph)

        self.title = QLabel(title)
        self.title.setObjectName('EmptyTitle')
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        self.body = QLabel(body)
        self.body.setObjectName('EmptyBody')
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setVisible(bool(body))
        layout.addWidget(self.body)
        layout.addStretch(1)

    def set_text(self, title, body=''):
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))
