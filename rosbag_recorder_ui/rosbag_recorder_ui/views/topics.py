"""
Topics: the live view of the ROS graph and what the current selection does to it.
"""
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_msgs.msg import TopicStat

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import NA, count, human_hz, human_rate, short_type
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_MD, SPACE_SM, SPACE_XS  # noqa: F401
from rosbag_recorder_ui.views.base import Page
from rosbag_recorder_ui.widgets.cards import Card, EmptyState, KeyValueList, SectionCard

STATE_META = {
    TopicStat.STATE_UNSELECTED: ('Not selected', PALETTE.topic_unselected),
    TopicStat.STATE_SELECTED: ('Will record', PALETTE.topic_selected),
    TopicStat.STATE_EXCLUDED: ('Excluded', PALETTE.topic_excluded),
    TopicStat.STATE_RECORDING: ('Recording', PALETTE.topic_recording),
    TopicStat.STATE_FAILED: ('Type failed', PALETTE.topic_failed),
    TopicStat.STATE_LOST: ('Lost', PALETTE.topic_lost),
}

# Headers are kept short so the topic name, the one column that must stay
# readable, keeps the space the Stretch mode gives it.
COLUMNS = ('Topic', 'Type', 'Hz', 'Bytes/s', 'QoS', 'Pub', 'Msgs', 'Record')
RECORD_COLUMN = len(COLUMNS) - 1

_dot_cache = {}


