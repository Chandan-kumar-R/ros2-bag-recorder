"""
Dashboard:

Everything here is read-only except the two buttons.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import (
    NA,
    count,
    duration,
    human_bytes,
    human_rate,
)
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_MD, SPACE_SM
from rosbag_recorder_ui.views.base import Page, card_grid
from rosbag_recorder_ui.widgets.cards import KeyValueList, SectionCard, StatCard
from rosbag_recorder_ui.widgets.indicators import Meter, RecordingBeacon, Sparkline

STATE_TONE = {0: 'idle', 1: 'preparing', 2: 'recording', 3: 'stopping', 4: 'error'}


class DashboardPage(Page):
    title_text = 'Dashboard'
    subtitle_text = 'Live view of the recorder'

    start_requested = Signal()
    stop_requested = Signal()
    configure_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._status = None

        self.refresh_hint = QLabel('')
        self.refresh_hint.setObjectName('CardHint')
        self.add_action(self.refresh_hint)

        self.configure_button = QPushButton('  Configure')
        self.configure_button.setIcon(icons.icon('config', PALETTE.text_muted, 15))
        self.configure_button.setProperty('variant', 'subtle')
        self.configure_button.setCursor(Qt.PointingHandCursor)
        self.configure_button.clicked.connect(self.configure_requested)
        self.add_action(self.configure_button)

        self.beacon = RecordingBeacon()
        self.content.addWidget(self.beacon)

        self.content.addLayout(self._build_primary_stats())
        self.content.addLayout(self._build_middle_row())
        self.content.addWidget(self._build_alerts())
        self.content.addStretch(1)

        self.set_status(None)

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------

    def _build_primary_stats(self):
        grid = card_grid(4)
        self.card_duration = StatCard('Duration', NA, 'since start', 'clock')
        self.card_size = StatCard('Bag size', NA, 'on disk', 'bag')
        self.card_topics = StatCard('Topics', NA, 'being recorded', 'topics')
        self.card_messages = StatCard('Messages', NA, 'written', 'wave')
        for column, card in enumerate((self.card_duration, self.card_size,
                                       self.card_topics, self.card_messages)):
            grid.addWidget(card, 0, column)
        return grid

    def _build_middle_row(self):
        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)

        throughput = SectionCard('Throughput', 'Bytes committed to the bag',
                                 'diagnostics')
        self.rate_label = QLabel(NA)
        self.rate_label.setObjectName('CardValue')
        throughput.body.addWidget(self.rate_label)
        self.sparkline = Sparkline(color=PALETTE.accent)
        throughput.body.addWidget(self.sparkline)
        row.addWidget(throughput, 3)

        output = SectionCard('Output', '', 'folder')
        self.output_details = KeyValueList(key_width=90)
        self.output_details.set('Location', NA)
        self.output_details.set('Bag name', NA)
        self.output_details.set('Writers', NA)
        self.output_details.set('Selection', NA)
        output.body.addWidget(self.output_details)
        row.addWidget(output, 4)

        disk = SectionCard('Recording disk', '', 'disk')
        self.disk_meter = Meter('Used')
        disk.body.addWidget(self.disk_meter)
        self.disk_free = QLabel(NA)
        self.disk_free.setObjectName('CardValueSm')
        disk.body.addWidget(self.disk_free)
        hint = QLabel('free')
        hint.setObjectName('CardHint')
        disk.body.addWidget(hint)
        disk.body.addStretch(1)
        row.addWidget(disk, 2)
        return row

    def _build_alerts(self):
        self.alerts_card = SectionCard('Attention', '', 'warning')
        self.alerts_body = QVBoxLayout()
        self.alerts_body.setSpacing(SPACE_SM)
        self.alerts_card.body.addLayout(self.alerts_body)

        self.no_alerts = QLabel('Nothing needs attention.')
        self.no_alerts.setObjectName('CardHint')
        self.alerts_body.addWidget(self.no_alerts)
        self._alert_widgets = []
        return self.alerts_card

    # ------------------------------------------------------------------
    #  Updates
    # ------------------------------------------------------------------

    def on_status(self, status):
        self.set_status(status)

    def set_status(self, status):
        self._status = status
        if status is None:
            self.beacon.set_state('idle', 'NOT CONNECTED',
                                  'Waiting for the recorder bridge')
            for card in (self.card_duration, self.card_size, self.card_topics,
                         self.card_messages):
                card.set_value(NA)
            self.rate_label.setText(NA)
            self.output_details.clear_values()
            self.disk_meter.set_value(-1.0, NA)
            self.disk_free.setText(NA)
            self._set_alerts([('warning', 'The recorder bridge is not reachable. '
                                          'Start it with: ros2 launch '
                                          'rosbag_recorder_bridge bridge.launch.py')])
            return

        recording = status.state == 2
        self._update_beacon(status)

        self.card_duration.set_value(duration(status.duration_sec) if status.duration_sec
                                     else NA)
        self.card_size.set_value(human_bytes(status.bag_size_bytes)
                                 if status.bag_uris else NA)
        self.card_topics.set_value(count(status.topic_count) if status.topic_count else NA)
        self.card_messages.set_value(count(status.message_count)
                                     if status.message_count else NA)

        if recording:
            self.card_duration.set_hint('recording', PALETTE.recording)
            self.card_size.set_hint(human_rate(status.write_rate_bytes_per_sec))
            self.card_topics.set_hint(
                f'{status.failed_topic_count} failed' if status.failed_topic_count
                else 'all resolved',
                PALETTE.danger if status.failed_topic_count else None)
            self.sparkline.push(max(0.0, status.write_rate_bytes_per_sec))
        else:
            self.card_duration.set_hint('last recording' if status.duration_sec
                                        else 'since start')
            self.card_size.set_hint('on disk')
            self.card_topics.set_hint('being recorded')

        self.rate_label.setText(human_rate(status.write_rate_bytes_per_sec)
                                if recording else NA)

        self.output_details.set('Location', status.bag_path or NA)
        self.output_details.set('Bag name', status.bag_name or NA)
        writers = ' + '.join(w.upper() for w in status.active_writers) or NA
        self.output_details.set('Writers', writers,
                                PALETTE.success if status.active_writers else None)
        config = status.config
        if config.selection_method == 'keywords':
            selection = 'Keywords: ' + (', '.join(config.keywords) or NA)
        elif config.selection_method == 'manual':
            ticked = len([t for t in config.manual_topics if t])
            selection = f'Manual: {ticked} topic(s) ticked'
        else:
            selection = 'Registry: ' + (', '.join(config.modules) or 'no modules')
        self.output_details.set('Selection', selection)

        if status.disk_total_bytes:
            used = status.disk_total_bytes - status.disk_free_bytes
            fraction = used / status.disk_total_bytes
            self.disk_meter.set_value(
                fraction, f'{human_bytes(used)} / {human_bytes(status.disk_total_bytes)}')
            self.disk_free.setText(human_bytes(status.disk_free_bytes))
            low = status.disk_free_bytes < (5 << 30)
            self.disk_free.setStyleSheet(
                f'color: {PALETTE.warning if low else PALETTE.text};')
        else:
            self.disk_meter.set_value(-1.0, NA)
            self.disk_free.setText(NA)

        self._refresh_alerts(status)

    def _update_beacon(self, status):
        if status.state == 2:
            detail = f'{status.bag_name} · {" + ".join(w.upper() for w in status.active_writers)}'
            self.beacon.set_state('recording', 'RECORDING', detail,
                                  duration(status.duration_sec))
        elif status.state == 1:
            self.beacon.set_state('preparing', 'PREPARING',
                                  status.state_detail or 'Getting ready', '')
        elif status.state == 3:
            self.beacon.set_state('stopping', 'STOPPING',
                                  status.state_detail or 'Closing the bag writers', '')
        elif status.state == 4:
            self.beacon.set_state('error', 'ERROR',
                                  status.last_error or 'The recorder reported a problem', '')
        elif status.bag_name:
            self.beacon.set_state(
                'done', 'IDLE',
                f'Last recording: {status.bag_name} · {human_bytes(status.bag_size_bytes)}',
                duration(status.duration_sec))
        else:
            self.beacon.set_state('idle', 'IDLE', 'Not recording', '')

    def _refresh_alerts(self, status):
        alerts = []
        if status.last_error:
            alerts.append(('error', status.last_error))
        if status.failed_topic_count:
            alerts.append(('warning',
                           f'{status.failed_topic_count} selected topic(s) could not be '
                           'recorded because their message type is not installed here.'))
        if status.lost_topic_count:
            alerts.append(('warning',
                           f'{status.lost_topic_count} topic(s) stopped publishing while '
                           'being recorded.'))
        if status.disk_total_bytes and status.disk_free_bytes < (5 << 30):
            alerts.append(('warning',
                           f'Only {human_bytes(status.disk_free_bytes)} left on the '
                           'recording disk.'))
        self._set_alerts(alerts)

    def _set_alerts(self, alerts):
        for widget in self._alert_widgets:
            self.alerts_body.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._alert_widgets = []

        self.no_alerts.setVisible(not alerts)
        self.alerts_card.set_tone('' if not alerts else
                                  ('danger' if any(t == 'error' for t, _ in alerts)
                                   else 'warning'))
        for tone, text in alerts:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(SPACE_SM)
            color = PALETTE.danger if tone == 'error' else PALETTE.warning
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap('error' if tone == 'error' else 'warning',
                                         color, 15))
            glyph.setAlignment(Qt.AlignTop)
            layout.addWidget(glyph)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet(f'color: {color};')
            layout.addWidget(label, 1)
            self.alerts_body.addWidget(row)
            self._alert_widgets.append(row)

    def set_connection(self, ros_online, bridge_online):
        if not bridge_online:
            self.set_status(None)
