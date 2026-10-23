"""
Status indicators.
"""
from PySide6.QtCore import Property, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.theme import PALETTE, RADIUS_SM, SPACE_SM, SPACE_XS


class Dot(QWidget):
    """A coloured dot that can pulse. Small, cheap, used everywhere."""

    def __init__(self, color=PALETTE.neutral, size=10, pulsing=False, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self._phase = 1.0
        self.setFixedSize(size + 6, size + 6)
        self._animation = QPropertyAnimation(self, b'phase', self)
        self._animation.setDuration(1100)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.25)
        self._animation.setLoopCount(-1)
        self.set_pulsing(pulsing)

    def get_phase(self):
        return self._phase

    def set_phase(self, value):
        self._phase = value
        self.update()

    phase = Property(float, get_phase, set_phase)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_pulsing(self, pulsing):
        if pulsing:
            if self._animation.state() != QPropertyAnimation.Running:
                self._animation.start()
        else:
            self._animation.stop()
            self._phase = 1.0
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        centre = QPointF(self.width() / 2, self.height() / 2)

        halo = QColor(self._color)
        halo.setAlphaF(0.28 * self._phase)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, self._size / 2 + 3 * self._phase,
                            self._size / 2 + 3 * self._phase)

        painter.setBrush(self._color)
        painter.drawEllipse(centre, self._size / 2, self._size / 2)
        painter.end()


class StatusPill(QWidget):
    """A dot plus a short uppercase label, on a tinted rounded background."""

    def __init__(self, text='UNKNOWN', color=PALETTE.neutral, parent=None,
                 pulsing=False, compact=False):
        super().__init__(parent)
        self._color = QColor(color)
        self._font_size = 10 if compact else 11
        layout = QHBoxLayout(self)
        margin = 6 if compact else 8
        layout.setContentsMargins(margin + 2, margin - 3, margin + 4, margin - 3)
        layout.setSpacing(SPACE_XS + 1)

        self.dot = Dot(color, 8 if compact else 9, pulsing)
        layout.addWidget(self.dot)

        self.label = QLabel(text)
        self.label.setStyleSheet(self._label_style(color))
        layout.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def _label_style(self, color):
        return (f'color: {color}; font-size: {self._font_size}px; '
                'font-weight: 700; letter-spacing: 0.9px;')

    def set_state(self, text, color, pulsing=False):
        self._color = QColor(color)
        self.label.setText(text)
        self.label.setStyleSheet(self._label_style(color))
        self.dot.set_color(color)
        self.dot.set_pulsing(pulsing)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        background = QColor(self._color)
        background.setAlphaF(0.13)
        border = QColor(self._color)
        border.setAlphaF(0.4)
        painter.setBrush(background)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
                                RADIUS_SM + 4, RADIUS_SM + 4)
        painter.end()


class RecordingBeacon(QWidget):
    """
    The unmissable 'we are recording' banner.

    Idle it is a quiet grey strip; recording it turns red, pulses and states
    the elapsed time. There is no way to mistake one for the other.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self._tone = 'idle'
        self._flash = 0.0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(14)

        self.dot = Dot(PALETTE.neutral, 14, False)
        layout.addWidget(self.dot)

        text = QVBoxLayout()
        text.setSpacing(0)
        self.headline = QLabel('IDLE')
        self.headline.setStyleSheet(
            f'color: {PALETTE.text_muted}; font-size: 17px; font-weight: 800; '
            'letter-spacing: 2.2px;')
        text.addWidget(self.headline)
        self.detail = QLabel('Not recording')
        self.detail.setStyleSheet(f'color: {PALETTE.text_dim}; font-size: 12px;')
        text.addWidget(self.detail)
        layout.addLayout(text)
        layout.addStretch(1)

        self.elapsed = QLabel('')
        self.elapsed.setStyleSheet(
            f'color: {PALETTE.text}; font-size: 25px; font-weight: 700; '
            'font-family: "JetBrains Mono","Ubuntu Mono","DejaVu Sans Mono",monospace;')
        layout.addWidget(self.elapsed)

    def set_state(self, tone, headline, detail, elapsed=''):
        self._tone = tone
        colors = {
            'idle': (PALETTE.neutral, PALETTE.text_muted),
            'preparing': (PALETTE.warning, PALETTE.warning),
            'recording': (PALETTE.recording, PALETTE.recording),
            'stopping': (PALETTE.warning, PALETTE.warning),
            'error': (PALETTE.danger, PALETTE.danger),
            'done': (PALETTE.success, PALETTE.success),
        }
        dot_color, text_color = colors.get(tone, colors['idle'])
        self.dot.set_color(dot_color)
        self.dot.set_pulsing(tone in ('recording', 'preparing', 'stopping'))
        self.headline.setText(headline)
        self.headline.setStyleSheet(
            f'color: {text_color}; font-size: 17px; font-weight: 800; letter-spacing: 2.2px;')
        self.detail.setText(detail)
        self.elapsed.setText(elapsed)
        self.elapsed.setStyleSheet(
            f'color: {text_color if tone == "recording" else PALETTE.text}; '
            'font-size: 25px; font-weight: 700; '
            'font-family: "JetBrains Mono","Ubuntu Mono","DejaVu Sans Mono",monospace;')
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        accent = {
            'idle': PALETTE.border_strong,
            'preparing': PALETTE.warning,
            'recording': PALETTE.recording,
            'stopping': PALETTE.warning,
            'error': PALETTE.danger,
            'done': PALETTE.success,
        }.get(self._tone, PALETTE.border_strong)

        background = QColor(accent)
        background.setAlphaF(0.10 if self._tone != 'idle' else 0.0)
        painter.setBrush(background if self._tone != 'idle' else QColor(PALETTE.bg_surface))
        border = QColor(accent)
        border.setAlphaF(0.55 if self._tone != 'idle' else 0.5)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 10, 10)

        # A solid bar down the left edge, so the state reads even in a screenshot.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 4, self.height() - 1), 2, 2)
        painter.end()


class Meter(QWidget):
    """A labelled bar for a bounded quantity: disk, CPU, memory."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_XS + 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE_SM)
        self.label = QLabel(label.upper())
        self.label.setObjectName('CardLabel')
        row.addWidget(self.label)
        row.addStretch(1)
        self.value = QLabel('N/A')
        self.value.setObjectName('Mono')
        self.value.setStyleSheet(f'color: {PALETTE.text_muted}; font-size: 12px;')
        row.addWidget(self.value)
        layout.addLayout(row)

        self._fraction = -1.0
        self._tone = PALETTE.accent
        self.bar = _Bar(self)
        layout.addWidget(self.bar)

    def set_value(self, fraction, text, tone=None):
        """*fraction* in 0..1, or negative for 'not measured'."""
        self._fraction = fraction
        if tone is None:
            tone = (PALETTE.danger if fraction >= 0.9 else
                    PALETTE.warning if fraction >= 0.75 else PALETTE.success)
        self._tone = tone
        self.value.setText(text)
        self.bar.set_value(fraction, tone)


