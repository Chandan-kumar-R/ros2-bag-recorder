"""The application header: identity on the left, live state on the right."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.formatting import duration
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_LG, SPACE_MD, SPACE_SM
from rosbag_recorder_ui.widgets.indicators import StatusPill

STATE_LOOK = {
    0: ('IDLE', 'idle', False),
    1: ('PREPARING', 'preparing', True),
    2: ('RECORDING', 'recording', True),
    3: ('STOPPING', 'stopping', True),
    4: ('ERROR', 'error', False),
}


class TopBar(QWidget):
    """Shows connection health and recorder state at all times, on every page."""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('TopBar')
        # See Sidebar: a QWidget subclass needs this before Qt honours the
        # stylesheet background.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_SM, SPACE_LG, SPACE_SM)
        layout.setSpacing(SPACE_MD)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel('ROS 2 Bag Recorder')
        self.title.setStyleSheet('font-size: 15px; font-weight: 700;')
        titles.addWidget(self.title)
        self.subtitle = QLabel('Recording dashboard')
        self.subtitle.setObjectName('CardHint')
        titles.addWidget(self.subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.graph_pill = StatusPill('ROS 2  DISCONNECTED', PALETTE.danger, compact=True)
        layout.addWidget(self.graph_pill)

        self.bridge_pill = StatusPill('BRIDGE  OFFLINE', PALETTE.danger, compact=True)
        layout.addWidget(self.bridge_pill)
        # Which machine will hold the bag. The bridge is often not this one,
        # and 'ONLINE' on its own does not say whose disk is about to fill.
        self._bridge_host = ''

        self.state_pill = StatusPill('IDLE', PALETTE.neutral)
        layout.addWidget(self.state_pill)

        self.elapsed = QLabel('')
        self.elapsed.setObjectName('Mono')
        self.elapsed.setStyleSheet(
            f'color: {PALETTE.recording}; font-size: 16px; font-weight: 700;')
        self.elapsed.setVisible(False)
        layout.addWidget(self.elapsed)

        self.stop_button = QPushButton('  STOP')
        self.stop_button.setProperty('variant', 'stop')
        self.stop_button.setIcon(icons.icon('stop', PALETTE.on_danger, 14))
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setVisible(False)
        self.stop_button.setStyleSheet('padding: 7px 16px; font-size: 12px;')
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

    def set_graph_state(self, online, node_count=-1):
        text = 'ROS 2  CONNECTED' if online else 'ROS 2  DISCONNECTED'
        if online and node_count >= 0:
            text = f'ROS 2  {node_count} NODE' + ('S' if node_count != 1 else '')
        self.graph_pill.set_state(text, PALETTE.success if online else PALETTE.danger)

    def set_bridge_state(self, online, hostname=None):
        if hostname is not None:
            self._bridge_host = hostname or ''
        text = 'BRIDGE  OFFLINE'
        if online:
            text = 'BRIDGE  ONLINE'
            if self._bridge_host:
                text += f'  ·  {self._bridge_host.upper()}'
        self.bridge_pill.set_state(text,
                                   PALETTE.success if online else PALETTE.danger)
        self.bridge_pill.setToolTip(
            f'Recording on {self._bridge_host}. Bag paths are resolved there, '
            'not on this machine.' if online and self._bridge_host else
            'The machine running rosbag_recorder_bridge holds the bag.')

    def set_recorder_state(self, state, elapsed_sec=None):
        text, tone, pulsing = STATE_LOOK.get(state, STATE_LOOK[0])
        self.state_pill.set_state(text, PALETTE.state_color(tone), pulsing)
        recording = state == 2
        self.elapsed.setVisible(recording)
        self.stop_button.setVisible(state in (2, 1))
        self.stop_button.setEnabled(state == 2)
        if recording and elapsed_sec is not None:
            self.elapsed.setText(duration(elapsed_sec))

    def set_context(self, subtitle):
        self.subtitle.setText(subtitle)
