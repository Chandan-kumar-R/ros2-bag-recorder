"""
Recording:

The page has three faces, one per phase of a recording,

  configure -> a summary of exactly what is about to happen, and START
  monitor   -> the live read-out, and STOP
  complete  -> what was actually written, and where
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import (
    NA,
    count,
    duration,
    human_bytes,
    human_rate,
    short_duration,
)
from rosbag_recorder_ui.core.theme import (
    MONO_STACK,
    PALETTE,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
)
from rosbag_recorder_ui.views.base import Page, card_grid
from rosbag_recorder_ui.widgets.cards import Card, KeyValueList, SectionCard, StatCard
from rosbag_recorder_ui.widgets.dialogs import confirm, show_error
from rosbag_recorder_ui.widgets.indicators import Meter, RecordingBeacon, Sparkline

PHASE_CONFIGURE, PHASE_MONITOR, PHASE_COMPLETE = 0, 1, 2

# What rosbag2 calls each format, so an available_writers list coming back from
# the bridge can be matched against the two checkboxes on this page.
STORAGE_IDS = {'sqlite': 'sqlite3', 'mcap': 'mcap'}


class CheckRow(QWidget):
    """One pre-flight line: an icon, a label, and the reason it is or is not OK."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        self.glyph = QLabel()
        self.glyph.setFixedWidth(18)
        layout.addWidget(self.glyph)
        self.label = QLabel(label)
        self.label.setMinimumWidth(160)
        layout.addWidget(self.label)
        self.detail = QLabel('checking…')
        self.detail.setObjectName('CardHint')
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail, 1)
        self.set_state('pending', 'not checked yet')

    def set_state(self, state, detail=''):
        glyph, color = {
            'ok': ('check', PALETTE.success),
            'warning': ('warning', PALETTE.warning),
            'error': ('error', PALETTE.danger),
            'pending': ('clock', PALETTE.text_dim),
        }.get(state, ('info', PALETTE.text_dim))
        self.glyph.setPixmap(icons.pixmap(glyph, color, 15))
        text_color = PALETTE.text_muted if state == 'pending' else PALETTE.text
        self.label.setStyleSheet(f'color: {text_color};')
        self.detail.setText(detail)
        self.detail.setStyleSheet(f'color: {color};')
        self.state = state