class _Bar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(7)
        self._fraction = -1.0
        self._color = QColor(PALETTE.accent)

    def set_value(self, fraction, color):
        self._fraction = fraction
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(PALETTE.bg_sunken))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3.5, 3.5)
        if self._fraction >= 0:
            width = max(4.0, min(1.0, self._fraction) * self.width())
            painter.setBrush(self._color)
            painter.drawRoundedRect(QRectF(0, 0, width, self.height()), 3.5, 3.5)
        else:
            # Unknown: a faint dashed track rather than an empty bar that
            # could be misread as 'zero'.
            pen = QPen(QColor(PALETTE.border_strong), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
                                    3.5, 3.5)
        painter.end()


class Sparkline(QWidget):
    """
    A tiny trend line for the recording write rate.

    Holds a fixed-length ring of samples; there is no data model behind it and
    it never allocates while running.
    """

    def __init__(self, capacity=90, color=PALETTE.accent, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self._values = []
        self._capacity = capacity
        self._color = QColor(color)

    def push(self, value):
        if value is None or value < 0:
            value = 0.0
        self._values.append(float(value))
        if len(self._values) > self._capacity:
            del self._values[0]
        self.update()

    def clear(self):
        self._values = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width, height = self.width(), self.height()

        if len(self._values) < 2:
            painter.setPen(QPen(QColor(PALETTE.border), 1, Qt.DashLine))
            painter.drawLine(0, height - 1, width, height - 1)
            painter.setPen(QColor(PALETTE.text_dim))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignCenter,
                             'waiting for data')
            painter.end()
            return

        peak = max(self._values) or 1.0
        step = width / max(1, self._capacity - 1)
        points = [QPointF(index * step, height - 2 - (value / peak) * (height - 8))
                  for index, value in enumerate(self._values)]

        fill = QColor(self._color)
        fill.setAlphaF(0.16)
        polygon = points + [QPointF(points[-1].x(), height), QPointF(points[0].x(), height)]
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(polygon)

        painter.setPen(QPen(self._color, 1.8))
        painter.setBrush(Qt.NoBrush)
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)
        painter.end()


class Toast(QWidget):
    """
    A transient message strip shown at the top of the content area.

    Errors stay until dismissed; everything else fades out on its own, because
    an operator should never have to clear a queue of 'saved' popups.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._tone = 'info'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(SPACE_SM + 2)

        self.icon_label = QLabel()
        layout.addWidget(self.icon_label)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message, 1)

        self.close_button = QPushButton()
        self.close_button.setIcon(icons.icon('close', PALETTE.text_muted, 14))
        self.close_button.setProperty('variant', 'ghost')
        self.close_button.setFixedSize(26, 26)
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.close_button)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, tone, text, timeout=6000):
        self._tone = tone
        color = PALETTE.state_color(tone if tone != 'error' else 'danger')
        glyph = {'error': 'error', 'warning': 'warning', 'success': 'check'}.get(tone, 'info')
        self.icon_label.setPixmap(icons.pixmap(glyph, color, 17))
        self.message.setText(text)
        self.message.setStyleSheet(f'color: {PALETTE.text};')
        self.setVisible(True)
        self.update()
        self._timer.stop()
        if tone not in ('error',) and timeout:
            self._timer.start(timeout)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(PALETTE.state_color(self._tone if self._tone != 'error' else 'danger'))
        background = QColor(color)
        background.setAlphaF(0.12)
        painter.setBrush(background)
        painter.setPen(QPen(color, 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        painter.end()
