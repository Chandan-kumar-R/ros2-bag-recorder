"""
History: what has been recorded from this dashboard.

Lightweight by design - a JSON file of small records, no database.
"""
import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import NA, count, duration, human_bytes, timestamp
from rosbag_recorder_ui.core.theme import MONO_STACK, PALETTE, SPACE_MD, SPACE_SM
from rosbag_recorder_ui.views.base import Page
from rosbag_recorder_ui.widgets.cards import EmptyState, KeyValueList, SectionCard
from rosbag_recorder_ui.widgets.dialogs import confirm, show_error

COLUMNS = ('Date', 'Name', 'Duration', 'Topics', 'Messages', 'Size', 'Format', 'On disk')


class HistoryPage(Page):
    title_text = 'History'
    subtitle_text = 'Recordings made from this dashboard'

    def __init__(self, history, parent=None):
        super().__init__(scrollable=False, parent=parent)
        self._history = history
        self._rows = []

        self.summary = QLabel('')
        self.summary.setObjectName('CardHint')
        self.add_action(self.summary)

        refresh = QPushButton('  Refresh')
        refresh.setProperty('variant', 'subtle')
        refresh.setIcon(icons.icon('refresh', PALETTE.text_muted, 15))
        refresh.clicked.connect(self.reload)
        self.add_action(refresh)

        clear = QPushButton('  Clear')
        clear.setProperty('variant', 'subtle')
        clear.setIcon(icons.icon('trash', PALETTE.text_muted, 15))
        clear.clicked.connect(self._on_clear)
        self.add_action(clear)

        body = QHBoxLayout()
        body.setSpacing(SPACE_MD)
        body.addWidget(self._build_table(), 3)
        body.addWidget(self._build_detail(), 1)
        self.content.addLayout(body, 1)

        self.reload()

    def _build_table(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5, 6, 7):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selected)
        layout.addWidget(self.table, 1)

        self.empty = EmptyState(
            'history', 'No recordings yet',
            'Recordings started from this dashboard are listed here, newest first.')
        layout.addWidget(self.empty, 1)
        return holder

    def _build_detail(self):
        card = SectionCard('Recording detail', '', 'bag', tone='flush')
        self.detail_empty = QLabel('Select a recording.')
        self.detail_empty.setObjectName('CardHint')
        card.body.addWidget(self.detail_empty)

        self.details = KeyValueList(key_width=90)
        for key in ('Name', 'Started', 'Duration', 'Topics', 'Messages', 'Size',
                    'Location'):
            self.details.set(key, NA)
        self.details.setVisible(False)
        card.body.addWidget(self.details)

        self.uri_list = QVBoxLayout()
        self.uri_list.setSpacing(4)
        card.body.addLayout(self.uri_list)
        self._uri_widgets = []

        # Recordings made before this list was kept have no topic names on
        # record, so the whole block hides rather than claiming zero topics.
        self.topics_title = QLabel('TOPICS IN THIS BAG')
        self.topics_title.setObjectName('CardLabel')
        self.topics_title.setVisible(False)
        card.body.addWidget(self.topics_title)
        self.topic_list = QPlainTextEdit()
        self.topic_list.setReadOnly(True)
        self.topic_list.setMaximumHeight(150)
        self.topic_list.setVisible(False)
        self.topic_list.setStyleSheet(
            f'font-family: {MONO_STACK}; font-size: 11px; '
            f'background: {PALETTE.bg_sunken};')
        card.body.addWidget(self.topic_list)

        card.body.addStretch(1)

        self.open_button = QPushButton('  Open containing folder')
        self.open_button.setProperty('variant', 'subtle')
        self.open_button.setIcon(icons.icon('folder', PALETTE.text_muted, 15))
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_folder)
        card.body.addWidget(self.open_button)

        self.forget_button = QPushButton('  Remove from history')
        self.forget_button.setProperty('variant', 'ghost')
        self.forget_button.setIcon(icons.icon('trash', PALETTE.text_muted, 14))
        self.forget_button.setEnabled(False)
        self.forget_button.setToolTip('Removes the entry only. The bag on disk is '
                                      'never deleted by this dashboard.')
        self.forget_button.clicked.connect(self._forget)
        card.body.addWidget(self.forget_button)

        # Docked on the right, like the topic detail, so both pages read the
        # same way: table on the page plane, detail on its own.
        holder = QWidget()
        holder.setObjectName('SidePanel')
        holder.setMinimumWidth(300)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.addWidget(card)
        return holder

    # ------------------------------------------------------------------

    def on_shown(self):
        self.reload()

    def reload(self):
        self._rows = self._history.entries()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for entry in self._rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            present = entry.get('present')
            values = (
                timestamp(entry.get('started', 0)),
                entry.get('name', NA),
                duration(entry.get('duration', -1)),
                count(entry.get('topics', -1)),
                count(entry.get('messages', -1)),
                human_bytes(entry.get('size', -1)),
                ' + '.join(f.upper() for f in entry.get('formats', [])) or NA,
                'yes' if present else 'missing',
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (2, 3, 4, 5):
                    item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                if column == 7 and not present:
                    item.setForeground(QColor(PALETTE.text_dim))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)

        has_rows = bool(self._rows)
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        total = sum(e.get('size', 0) for e in self._rows if e.get('present'))
        self.summary.setText(
            f'{len(self._rows)} recording(s) · {human_bytes(total)} still on disk'
            if has_rows else '')

    def _selected_entry(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() \
            else []
        if not rows:
            return None
        name_item = self.table.item(rows[0].row(), 1)
        date_item = self.table.item(rows[0].row(), 0)
        if name_item is None:
            return None
        for entry in self._rows:
            if entry.get('name') == name_item.text() and \
                    timestamp(entry.get('started', 0)) == date_item.text():
                return entry
        return None

    def _on_selected(self):
        entry = self._selected_entry()
        for widget in self._uri_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._uri_widgets = []

        if entry is None:
            self.details.setVisible(False)
            self.detail_empty.setVisible(True)
            self.topics_title.setVisible(False)
            self.topic_list.setVisible(False)
            self.open_button.setEnabled(False)
            self.forget_button.setEnabled(False)
            return

        self.detail_empty.setVisible(False)
        self.details.setVisible(True)
        self.details.set('Name', entry.get('name', NA))
        self.details.set('Started', timestamp(entry.get('started', 0),
                                              '%Y-%m-%d %H:%M:%S'))
        self.details.set('Duration', duration(entry.get('duration', -1)))
        self.details.set('Topics', count(entry.get('topics', -1)))
        self.details.set('Messages', count(entry.get('messages', -1)))
        self.details.set('Size', human_bytes(entry.get('size', -1)))
        self.details.set('Location', entry.get('path', NA))

        for uri in entry.get('uris', []):
            exists = os.path.exists(uri)
            label = QLabel(('✓  ' if exists else '✗  ') + os.path.basename(uri))
            label.setObjectName('Mono')
            label.setWordWrap(True)
            label.setToolTip(uri)
            label.setStyleSheet(
                f'color: {PALETTE.success if exists else PALETTE.text_dim}; '
                'font-size: 11px;')
            self.uri_list.addWidget(label)
            self._uri_widgets.append(label)

        recorded = entry.get('recorded_topics') or []
        self.topics_title.setText(f'TOPICS IN THIS BAG ({len(recorded)})')
        self.topics_title.setVisible(bool(recorded))
        self.topic_list.setVisible(bool(recorded))
        if recorded:
            lines = list(recorded)
            for name in entry.get('failed_topics') or []:
                lines.append(f'{name}    (not recorded: type unavailable)')
            for name in entry.get('lost_topics') or []:
                lines.append(f'{name}    (stopped publishing)')
            self.topic_list.setPlainText('\n'.join(lines))

        self.open_button.setEnabled(bool(entry.get('present')))
        self.forget_button.setEnabled(True)

    def _open_folder(self):
        entry = self._selected_entry()
        if entry is None:
            return
        path = entry.get('path') or os.path.dirname((entry.get('uris') or [''])[0])
        if not path or not os.path.isdir(path):
            show_error(self, 'That folder is not here',
                       f'{path} does not exist on this machine. If the bridge runs '
                       'on the robot, the bag is on the robot.')
            return
        try:
            subprocess.Popen(['xdg-open', path])
        except OSError as err:
            show_error(self, 'Could not open the folder', str(err))

    def _forget(self):
        entry = self._selected_entry()
        if entry is None:
            return
        if not confirm(self, 'Remove this entry?',
                       'The entry disappears from the history list. The bag files on '
                       'disk are not touched.', confirm_text='Remove'):
            return
        self._history.remove(entry.get('started'), entry.get('name'))
        self.reload()

    def _on_clear(self):
        if not self._rows:
            return
        if not confirm(self, 'Clear the whole history?',
                       'Every entry is removed from the list. No bag files are '
                       'deleted.', confirm_text='Clear history'):
            return
        self._history.clear()
        self.reload()