class RecordingPage(Page):
    title_text = 'Recording'
    subtitle_text = 'Configure the output, then start'

    start_requested = Signal(object)     # RecordingConfig
    stop_requested = Signal()
    configure_requested = Signal()
    preview_requested = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent=parent)
        self._store = store
        self._syncing = False
        self._status = None
        self._preview = None
        self._validation = None
        self._summary = None
        # Empty means 'the bridge has not told us yet', which is not the same
        # as 'no storage plugins exist'. Nothing is disabled on an empty list.
        self._available_writers = []

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_configure())
        self.stack.addWidget(self._build_monitor())
        self.stack.addWidget(self._build_complete())
        self.content.addWidget(self.stack, 1)

        store.changed.connect(self._load_from_store)
        self._load_from_store(store.config)

    # ==================================================================
    #  Configure phase
    # ==================================================================

    def _build_configure(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)

        layout.addWidget(self._build_storage_card())

        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)
        row.addWidget(self._build_selection_card(), 3)
        row.addWidget(self._build_preflight_card(), 2)
        layout.addLayout(row)

        layout.addWidget(self._build_launch_card())
        layout.addStretch(1)
        return page

    def _build_storage_card(self):
        card = SectionCard('Storage', 'Where this recording is written on the '
                                      'recording machine', 'folder')
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE_MD)
        grid.setVerticalSpacing(SPACE_SM)
        grid.setColumnStretch(1, 1)

        grid.addWidget(self._field_label('Storage location'), 0, 0)
        path_row = QHBoxLayout()
        path_row.setSpacing(SPACE_SM)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('/data/rosbags')
        self.path_edit.setToolTip('This path is resolved on the machine running the '
                                  'recorder bridge, not necessarily this one.')
        self.path_edit.textEdited.connect(
            lambda text: self._push(bag_path=text))
        path_row.addWidget(self.path_edit, 1)
        browse = QPushButton('  Browse')
        browse.setIcon(icons.icon('open', PALETTE.text_muted, 15))
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        grid.addLayout(path_row, 0, 1)

        grid.addWidget(self._field_label('Bag name'), 1, 0)
        name_row = QHBoxLayout()
        name_row.setSpacing(SPACE_MD)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('mission_001')
        self.name_edit.textEdited.connect(lambda text: self._push(bag_name=text))
        name_row.addWidget(self.name_edit, 1)
        self.timestamp_check = QCheckBox('Append timestamp')
        self.timestamp_check.setToolTip(
            'Adds _YYYY-MM-DD_HH-MM-SS so a repeated run never collides.')
        self.timestamp_check.toggled.connect(
            lambda on: self._push(append_timestamp=on))
        name_row.addWidget(self.timestamp_check)
        grid.addLayout(name_row, 1, 1)

        grid.addWidget(self._field_label('Storage format'), 2, 0)
        format_row = QHBoxLayout()
        format_row.setSpacing(SPACE_LG)
        self.sqlite_check = QCheckBox('SQLite3')
        self.sqlite_check.toggled.connect(lambda on: self._push(storage_sqlite=on))
        self.mcap_check = QCheckBox('MCAP')
        self.mcap_check.toggled.connect(lambda on: self._push(storage_mcap=on))
        format_row.addWidget(self.sqlite_check)
        format_row.addWidget(self.mcap_check)
        self.format_hint = QLabel('Both can be written at once.')
        self.format_hint.setObjectName('CardHint')
        format_row.addWidget(self.format_hint)
        format_row.addStretch(1)
        grid.addLayout(format_row, 2, 1)

        card.body.addLayout(grid)

        self.resolved_label = QLabel('')
        self.resolved_label.setObjectName('CardHint')
        self.resolved_label.setWordWrap(True)
        card.body.addWidget(self.resolved_label)
        return card

    def _build_selection_card(self):
        card = SectionCard('Selection', 'What will be recorded', 'topics')
        edit = QPushButton('  Edit selection')
        edit.setProperty('variant', 'ghost')
        edit.setIcon(icons.icon('config', PALETTE.text_muted, 14))
        edit.clicked.connect(self.configure_requested)
        card.add_header_widget(edit)

        self.selection_details = KeyValueList(key_width=104)
        self.selection_details.set('Mode', NA)
        self.selection_details.set('Modules', NA)
        self.selection_details.set('Keywords', NA)
        self.selection_details.set('Ticked', NA)
        self.selection_details.set('Excluded', NA)
        card.body.addWidget(self.selection_details)

        matched = QHBoxLayout()
        matched.setSpacing(SPACE_SM)
        self.match_count = QLabel(NA)
        self.match_count.setObjectName('CardValue')
        matched.addWidget(self.match_count)
        matched_label = QVBoxLayout()
        matched_label.setSpacing(0)
        title = QLabel('topics matched right now')
        title.setObjectName('CardHint')
        matched_label.addWidget(title)
        self.match_detail = QLabel('')
        self.match_detail.setObjectName('CardHint')
        matched_label.addWidget(self.match_detail)
        matched.addLayout(matched_label)
        matched.addStretch(1)
        refresh = QPushButton()
        refresh.setProperty('variant', 'ghost')
        refresh.setIcon(icons.icon('refresh', PALETTE.text_muted, 15))
        refresh.setToolTip('Re-check the selection against the live graph')
        refresh.setFixedWidth(34)
        refresh.clicked.connect(self.preview_requested)
        matched.addWidget(refresh)
        card.body.addLayout(matched)

        # A count of selectors that match nothing is not actionable; the names
        # are. The bridge already sends them, so print them.
        self.unmatched_label = QLabel('')
        self.unmatched_label.setObjectName('CardHint')
        self.unmatched_label.setWordWrap(True)
        self.unmatched_label.setVisible(False)
        card.body.addWidget(self.unmatched_label)
        return card

    def _build_preflight_card(self):
        card = SectionCard('Pre-flight', 'Checked on the recording machine', 'check')
        self.check_ros = CheckRow('ROS 2 / bridge')
        self.check_path = CheckRow('Output path')
        self.check_collision = CheckRow('Name collision')
        self.check_disk = CheckRow('Disk space')
        self.check_selection = CheckRow('Topic selection')
        self.check_format = CheckRow('Storage format')
        for check in (self.check_ros, self.check_path, self.check_collision,
                      self.check_disk, self.check_selection, self.check_format):
            card.body.addWidget(check)

        # Whatever the bridge said that no single check above represents: its
        # own one-sentence verdict, and any non-fatal warnings.
        self.validation_note = QLabel('')
        self.validation_note.setObjectName('CardHint')
        self.validation_note.setWordWrap(True)
        self.validation_note.setVisible(False)
        card.body.addWidget(self.validation_note)

        card.body.addStretch(1)
        return card

    def _build_launch_card(self):
        card = Card(tone='')
        layout = QHBoxLayout()
        layout.setSpacing(SPACE_LG)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.launch_title = QLabel('Ready to record')
        self.launch_title.setStyleSheet('font-size: 15px; font-weight: 600;')
        text.addWidget(self.launch_title)
        self.launch_detail = QLabel('')
        self.launch_detail.setObjectName('CardHint')
        self.launch_detail.setWordWrap(True)
        text.addWidget(self.launch_detail)
        layout.addLayout(text, 1)

        self.start_button = QPushButton('  START RECORDING')
        self.start_button.setProperty('variant', 'record')
        self.start_button.setIcon(icons.icon('record', PALETTE.on_success, 17))
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.setMinimumWidth(230)
        self.start_button.clicked.connect(self._on_start_clicked)
        layout.addWidget(self.start_button)

        card.layout().addLayout(layout)
        self.launch_card = card
        return card

    @staticmethod
    def _field_label(text):
        label = QLabel(text.upper())
        label.setObjectName('CardLabel')
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return label

    # ==================================================================
    #  Monitor phase
    # ==================================================================

    def _build_monitor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)

        self.monitor_beacon = RecordingBeacon()
        layout.addWidget(self.monitor_beacon)

        grid = card_grid(4)
        self.m_duration = StatCard('Duration', NA, '', 'clock')
        self.m_size = StatCard('Bag size', NA, '', 'bag')
        self.m_topics = StatCard('Topics', NA, '', 'topics')
        self.m_messages = StatCard('Messages', NA, '', 'wave')
        for column, card in enumerate((self.m_duration, self.m_size,
                                       self.m_topics, self.m_messages)):
            grid.addWidget(card, 0, column)
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)

        rate_card = SectionCard('Recording rate', '', 'diagnostics')
        self.m_rate = QLabel(NA)
        self.m_rate.setObjectName('CardValue')
        rate_card.body.addWidget(self.m_rate)
        self.m_spark = Sparkline(color=PALETTE.recording)
        rate_card.body.addWidget(self.m_spark)
        row.addWidget(rate_card, 3)

        target_card = SectionCard('Writing to', '', 'folder')
        self.m_targets = KeyValueList(key_width=80)
        target_card.body.addWidget(self.m_targets)
        row.addWidget(target_card, 4)

        disk_card = SectionCard('Disk', '', 'disk')
        self.m_disk = Meter('Used')
        disk_card.body.addWidget(self.m_disk)
        self.m_disk_free = QLabel(NA)
        self.m_disk_free.setObjectName('CardValueSm')
        disk_card.body.addWidget(self.m_disk_free)
        free_hint = QLabel('free')
        free_hint.setObjectName('CardHint')
        disk_card.body.addWidget(free_hint)
        disk_card.body.addStretch(1)
        row.addWidget(disk_card, 2)
        layout.addLayout(row)

        problems = SectionCard('Warnings during this recording', '', 'warning')
        self.m_problems = QLabel('None so far.')
        self.m_problems.setObjectName('CardHint')
        self.m_problems.setWordWrap(True)
        problems.body.addWidget(self.m_problems)
        self.m_problems_card = problems
        layout.addWidget(problems)

        layout.addStretch(1)

        stop_card = Card()
        stop_row = QHBoxLayout()
        stop_row.setSpacing(SPACE_LG)
        stop_text = QVBoxLayout()
        stop_text.setSpacing(2)
        stop_title = QLabel('Finish this recording')
        stop_title.setStyleSheet('font-size: 15px; font-weight: 600;')
        stop_text.addWidget(stop_title)
        stop_hint = QLabel('The bag is only complete once the writers have been closed. '
                           'The dashboard waits for the bridge to confirm that.')
        stop_hint.setObjectName('CardHint')
        stop_hint.setWordWrap(True)
        stop_text.addWidget(stop_hint)
        stop_row.addLayout(stop_text, 1)

        self.stop_button = QPushButton('  STOP RECORDING')
        self.stop_button.setProperty('variant', 'stop')
        self.stop_button.setIcon(icons.icon('stop', PALETTE.on_danger, 16))
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setMinimumWidth(230)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        stop_row.addWidget(self.stop_button)
        stop_card.layout().addLayout(stop_row)
        layout.addWidget(stop_card)
        return page

    # ==================================================================
    #  Complete phase
    # ==================================================================

    def _build_complete(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_MD)

        banner = Card(tone='success')
        banner_row = QHBoxLayout()
        banner_row.setSpacing(SPACE_MD)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap('check', PALETTE.success, 26))
        banner_row.addWidget(glyph)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.done_title = QLabel('Recording completed')
        self.done_title.setStyleSheet(
            f'font-size: 17px; font-weight: 700; color: {PALETTE.success};')
        text.addWidget(self.done_title)
        self.done_subtitle = QLabel('')
        self.done_subtitle.setObjectName('CardHint')
        text.addWidget(self.done_subtitle)
        banner_row.addLayout(text, 1)
        banner.layout().addLayout(banner_row)
        layout.addWidget(banner)

        grid = card_grid(4)
        self.c_duration = StatCard('Duration', NA, '', 'clock')
        self.c_topics = StatCard('Topics', NA, '', 'topics')
        self.c_messages = StatCard('Messages', NA, '', 'wave')
        self.c_size = StatCard('Storage', NA, '', 'bag')
        for column, card in enumerate((self.c_duration, self.c_topics,
                                       self.c_messages, self.c_size)):
            grid.addWidget(card, 0, column)
        layout.addLayout(grid)

        output = SectionCard('Output', 'Written and closed', 'folder')
        self.c_outputs = KeyValueList(key_width=90)
        output.body.addWidget(self.c_outputs)
        layout.addWidget(output)

        # 'What was actually in that bag?' should not require opening the bag.
        self.c_topics_card = SectionCard('Recorded topics', '', 'topics')
        self.c_topic_list = QPlainTextEdit()
        self.c_topic_list.setReadOnly(True)
        self.c_topic_list.setMaximumHeight(160)
        self.c_topic_list.setStyleSheet(
            f'font-family: {MONO_STACK}; font-size: 12px; '
            f'background: {PALETTE.bg_sunken};')
        self.c_topics_card.body.addWidget(self.c_topic_list)
        layout.addWidget(self.c_topics_card)

        self.c_notes = SectionCard('Notes', '', 'info')
        self.c_notes_label = QLabel('')
        self.c_notes_label.setObjectName('CardHint')
        self.c_notes_label.setWordWrap(True)
        self.c_notes.body.addWidget(self.c_notes_label)
        layout.addWidget(self.c_notes)

        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        again = QPushButton('  Set up another recording')
        again.setProperty('variant', 'primary')
        again.setIcon(icons.icon('record', PALETTE.on_accent, 15))
        again.clicked.connect(lambda: self._set_phase(PHASE_CONFIGURE))
        actions.addWidget(again)
        layout.addLayout(actions)
        return page

    # ==================================================================
    #  State plumbing
    # ==================================================================

    def _push(self, **fields):
        if self._syncing:
            return
        self._store.update(**fields)
        self._update_resolved_name()
        self.preview_requested.emit()

    def _load_from_store(self, config):
        self._syncing = True
        try:
            self.path_edit.setText(config.bag_path)
            self.name_edit.setText(config.bag_name)
            self.timestamp_check.setChecked(config.append_timestamp)
            self.sqlite_check.setChecked(config.storage_sqlite)
            self.mcap_check.setChecked(config.storage_mcap)

            mode = {'keywords': 'Keywords', 'manual': 'Manual'}.get(
                config.selection_method, 'Registry')
            self.selection_details.set('Mode', mode)
            self.selection_details.set(
                'Modules', ', '.join(config.modules) or 'none enabled',
                None if config.modules else PALETTE.warning)
            self.selection_details.set(
                'Keywords', ', '.join(config.keywords) or 'none',
                None if config.keywords else PALETTE.text_dim)
            ticked = len(config.manual_topics)
            self.selection_details.set(
                'Ticked', f'{ticked} topic(s) picked by hand' if ticked
                else 'nothing ticked yet',
                None if ticked else PALETTE.warning)
            self.selection_details.set(
                'Excluded', ', '.join(config.exclude_patterns) or 'nothing excluded')
            self.selection_details.set_visible(
                'Modules', config.selection_method == 'registry')
            self.selection_details.set_visible(
                'Keywords', config.selection_method == 'keywords')
            self.selection_details.set_visible(
                'Ticked', config.selection_method == 'manual')
        finally:
            self._syncing = False
        self._update_resolved_name()
        self._refresh_checks()

    def _update_resolved_name(self):
        config = self._store.config
        suffixes = []
        if config.storage_sqlite:
            suffixes.append('_sqlite')
        if config.storage_mcap:
            suffixes.append('_mcap')
        stamp = '_<timestamp>' if config.append_timestamp else ''
        if not suffixes:
            self.resolved_label.setText('No storage format selected.')
            self.resolved_label.setStyleSheet(f'color: {PALETTE.warning};')
            return
        targets = ', '.join(
            os.path.join(config.bag_path or '~/rosbags',
                         f'{config.bag_name or "recording"}{stamp}{suffix}')
            for suffix in suffixes)
        self.resolved_label.setText(f'Will write: {targets}')
        self.resolved_label.setStyleSheet(f'color: {PALETTE.text_dim};')

    def _browse(self):
        start = self._store.config.bag_path or os.path.expanduser('~')
        chosen = QFileDialog.getExistingDirectory(self, 'Choose where bags are written',
                                                  os.path.expanduser(start))
        if chosen:
            self.path_edit.setText(chosen)
            self._push(bag_path=chosen)

    def _browse_hint(self):
        return 'Paths are resolved on the recording machine.'

    # -- external updates ------------------------------------------------

    def set_connection(self, ros_online, bridge_online):
        self._bridge_online = bridge_online
        if not bridge_online:
            self.check_ros.set_state('error', 'the recorder bridge is not running')
        else:
            self.check_ros.set_state('ok', 'connected')
        self._refresh_checks()

    def set_preview(self, response, error=''):
        self._preview = response if error == '' else None
        if error or response is None or not response.success:
            self._show_unmatched([])
        if error:
            self.match_count.setText(NA)
            self.match_detail.setText(error)
            self.match_detail.setStyleSheet(f'color: {PALETTE.warning};')
            self.check_selection.set_state('error', error)
        elif response is None:
            self.check_selection.set_state('pending', 'not checked yet')
        elif not response.success:
            self.match_count.setText('0')
            self.match_detail.setText(response.message)
            self.check_selection.set_state('error', response.message)
        else:
            matched = len(response.matched_topics)
            self.match_count.setText(str(matched))
            self.match_count.setStyleSheet(
                f'color: {PALETTE.success if matched else PALETTE.warning};')
            bits = []
            if response.excluded_topics:
                bits.append(f'{len(response.excluded_topics)} excluded')
            if response.unmatched_selectors:
                bits.append(f'{len(response.unmatched_selectors)} selector(s) match nothing')
            self.match_detail.setText(' · '.join(bits))
            self.match_detail.setStyleSheet(f'color: {PALETTE.text_dim};')
            self._show_unmatched(response.unmatched_selectors)
            if matched:
                self.check_selection.set_state(
                    'warning' if response.unmatched_selectors else 'ok',
                    f'{matched} topic(s) matched'
                    + (f', {len(response.unmatched_selectors)} selector(s) match nothing'
                       if response.unmatched_selectors else ''))
            else:
                self.check_selection.set_state('error', 'nothing matches this selection')
        self._refresh_checks()

    def _show_unmatched(self, selectors):
        """Name the selectors that match nothing, rather than counting them."""
        selectors = [s for s in selectors if s]
        if not selectors:
            self.unmatched_label.setVisible(False)
            self.unmatched_label.setToolTip('')
            return
        shown = ', '.join(selectors[:6])
        if len(selectors) > 6:
            shown += f' and {len(selectors) - 6} more'
        self.unmatched_label.setText(f'Matches nothing on the graph right now: {shown}')
        self.unmatched_label.setToolTip('\n'.join(selectors))
        self.unmatched_label.setStyleSheet(f'color: {PALETTE.warning};')
        self.unmatched_label.setVisible(True)

    def set_validation(self, response, error=''):
        self._validation = response if not error else None
        if error:
            for check in (self.check_path, self.check_collision, self.check_disk):
                check.set_state('pending', error)
            self._set_validation_note('', [])
            self._refresh_checks()
            return
        if response is None:
            return
        self._available_writers = list(response.available_writers)
        self._apply_storage_availability()
        if response.path_writable:
            self.check_path.set_state(
                'ok', 'writable' + ('' if response.path_exists else ' (will be created)'))
        else:
            self.check_path.set_state('error', 'not writable on the recording machine')

        if response.collision:
            self.check_collision.set_state(
                'error', f'{os.path.basename(response.collision_uris[0])} already exists')
        else:
            self.check_collision.set_state('ok', 'name is free')

        if response.disk_total_bytes:
            free = response.disk_free_bytes
            state = 'error' if free < (1 << 30) else ('warning' if free < (5 << 30) else 'ok')
            self.check_disk.set_state(state, f'{human_bytes(free)} free')
        else:
            self.check_disk.set_state('warning', 'could not read the disk')

        # The bridge writes one operator-readable sentence and a warning list.
        # Both used to be thrown away here.
        self._set_validation_note('' if response.ok else response.message,
                                  list(response.warnings))
        self._refresh_checks()

    def _set_validation_note(self, message, warnings):
        lines = [text for text in ([message] + list(warnings)) if text]
        self.validation_note.setText(' · '.join(lines))
        self.validation_note.setVisible(bool(lines))
        self.validation_note.setStyleSheet(
            f'color: {PALETTE.danger if message else PALETTE.warning};')

    def _apply_storage_availability(self):
        """
        Reflect which rosbag2 storage plugins the recording machine has.

        A format that is not installed cannot be switched on, so its box is
        disabled - unless it is already ticked, in which case the box stays
        live so the operator can untick it and the pre-flight turns red.
        """
        available = self._available_writers
        for key, box in (('sqlite', self.sqlite_check), ('mcap', self.mcap_check)):
            storage_id = STORAGE_IDS[key]
            missing = bool(available) and storage_id not in available
            box.setEnabled(not missing or box.isChecked())
            box.setToolTip(
                f'The {storage_id} storage plugin is not installed on the '
                'recording machine.' if missing else '')
        self._update_format_hint()

    def _missing_formats(self):
        config = self._store.config
        if not self._available_writers:
            return []
        return [STORAGE_IDS[key] for key, on in (('sqlite', config.storage_sqlite),
                                                 ('mcap', config.storage_mcap))
                if on and STORAGE_IDS[key] not in self._available_writers]

    def _update_format_hint(self):
        missing = self._missing_formats()
        if missing:
            self.format_hint.setText(f'{missing[0]} is not installed on the recorder.')
            self.format_hint.setStyleSheet(f'color: {PALETTE.danger};')
        elif self._available_writers:
            self.format_hint.setText(
                'Available here: ' + ', '.join(self._available_writers))
            self.format_hint.setStyleSheet(f'color: {PALETTE.text_dim};')
        else:
            self.format_hint.setText('Both can be written at once.')
            self.format_hint.setStyleSheet(f'color: {PALETTE.text_dim};')

    def _refresh_checks(self):
        config = self._store.config
        self._update_format_hint()
        missing = self._missing_formats()
        if missing:
            self.check_format.set_state(
                'error', f'{missing[0]} is not installed on the recording machine')
        elif config.storage_sqlite or config.storage_mcap:
            formats = ' + '.join(
                name for name, on in (('SQLite3', config.storage_sqlite),
                                      ('MCAP', config.storage_mcap)) if on)
            self.check_format.set_state('ok', formats)
        else:
            self.check_format.set_state('error', 'pick at least one format')

        blocking = [c for c in (self.check_ros, self.check_path, self.check_collision,
                                self.check_disk, self.check_selection, self.check_format)
                    if getattr(c, 'state', 'pending') == 'error']
        ready = not blocking
        self.start_button.setEnabled(ready)
        if ready:
            self.launch_card.set_tone('success')
            self.launch_title.setText('Ready to record')
            matched = len(self._preview.matched_topics) if self._preview else 0
            formats = ' + '.join(
                name for name, on in (('MCAP', config.storage_mcap),
                                      ('SQLite3', config.storage_sqlite)) if on)
            self.launch_detail.setText(
                f'{matched} topic(s) · {formats} · {config.bag_path}')
        else:
            self.launch_card.set_tone('warning')
            self.launch_title.setText('Not ready yet')
            self.launch_detail.setText(
                'Resolve these first: '
                + ', '.join(c.label.text().lower() for c in blocking))

    def on_status(self, status):
        self._status = status
        if status.state in (1, 2):
            self._set_phase(PHASE_MONITOR)
            self._update_monitor(status)
        elif status.state == 3:
            self._set_phase(PHASE_MONITOR)
            self.monitor_beacon.set_state('stopping', 'STOPPING',
                                          'Closing the bag writers…', '')
            self.stop_button.setEnabled(False)
            self.stop_button.setText('  STOPPING…')
        elif self.stack.currentIndex() == PHASE_MONITOR:
            # The bridge left the recording states without us asking; most
            # likely the recorder failed. Show what we know.
            self._set_phase(PHASE_CONFIGURE)
            self.stop_button.setEnabled(True)
            self.stop_button.setText('  STOP RECORDING')

    def _update_monitor(self, status):
        recording = status.state == 2
        self.stop_button.setEnabled(recording)
        self.stop_button.setText('  STOP RECORDING')
        if recording:
            writers = ' + '.join(w.upper() for w in status.active_writers)
            self.monitor_beacon.set_state('recording', 'RECORDING',
                                          f'{status.bag_name} · {writers}',
                                          duration(status.duration_sec))
        else:
            self.monitor_beacon.set_state('preparing', 'PREPARING',
                                          status.state_detail or 'Opening writers…', '')

        self.m_duration.set_value(duration(status.duration_sec))
        self.m_size.set_value(human_bytes(status.bag_size_bytes))
        self.m_size.set_hint(human_rate(status.write_rate_bytes_per_sec))
        self.m_topics.set_value(count(status.topic_count))
        self.m_messages.set_value(count(status.message_count))
        self.m_rate.setText(human_rate(status.write_rate_bytes_per_sec))
        self.m_spark.push(max(0.0, status.write_rate_bytes_per_sec))

        self.m_targets.set('Location', status.bag_path or NA)
        for index, uri in enumerate(status.bag_uris):
            self.m_targets.set(status.active_writers[index].upper()
                               if index < len(status.active_writers) else f'Bag {index}',
                               uri, PALETTE.success)

        if status.disk_total_bytes:
            used = status.disk_total_bytes - status.disk_free_bytes
            self.m_disk.set_value(used / status.disk_total_bytes,
                                  f'{human_bytes(used)} / '
                                  f'{human_bytes(status.disk_total_bytes)}')
            self.m_disk_free.setText(human_bytes(status.disk_free_bytes))
        else:
            self.m_disk.set_value(-1.0, NA)
            self.m_disk_free.setText(NA)

        problems = []
        if status.failed_topic_count:
            problems.append(f'{status.failed_topic_count} topic(s) could not be recorded '
                            '(message type not installed here).')
        if status.lost_topic_count:
            problems.append(f'{status.lost_topic_count} topic(s) stopped publishing.')
        if status.last_error:
            problems.append(status.last_error)
        self.m_problems.setText('\n'.join(problems) if problems else 'None so far.')
        self.m_problems.setStyleSheet(
            f'color: {PALETTE.warning if problems else PALETTE.text_dim};')
        self.m_problems_card.set_tone('warning' if problems else '')

    def show_summary(self, summary, warning=''):
        """Switch to the completion view once the bridge confirms the stop."""
        self._summary = summary
        self._set_phase(PHASE_COMPLETE)
        self.done_title.setText('Recording completed' if not warning
                                else 'Recording stopped with a warning')
        self.done_subtitle.setText(
            f'{summary.bag_name} · finished after {short_duration(summary.duration_sec)}')
        self.c_duration.set_value(duration(summary.duration_sec))
        self.c_topics.set_value(count(summary.topic_count))
        self.c_messages.set_value(count(summary.message_count))
        self.c_size.set_value(human_bytes(summary.total_size_bytes))

        recorded = [name for name in summary.recorded_topics if name]
        self.c_topics_card.set_subtitle(
            f'{len(recorded)} topic(s) written to this bag' if recorded
            else 'The bridge reported no per-topic detail for this recording.')
        self.c_topic_list.setPlainText('\n'.join(recorded) or 'No topics recorded.')
        self.c_topics_card.setVisible(True)

        self.c_outputs.set('Location', summary.bag_path or NA)
        for index, uri in enumerate(summary.bag_uris):
            label = (summary.formats[index].upper() if index < len(summary.formats)
                     else f'Bag {index}')
            self.c_outputs.set(label, uri, PALETTE.success)

        notes = []
        if warning:
            notes.append(warning)
        if summary.failed_topics:
            notes.append('Not recorded (message type unavailable): '
                         + ', '.join(summary.failed_topics))
        if summary.lost_topics:
            notes.append('Stopped publishing during the recording: '
                         + ', '.join(summary.lost_topics))
        self.c_notes_label.setText('\n'.join(notes) if notes
                                   else 'No problems were reported.')
        self.c_notes.set_tone('warning' if notes else '')

    def _set_phase(self, phase):
        if self.stack.currentIndex() != phase:
            self.stack.setCurrentIndex(phase)
        self.set_subtitle({
            PHASE_CONFIGURE: 'Configure the output, then start',
            PHASE_MONITOR: 'Recording in progress',
            PHASE_COMPLETE: 'Last recording finished',
        }[phase])

    # -- actions ---------------------------------------------------------

    def _on_start_clicked(self):
        self.start_button.setEnabled(False)
        self.start_button.setText('  STARTING…')
        self.start_requested.emit(self._store.config)

    def start_failed(self, message, detail=''):
        self.start_button.setEnabled(True)
        self.start_button.setText('  START RECORDING')
        self._refresh_checks()
        show_error(self, 'Recording could not be started', message, detail)

    def start_succeeded(self):
        self.start_button.setText('  START RECORDING')
        self._set_phase(PHASE_MONITOR)
        self.m_spark.clear()

    def _on_stop_clicked(self):
        status = self._status
        detail = ''
        if status is not None:
            detail = (f'{status.bag_name}\n{count(status.message_count)} messages from '
                      f'{status.topic_count} topics, {human_bytes(status.bag_size_bytes)} '
                      f'so far.')
        if not confirm(self, 'Stop this recording?',
                       'The bag will be closed and cannot be resumed. A new recording '
                       'would start a new bag.',
                       confirm_text='Stop recording', tone='warning', detail=detail):
            return
        self.stop_button.setEnabled(False)
        self.stop_button.setText('  STOPPING…')
        self.stop_requested.emit()

    def stop_failed(self, message, detail=''):
        self.stop_button.setEnabled(True)
        self.stop_button.setText('  STOP RECORDING')
        show_error(self, 'The recording did not stop cleanly', message, detail)
