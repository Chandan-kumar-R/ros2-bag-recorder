"""Common page scaffolding: title block, optional scroll area, action row."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core.theme import SPACE_LG, SPACE_MD, SPACE_XL


class Page(QWidget):
    """
    A dashboard page.

    Subclasses add widgets to ``self.content`` (a QVBoxLayout). Set
    ``scrollable=False`` for pages whose main widget should take all the
    height itself, such as the topic table.
    """

    title_text = 'Page'
    subtitle_text = ''

    def __init__(self, title=None, subtitle=None, scrollable=True, parent=None):
        super().__init__(parent)
        self.title_text = title or self.title_text
        self.subtitle_text = subtitle if subtitle is not None else self.subtitle_text

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE_XL, SPACE_LG, SPACE_XL, SPACE_LG)
        outer.setSpacing(SPACE_MD)

        header = QHBoxLayout()
        header.setSpacing(SPACE_MD)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(self.title_text)
        self.title_label.setObjectName('PageTitle')
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(self.subtitle_text)
        self.subtitle_label.setObjectName('PageSubtitle')
        self.subtitle_label.setVisible(bool(self.subtitle_text))
        titles.addWidget(self.subtitle_label)
        header.addLayout(titles)
        header.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(SPACE_MD - 6)
        header.addLayout(self.actions)
        outer.addLayout(header)

        if scrollable:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            holder = QWidget()
            holder.setObjectName('Root')
            self.content = QVBoxLayout(holder)
            self.content.setContentsMargins(0, 0, 6, 0)
            self.content.setSpacing(SPACE_MD)
            area.setWidget(holder)
            outer.addWidget(area, 1)
        else:
            self.content = QVBoxLayout()
            self.content.setContentsMargins(0, 0, 0, 0)
            self.content.setSpacing(SPACE_MD)
            outer.addLayout(self.content, 1)

    def set_subtitle(self, text):
        self.subtitle_text = text
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def add_action(self, widget):
        self.actions.addWidget(widget)
        return widget

    # -- hooks ----------------------------------------------------------

    def on_shown(self):
        """React to the page becoming visible. Cheap by default."""

    def on_hidden(self):
        """React to the user navigating away."""

    def on_status(self, status):
        """Handle a new RecorderStatus."""

    def on_topic_stats(self, stats):
        """Handle new TopicStats."""


def card_grid(columns=4, spacing=SPACE_MD):
    grid = QGridLayout()
    grid.setSpacing(spacing)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return grid
