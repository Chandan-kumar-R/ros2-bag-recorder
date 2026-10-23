"""Left-hand navigation."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.theme import PALETTE, SPACE_MD, SPACE_SM, SPACE_XS
from rosbag_recorder_ui.widgets.cards import restyle
from rosbag_recorder_ui.widgets.indicators import Dot


class NavItem(QPushButton):
    def __init__(self, key, label, icon_name, parent=None):
        super().__init__(f'  {label}', parent)
        self.key = key
        self.icon_name = icon_name
        self.setObjectName('NavItem')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(17, 17))
        self._apply_icon(False)
        self.toggled.connect(self._apply_icon)

    def _apply_icon(self, active):
        color = PALETTE.text if active else PALETTE.text_dim
        self.setIcon(icons.icon(self.icon_name, color, 17))


class Sidebar(QWidget):
    """Navigation plus a compact connection read-out pinned to the bottom."""

    navigated = Signal(str)

    PAGES = (
        ('dashboard', 'Dashboard', 'dashboard'),
        ('recording', 'Recording', 'record'),
        ('topics', 'Topics', 'topics'),
        ('configuration', 'Configuration', 'config'),
        ('diagnostics', 'Diagnostics', 'diagnostics'),
        ('history', 'History', 'history'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Sidebar')
        # Qt will not paint a stylesheet background on a QWidget *subclass*
        # unless this is set; without it the sidebar silently inherits the page
        # colour and the whole elevation scheme collapses into one flat plane.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(214)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_MD, SPACE_MD + 4, SPACE_MD, SPACE_MD)
        layout.setSpacing(SPACE_SM)

        layout.addLayout(self._build_brand())
        layout.addSpacing(SPACE_MD)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items = {}
        self._badges = {}
        for key, label, icon_name in self.PAGES:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            item = NavItem(key, label, icon_name)
            item.clicked.connect(lambda _checked=False, k=key: self.navigated.emit(k))
            self._group.addButton(item)
            self._items[key] = item
            row_layout.addWidget(item)

            badge = QLabel('')
            badge.setObjectName('NavBadge')
            badge.setVisible(False)
            badge.setAttribute(Qt.WA_TransparentForMouseEvents)
            row_layout.addWidget(badge, 0, Qt.AlignRight | Qt.AlignVCenter)
            row_layout.setStretch(0, 1)
            self._badges[key] = badge
            layout.addWidget(row)

        layout.addStretch(1)

        divider = QFrame()
        divider.setObjectName('Divider')
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)
        layout.addSpacing(SPACE_XS)
        layout.addWidget(self._build_connection())

    def _build_brand(self):
        row = QHBoxLayout()
        row.setSpacing(SPACE_SM + 2)
        mark = QLabel()
        pixmap = QPixmap(30, 30)
        pixmap.fill(Qt.transparent)
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(icons.app_icon_svg().encode('utf-8')))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        mark.setPixmap(pixmap)
        row.addWidget(mark)

        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel('Bag Recorder')
        title.setObjectName('BrandTitle')
        text.addWidget(title)
        subtitle = QLabel('ROS 2 · RECORDING')
        subtitle.setObjectName('BrandSub')
        text.addWidget(subtitle)
        row.addLayout(text)
        row.addStretch(1)
        return row

    def _build_connection(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(SPACE_XS + 2)

        self.ros_dot = Dot(PALETTE.danger, 8)
        self.ros_label = QLabel('ROS 2 graph')
        self.ros_label.setObjectName('CardHint')
        self.ros_value = QLabel('offline')
        self.ros_value.setObjectName('CardHint')

        self.bridge_dot = Dot(PALETTE.danger, 8)
        self.bridge_label = QLabel('Recorder bridge')
        self.bridge_label.setObjectName('CardHint')
        self.bridge_value = QLabel('offline')
        self.bridge_value.setObjectName('CardHint')

        for dot, label, value in ((self.ros_dot, self.ros_label, self.ros_value),
                                  (self.bridge_dot, self.bridge_label, self.bridge_value)):
            row = QHBoxLayout()
            row.setSpacing(SPACE_XS + 2)
            row.addWidget(dot)
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            layout.addLayout(row)
        return panel

    # -- API ------------------------------------------------------------

    def select(self, key):
        item = self._items.get(key)
        if item is not None and not item.isChecked():
            item.setChecked(True)

    def set_badge(self, key, text, tone='danger'):
        badge = self._badges.get(key)
        if badge is None:
            return
        badge.setText(str(text))
        badge.setVisible(bool(text))
        badge.setStyleSheet(
            f'background: {PALETTE.state_color(tone)}; '
            f'color: {PALETTE.ink_for(tone)}; border-radius: 7px;'
            'font-size: 10px; font-weight: 700; padding: 1px 6px;')
        restyle(badge)

    def set_ros_state(self, online, detail=''):
        self.ros_dot.set_color(PALETTE.success if online else PALETTE.danger)
        self.ros_value.setText(detail or ('connected' if online else 'offline'))
        self.ros_value.setStyleSheet(
            f'color: {PALETTE.success if online else PALETTE.danger}; font-size: 11px;')

    def set_bridge_state(self, online, detail=''):
        self.bridge_dot.set_color(PALETTE.success if online else PALETTE.danger)
        self.bridge_value.setText(detail or ('online' if online else 'offline'))
        self.bridge_value.setStyleSheet(
            f'color: {PALETTE.success if online else PALETTE.danger}; font-size: 11px;')