def dot_icon(color, size=10):
    key = (color, size)
    if key not in _dot_cache:
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(size // 2, size // 2, size, size)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        _dot_cache[key] = QIcon(pixmap)
    return _dot_cache[key]


class TopicModel(QAbstractTableModel):
    """
    Rows are TopicStat messages, kept in the order the bridge sent them.

    In manual selection mode the Record column becomes a checkbox. The model
    holds the ticked set locally so a click is reflected instantly, rather than
    waiting a second for the bridge's next statistics message to come back.
    """

    manual_toggled = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._names = []
        self._manual_mode = False
        self._manual = set()

    def set_manual(self, enabled, topics):
        """Switch the checkbox column on or off and set what is ticked."""
        topics = set(topics)
        if enabled == self._manual_mode and topics == self._manual:
            return
        self._manual_mode = enabled
        self._manual = topics
        if self._rows:
            self.dataChanged.emit(self.index(0, RECORD_COLUMN),
                                  self.index(len(self._rows) - 1, RECORD_COLUMN))
            self.headerDataChanged.emit(Qt.Horizontal, RECORD_COLUMN, RECORD_COLUMN)

    @property
    def manual_mode(self):
        return self._manual_mode

    def flags(self, index):
        flags = super().flags(index)
        if self._manual_mode and index.column() == RECORD_COLUMN:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or not self._manual_mode \
                or index.column() != RECORD_COLUMN:
            return False
        stat = self._rows[index.row()]
        ticked = Qt.CheckState(value) == Qt.Checked
        if ticked:
            self._manual.add(stat.name)
        else:
            self._manual.discard(stat.name)
        self.dataChanged.emit(index, index)
        self.manual_toggled.emit(stat.name, ticked)
        return True

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def stat(self, row):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        stat = self._rows[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return (
                stat.name,
                short_type(stat.type),
                human_hz(stat.hz),
                human_rate(stat.bytes_per_sec),
                self._qos_summary(stat),
                str(stat.publisher_count) if stat.publisher_count >= 0 else NA,
                count(stat.message_count),
                STATE_META.get(stat.state, ('?', PALETTE.text_dim))[0],
            )[column]

        if role == Qt.CheckStateRole and column == RECORD_COLUMN and self._manual_mode:
            return Qt.Checked if stat.name in self._manual else Qt.Unchecked

        if role == Qt.DecorationRole and column == 0:
            return dot_icon(STATE_META.get(stat.state,
                                           ('', PALETTE.text_dim))[1])

        if role == Qt.ForegroundRole:
            color = STATE_META.get(stat.state, ('', PALETTE.text_dim))[1]
            if column == len(COLUMNS) - 1:
                return QColor(color)
            if stat.state == TopicStat.STATE_UNSELECTED:
                return QColor(PALETTE.text_muted)
            if stat.state in (TopicStat.STATE_FAILED, TopicStat.STATE_LOST):
                return QColor(color)
            return QColor(PALETTE.text)

        if role == Qt.TextAlignmentRole and column in (2, 3, 5, 6):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ToolTipRole:
            bits = [stat.name, stat.type or 'type unknown']
            if stat.state == TopicStat.STATE_FAILED:
                bits.append('The message type could not be imported on the recording '
                            'machine, so this topic will be skipped.')
            elif stat.state == TopicStat.STATE_LOST:
                bits.append('This topic was being recorded but has stopped publishing.')
            elif stat.state == TopicStat.STATE_EXCLUDED:
                bits.append('Matched by the selection, then removed by an exclude '
                            'pattern.')
            if stat.newly_discovered:
                bits.append('Newly discovered.')
            return '\n'.join(bits)

        if role == Qt.UserRole:
            return stat.state
        if role == Qt.UserRole + 1:
            return stat.name
        # Sorting keys, so 'N/A' does not sort between numbers.
        if role == Qt.UserRole + 2:
            return {2: stat.hz, 3: stat.bytes_per_sec, 5: float(stat.publisher_count),
                    6: float(stat.message_count)}.get(column)
        return None

    @staticmethod
    def _qos_summary(stat):
        if not stat.reliability:
            return NA
        short = {'BEST_EFFORT': 'BE', 'RELIABLE': 'REL', 'SYSTEM_DEFAULT': 'SYS'}
        durable = {'TRANSIENT_LOCAL': ' · TL', 'VOLATILE': '', 'SYSTEM_DEFAULT': ''}
        return short.get(stat.reliability, stat.reliability) + \
            durable.get(stat.durability, '')

    def manual_topics(self):
        return set(self._manual)

    def update(self, stats):
        """
        Replace the contents.

        The common case - same topics, new numbers - avoids a model reset so
        the user's selection and scroll position survive the refresh.
        """
        names = [s.name for s in stats]
        if names == self._names:
            self._rows = list(stats)
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom)
            return False
        self.beginResetModel()
        self._rows = list(stats)
        self._names = names
        self.endResetModel()
        return True

    def row_of(self, name):
        try:
            return self._names.index(name)
        except ValueError:
            return -1


class TopicFilter(QSortFilterProxyModel):
    """Text search plus a state chip filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ''
        self.states = None       # None means 'any'
        self.setSortRole(Qt.UserRole + 2)

    def set_text(self, text):
        self.text = text.strip().lower()
        self.invalidateFilter()

    def set_states(self, states):
        self.states = states
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        stat = model.stat(row)
        if stat is None:
            return False
        if self.states is not None and stat.state not in self.states:
            return False
        if self.text:
            haystack = f'{stat.name} {stat.type}'.lower()
            if self.text not in haystack:
                return False
        return True

    def lessThan(self, left, right):
        left_key = self.sourceModel().data(left, Qt.UserRole + 2)
        right_key = self.sourceModel().data(right, Qt.UserRole + 2)
        if left_key is None or right_key is None:
            return super().lessThan(left, right)
        return left_key < right_key


class TopicsPage(Page):
    title_text = 'Topics'
    subtitle_text = 'Live ROS 2 graph and what the current selection captures'

    # (enabled, topics). An empty list with enabled=True means 'everything the
    # current selection matches', which is what the bridge's service expects.
    rate_monitor_requested = Signal(bool, list)
    manual_topic_toggled = Signal(str, bool)   # one topic ticked or unticked
    manual_topics_set = Signal(list)           # bulk replace of the ticked set
    manual_mode_requested = Signal(list)       # switch to manual, seeded with these

    FILTERS = (
        ('all', 'All', None),
        ('record', 'Will record', {TopicStat.STATE_SELECTED, TopicStat.STATE_RECORDING}),
        ('excluded', 'Excluded', {TopicStat.STATE_EXCLUDED}),
        ('problems', 'Problems', {TopicStat.STATE_FAILED, TopicStat.STATE_LOST}),
        ('idle', 'Not selected', {TopicStat.STATE_UNSELECTED}),
    )

    def __init__(self, parent=None):
        super().__init__(scrollable=False, parent=parent)
        self._selected_name = ''
        self._have_data = False
        self._probe_all = False
        self._probe_topics = set()   # topics probed one at a time, by name

        self.summary_label = QLabel('')
        self.summary_label.setObjectName('CardHint')
        self.add_action(self.summary_label)

        self.rate_button = QPushButton('  Measure rates')
        self.rate_button.setCheckable(True)
        self.rate_button.setProperty('variant', 'ghost')
        self.rate_button.setIcon(icons.icon('wave', PALETTE.text_muted, 15))
        self.rate_button.setToolTip(
            'Attach lightweight probes so idle topics report a frequency.\n'
            'Probes read raw bytes and never decode a message, but they are still\n'
            'real subscriptions - leave this off on a loaded robot, and measure\n'
            'one topic at a time from the detail panel instead.')
        self.rate_button.toggled.connect(self._on_rate_toggled)
        self.add_action(self.rate_button)

        self.manual_button = QPushButton('  Pick topics')
        self.manual_button.setCheckable(True)
        self.manual_button.setProperty('variant', 'ghost')
        self.manual_button.setIcon(icons.icon('check', PALETTE.text_muted, 15))
        self.manual_button.setToolTip(
            'Switch to manual selection and tick topics directly in this table.\n'
            'Turning it on starts from whatever the current selection already '
            'matches, so you can refine rather than start over.')
        self.manual_button.clicked.connect(self._on_manual_button)
        self.add_action(self.manual_button)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_table_side())
        splitter.addWidget(self._build_detail_side())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([980, 340])
        self.content.addWidget(splitter, 1)

    def _build_table_side(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(SPACE_XS + 2)
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('Search topics and types…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search, 1)

        self._filter_buttons = {}
        for key, label, states in self.FILTERS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty('variant', 'ghost')
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(key == 'all')
            button.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            button.setStyleSheet('font-size: 12px;')
            self._filter_buttons[key] = button
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        # Bulk actions, only meaningful while ticking topics by hand.
        self.bulk_bar = QWidget()
        bulk = QHBoxLayout(self.bulk_bar)
        bulk.setContentsMargins(0, 0, 0, 0)
        bulk.setSpacing(SPACE_XS + 2)
        self.bulk_hint = QLabel('')
        self.bulk_hint.setObjectName('CardHint')
        bulk.addWidget(self.bulk_hint)
        bulk.addStretch(1)
        for label, handler, tip in (
                ('Tick all shown', self._tick_shown,
                 'Tick every topic currently visible under the search and filter.'),
                ('Untick all shown', self._untick_shown,
                 'Untick every topic currently visible.'),
                ('Clear selection', self._clear_manual,
                 'Untick everything, including rows hidden by the filter.')):
            button = QPushButton(label)
            button.setProperty('variant', 'ghost')
            button.setStyleSheet('font-size: 12px;')
            button.setToolTip(tip)
            button.clicked.connect(handler)
            bulk.addWidget(button)
        self.bulk_bar.setVisible(False)
        layout.addWidget(self.bulk_bar)

        self.model = TopicModel(self)
        self.proxy = TopicFilter(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        # Every column but the name is Interactive at a fixed starting width, so
        # the Stretch on column 0 always has room left over to claim. Making the
        # others ResizeToContents lets a long type name squeeze the topic name
        # down to an ellipsis, which is the one thing that must stay readable.
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(48)
        # The Record column carries a checkbox in manual mode, so it is sized
        # for checkbox plus the longest label ('Not selected').
        for column, width in enumerate((0, 162, 52, 78, 70, 42, 66, 132)):
            if column:
                self.table.setColumnWidth(column, width)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setWordWrap(False)
        # Topic names differ in the middle ('/camera/left/image' against
        # '/camera/right/image'), so clipping the tail would hide exactly the
        # part that tells them apart.
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self.model.manual_toggled.connect(self._on_manual_toggled)
        layout.addWidget(self.table, 1)

        self.empty = EmptyState(
            'topics', 'No topics yet',
            'Waiting for the recorder bridge to report the ROS 2 graph. Start it with:\n'
            'ros2 launch rosbag_recorder_bridge bridge.launch.py')
        layout.addWidget(self.empty, 1)
        self.table.setVisible(False)

        layout.addWidget(self._build_legend())
        return holder

    def _build_legend(self):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(SPACE_MD)
        for state, (label, color) in STATE_META.items():
            chip = QLabel(f'●  {label}')
            chip.setStyleSheet(f'color: {color}; font-size: 11px;')
            layout.addWidget(chip)
        layout.addStretch(1)
        return row

    def _build_detail_side(self):
        holder = QWidget()
        holder.setObjectName('SidePanel')
        holder.setMinimumWidth(320)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.setSpacing(SPACE_MD)

        self.detail_card = SectionCard('Topic detail', '', 'eye', tone='flush')
        self.detail_empty = QLabel('Select a topic to inspect it.')
        self.detail_empty.setObjectName('CardHint')
        self.detail_card.body.addWidget(self.detail_empty)

        self.detail_name = QLabel('')
        self.detail_name.setObjectName('Mono')
        self.detail_name.setWordWrap(True)
        self.detail_name.setStyleSheet('font-size: 14px; font-weight: 600;')
        self.detail_name.setVisible(False)
        self.detail_card.body.addWidget(self.detail_name)

        self.detail_state = QLabel('')
        self.detail_state.setVisible(False)
        self.detail_card.body.addWidget(self.detail_state)

        self.details = KeyValueList(key_width=104)
        for key in ('Message type', 'Publishers', 'Subscribers', 'Frequency',
                    'Bandwidth', 'Messages', 'Reliability', 'Durability', 'History',
                    'Depth', 'Recording'):
            self.details.set(key, NA)
        self.details.setVisible(False)
        self.detail_card.body.addWidget(self.details)

        self.probe_button = QPushButton('  Measure this topic')
        self.probe_button.setCheckable(True)
        self.probe_button.setProperty('variant', 'subtle')
        self.probe_button.setIcon(icons.icon('wave', PALETTE.text_muted, 14))
        self.probe_button.setEnabled(False)
        self.probe_button.setVisible(False)
        self.probe_button.toggled.connect(self._on_probe_one)
        self.detail_card.body.addWidget(self.probe_button)

        self.detail_card.body.addStretch(1)
        layout.addWidget(self.detail_card, 1)

        note = Card(padding=SPACE_MD)
        note_label = QLabel(
            'Frequencies are measured by the bridge. Topics being recorded report the '
            'recorder\'s own message counters; other topics show N/A unless rate '
            'measurement is switched on.')
        note_label.setObjectName('CardHint')
        note_label.setWordWrap(True)
        note.layout().addWidget(note_label)
        layout.addWidget(note)
        return holder

    # ------------------------------------------------------------------

    def _on_search(self, text):
        self.proxy.set_text(text)
        self._update_summary()

    def _set_filter(self, key):
        for name, button in self._filter_buttons.items():
            button.setChecked(name == key)
        states = dict((k, s) for k, _l, s in self.FILTERS)[key]
        self.proxy.set_states(states)
        self._update_summary()

    def _on_rate_toggled(self, enabled):
        self._probe_all = enabled
        self.rate_button.setText('  Measuring rates' if enabled else '  Measure rates')
        self._request_probes()

    def _request_probes(self):
        """
        Ask for exactly the probes the page currently wants.

        The service replaces the whole probe set on every call, so 'all
        selected plus these two' has to be sent as one explicit list rather
        than as two calls that would each undo the other.
        """
        if self._probe_all and not self._probe_topics:
            self.rate_monitor_requested.emit(True, [])
        elif self._probe_all:
            selected = {self.model.stat(row).name
                        for row in range(self.model.rowCount())
                        if self.model.stat(row).state in (TopicStat.STATE_SELECTED,
                                                          TopicStat.STATE_RECORDING)}
            self.rate_monitor_requested.emit(True, sorted(selected | self._probe_topics))
        elif self._probe_topics:
            self.rate_monitor_requested.emit(True, sorted(self._probe_topics))
        else:
            self.rate_monitor_requested.emit(False, [])

    def _on_probe_one(self, wanted):
        name = self._selected_name
        if not name:
            return
        if wanted:
            self._probe_topics.add(name)
        else:
            self._probe_topics.discard(name)
        self._sync_probe_button()
        self._request_probes()

    def _sync_probe_button(self):
        """Match the detail-panel button to the selected topic's probe state."""
        name = self._selected_name
        row = self.model.row_of(name) if name else -1
        stat = self.model.stat(row) if row >= 0 else None
        if stat is None:
            self.probe_button.setEnabled(False)
            self.probe_button.setText('  Measure this topic')
            self.probe_button.setToolTip('')
            return
        counted = stat.state == TopicStat.STATE_RECORDING
        self.probe_button.setEnabled(not counted)
        self.probe_button.setToolTip(
            'This topic is being recorded, so its rate already comes from the '
            "recorder's own counters - a probe would only duplicate it."
            if counted else
            'Attach a raw byte-counting probe to this one topic. It is a real '
            'DDS subscription, but it never decodes a message.')
        self.probe_button.blockSignals(True)
        self.probe_button.setChecked(name in self._probe_topics)
        self.probe_button.blockSignals(False)
        self.probe_button.setText('  Measuring this topic' if name in self._probe_topics
                                  else '  Measure this topic')

    # ------------------------------------------------------------------
    #  Manual selection
    # ------------------------------------------------------------------

    def _on_manual_button(self):
        if self.manual_button.isChecked():
            # Seed from what the current mode already matches, so switching to
            # manual is a refinement step rather than starting from nothing.
            seed = [self.model.stat(row).name for row in range(self.model.rowCount())
                    if self.model.stat(row).state in (TopicStat.STATE_SELECTED,
                                                      TopicStat.STATE_RECORDING)]
            self.manual_mode_requested.emit(sorted(seed))
        else:
            # Unticking the button hands control back to the Configuration page.
            self.manual_mode_requested.emit([])

    def _on_manual_toggled(self, name, ticked):
        self.manual_topic_toggled.emit(name, ticked)

    def _visible_names(self):
        return [self.proxy.data(self.proxy.index(row, 0), Qt.UserRole + 1)
                for row in range(self.proxy.rowCount())]

    def _tick_shown(self):
        self.manual_topics_set.emit(
            sorted(self.model.manual_topics() | set(self._visible_names())))

    def _untick_shown(self):
        self.manual_topics_set.emit(
            sorted(self.model.manual_topics() - set(self._visible_names())))

    def _clear_manual(self):
        self.manual_topics_set.emit([])

    def apply_config(self, config):
        """Mirror the selection mode and ticked set from the shared config."""
        manual = config.selection_method == 'manual'
        self.model.set_manual(manual, config.manual_topics)
        self.bulk_bar.setVisible(manual)
        if self.manual_button.isChecked() != manual:
            self.manual_button.blockSignals(True)
            self.manual_button.setChecked(manual)
            self.manual_button.blockSignals(False)
        self.manual_button.setText('  Picking topics' if manual else '  Pick topics')
        self._update_summary()

    def _on_row_selected(self, *_args):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        source = self.proxy.mapToSource(indexes[0])
        stat = self.model.stat(source.row())
        if stat is not None:
            self._selected_name = stat.name
            self._show_detail(stat)

    def _show_detail(self, stat):
        self.detail_empty.setVisible(False)
        self.detail_name.setVisible(True)
        self.detail_state.setVisible(True)
        self.details.setVisible(True)
        self.probe_button.setVisible(True)

        label, color = STATE_META.get(stat.state, ('Unknown', PALETTE.text_dim))
        self.detail_name.setText(stat.name)
        self.detail_state.setText(f'●  {label}')
        self.detail_state.setStyleSheet(f'color: {color}; font-weight: 600;')

        self.details.set('Message type', stat.type or NA)
        self.details.set('Publishers', str(stat.publisher_count)
                         if stat.publisher_count >= 0 else NA)
        self.details.set('Subscribers', str(stat.subscriber_count)
                         if stat.subscriber_count >= 0 else NA)
        self.details.set('Frequency', human_hz(stat.hz))
        self.details.set('Bandwidth', human_rate(stat.bytes_per_sec))
        self.details.set('Messages', count(stat.message_count))
        self.details.set('Reliability', stat.reliability or NA,
                         PALETTE.warning if stat.reliability == 'BEST_EFFORT' else None)
        self.details.set('Durability', stat.durability or NA)
        self.details.set('History', stat.history or NA)
        self.details.set('Depth', str(stat.depth) if stat.depth >= 0 else NA)
        recording = {
            TopicStat.STATE_RECORDING: ('ENABLED · active', PALETTE.topic_recording),
            TopicStat.STATE_SELECTED: ('ENABLED', PALETTE.topic_selected),
            TopicStat.STATE_EXCLUDED: ('DISABLED · excluded', PALETTE.topic_excluded),
            TopicStat.STATE_FAILED: ('UNAVAILABLE · type not installed',
                                     PALETTE.topic_failed),
            TopicStat.STATE_LOST: ('ENABLED · publisher gone', PALETTE.topic_lost),
        }.get(stat.state, ('DISABLED', PALETTE.text_muted))
        self.details.set('Recording', recording[0], recording[1])
        self._sync_probe_button()

    # ------------------------------------------------------------------

    def on_topic_stats(self, stats):
        topics = list(stats.topics)
        self._have_data = True
        self.empty.setVisible(not topics)
        self.table.setVisible(bool(topics))

        was_reset = self.model.update(topics)
        if was_reset and self._selected_name:
            row = self.model.row_of(self._selected_name)
            if row >= 0:
                proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
                if proxy_index.isValid():
                    self.table.selectRow(proxy_index.row())
        if self._selected_name:
            row = self.model.row_of(self._selected_name)
            if row >= 0:
                self._show_detail(self.model.stat(row))

        # Keep the page's idea of what is probed in step with the graph, and
        # re-issue the request when the selection itself changed underneath a
        # 'measure everything selected'.
        live = {stat.name for stat in topics}
        stale = self._probe_topics - live
        if stale:
            self._probe_topics -= stale
            self._request_probes()
        self._update_summary()

    def _update_summary(self):
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        by_state = {}
        for row in range(total):
            stat = self.model.stat(row)
            by_state[stat.state] = by_state.get(stat.state, 0) + 1
        recording = by_state.get(TopicStat.STATE_RECORDING, 0)
        selected = by_state.get(TopicStat.STATE_SELECTED, 0)
        bits = [f'{shown} of {total} shown']
        if recording:
            bits.append(f'{recording} recording')
        elif selected:
            bits.append(f'{selected} will record')
        failed = by_state.get(TopicStat.STATE_FAILED, 0)
        if failed:
            bits.append(f'{failed} failed')
        self.summary_label.setText(' · '.join(bits))

        if self.model.manual_mode:
            ticked = len(self.model.manual_topics())
            missing = len(self.model.manual_topics()
                          - {self.model.stat(r).name for r in range(total)})
            hint = f'{ticked} topic(s) ticked'
            if missing:
                hint += f' · {missing} not currently on the graph'
            self.bulk_hint.setText(hint)

    def set_connection(self, ros_online, bridge_online):
        if not bridge_online and self._have_data:
            self.empty.set_text(
                'Connection to the bridge lost',
                'The topic list below is the last one received and is no longer live.')
