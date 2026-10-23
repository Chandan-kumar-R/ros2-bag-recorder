"""
Diagnostics: whether the problem is the robot, the network, the disk, or us.

Everything on the left describes the machine running the bridge (which is the
machine that will hold the bag). Everything on the right describes the link
between this dashboard and that machine.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import NA, count, human_bytes, percent, short_duration
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_MD, SPACE_SM
from rosbag_recorder_ui.views.base import Page, card_grid
from rosbag_recorder_ui.widgets.cards import KeyValueList, SectionCard, StatCard
from rosbag_recorder_ui.widgets.indicators import Meter

REFRESH_MS = 4000


class DiagnosticsPage(Page):
    title_text = 'Diagnostics'
    subtitle_text = 'Health of the recording machine and the link to it'

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._diag = None
        self._ros_online = False
        self._bridge_online = False
        self._warnings = 0
        self._errors = 0

        self.stamp_label = QLabel('never refreshed')
        self.stamp_label.setObjectName('CardHint')
        self.add_action(self.stamp_label)

        refresh = QPushButton('  Refresh')
        refresh.setProperty('variant', 'subtle')
        refresh.setIcon(icons.icon('refresh', PALETTE.text_muted, 15))
        refresh.clicked.connect(self.refresh_requested)
        self.add_action(refresh)

        self.content.addLayout(self._build_connection_row())
        self.content.addLayout(self._build_graph_row())

        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)
        row.addWidget(self._build_resources_card(), 2)
        row.addWidget(self._build_environment_card(), 3)
        self.content.addLayout(row)

        self.content.addWidget(self._build_problems_card())
        self.content.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_requested)

    # ------------------------------------------------------------------

    def _build_connection_row(self):
        grid = card_grid(4)
        self.card_ros = StatCard('ROS 2 graph', NA, '', 'link', compact=True)
        self.card_bridge = StatCard('Recorder bridge', NA, '', 'link', compact=True)
        self.card_recorder = StatCard('Recorder', NA, '', 'record', compact=True)
        self.card_uptime = StatCard('Bridge uptime', NA, '', 'clock', compact=True)
        for column, card in enumerate((self.card_ros, self.card_bridge,
                                       self.card_recorder, self.card_uptime)):
            grid.addWidget(card, 0, column)
        return grid

    def _build_graph_row(self):
        grid = card_grid(4)
        self.card_nodes = StatCard('Nodes', NA, '', 'dashboard', compact=True)
        self.card_topics = StatCard('Topics', NA, '', 'topics', compact=True)
        self.card_services = StatCard('Services', NA, '', 'config', compact=True)
        self.card_actions = StatCard('Actions', NA, '', 'play', compact=True)
        for column, card in enumerate((self.card_nodes, self.card_topics,
                                       self.card_services, self.card_actions)):
            grid.addWidget(card, 0, column)
        return grid

    def _build_resources_card(self):
        card = SectionCard('Recording machine', '', 'cpu')
        self.cpu_meter = Meter('CPU')
        self.memory_meter = Meter('Memory')
        self.disk_meter = Meter('Disk')
        for meter in (self.cpu_meter, self.memory_meter, self.disk_meter):
            card.body.addWidget(meter)
        card.body.addStretch(1)
        return card

    def _build_environment_card(self):
        card = SectionCard('Environment', '', 'info')
        self.environment = KeyValueList(key_width=140)
        for key in ('Hostname', 'ROS distro', 'ROS_DOMAIN_ID', 'Disk mount',
                    'Disk free', 'Recorder state'):
            self.environment.set(key, NA)
        card.body.addWidget(self.environment)
        card.body.addStretch(1)
        return card

    def _build_problems_card(self):
        self.problems_card = SectionCard('Warnings and errors', '', 'warning')
        self.problems_body = QVBoxLayout()
        self.problems_body.setSpacing(SPACE_SM)
        self.problems_card.body.addLayout(self.problems_body)
        self.no_problems = QLabel('Nothing reported.')
        self.no_problems.setObjectName('CardHint')
        self.problems_body.addWidget(self.no_problems)
        self._problem_widgets = []
        return self.problems_card

    # ------------------------------------------------------------------

    def on_shown(self):
        self.refresh_requested.emit()
        self._timer.start(REFRESH_MS)

    def on_hidden(self):
        self._timer.stop()

    def set_connection(self, ros_online, bridge_online, node_count=-1, topic_count=-1):
        self._ros_online = ros_online
        self._bridge_online = bridge_online
        self.card_ros.set_value('CONNECTED' if ros_online else 'DISCONNECTED',
                                PALETTE.success if ros_online else PALETTE.danger)
        self.card_ros.set_hint(
            f'{node_count} node' + ('s' if node_count != 1 else '') + ' visible'
            if node_count >= 0 else 'graph unavailable')
        self.card_bridge.set_value('ONLINE' if bridge_online else 'OFFLINE',
                                   PALETTE.success if bridge_online else PALETTE.danger)
        self.card_bridge.set_hint('' if bridge_online
                                  else 'start rosbag_recorder_bridge')
        if not bridge_online:
            self.card_recorder.set_value(NA)
            self.card_uptime.set_value(NA)
            self._render_problems([
                ('error', 'The recorder bridge is not reachable. Nothing can be '
                          'recorded until it is running.')])

    def on_status(self, status):
        label, color = {
            0: ('IDLE', PALETTE.neutral),
            1: ('PREPARING', PALETTE.warning),
            2: ('RECORDING', PALETTE.recording),
            3: ('STOPPING', PALETTE.warning),
            4: ('ERROR', PALETTE.danger),
        }.get(status.state, ('UNKNOWN', PALETTE.neutral))
        self.card_recorder.set_value(label, color)
        self.card_recorder.set_hint(status.bag_name or '')
        self.environment.set('Recorder state', label, color)

    def set_log_counts(self, warnings, errors):
        self._warnings, self._errors = warnings, errors

    def set_diagnostics(self, diag, error=''):
        if error:
            self.stamp_label.setText(f'refresh failed: {error}')
            return
        self._diag = diag
        self.stamp_label.setText('refreshed just now')

        self.card_nodes.set_value(count(diag.node_count))
        self.card_topics.set_value(count(diag.topic_count))
        self.card_services.set_value(count(diag.service_count))
        self.card_actions.set_value(count(diag.action_count))
        self.card_uptime.set_value(short_duration(diag.bridge_uptime_sec))

        if diag.cpu_percent >= 0:
            self.cpu_meter.set_value(diag.cpu_percent / 100.0, percent(diag.cpu_percent))
        else:
            self.cpu_meter.set_value(-1.0, NA)
        if diag.memory_percent >= 0:
            self.memory_meter.set_value(
                diag.memory_percent / 100.0,
                f'{human_bytes(diag.memory_used_bytes)} / '
                f'{human_bytes(diag.memory_total_bytes)}')
        else:
            self.memory_meter.set_value(-1.0, NA)
        if diag.disk_total_bytes:
            used = diag.disk_total_bytes - diag.disk_free_bytes
            self.disk_meter.set_value(
                used / diag.disk_total_bytes,
                f'{human_bytes(used)} / {human_bytes(diag.disk_total_bytes)}')
        else:
            self.disk_meter.set_value(-1.0, NA)

        self.environment.set('Hostname', diag.hostname or NA)
        self.environment.set('ROS distro', diag.ros_distro or NA)
        self.environment.set('ROS_DOMAIN_ID', str(diag.ros_domain_id)
                             if diag.ros_domain_id >= 0 else NA)
        self.environment.set('Disk mount', diag.disk_mount or NA)
        self.environment.set('Disk free', human_bytes(diag.disk_free_bytes)
                             if diag.disk_total_bytes else NA)

        problems = [('error', text) for text in diag.errors]
        problems += [('warning', text) for text in diag.warnings]
        if self._errors:
            problems.append(('warning', f'{self._errors} error(s) in the log this '
                                        'session; see the log panel.'))
        self._render_problems(problems)

    def _render_problems(self, problems):
        for widget in self._problem_widgets:
            self.problems_body.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._problem_widgets = []
        self.no_problems.setVisible(not problems)
        self.problems_card.set_tone(
            '' if not problems else
            ('danger' if any(t == 'error' for t, _ in problems) else 'warning'))
        for tone, text in problems:
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
            self.problems_body.addWidget(row)
            self._problem_widgets.append(row)
