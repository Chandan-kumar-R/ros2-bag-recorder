"""
Entry point for the dashboard.

Starting the GUI must not depend on ROS being healthy: 
"""
import argparse
import ctypes
import os
import signal
import sys

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.theme import PALETTE, stylesheet
from rosbag_recorder_ui.main_window import MainWindow
from rosbag_recorder_ui.ros.ros_link import DEFAULT_BRIDGE_NS, RosLink


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='rosbag_recorder_ui',
        description='Desktop dashboard for the ROS 2 bag recorder.')
    parser.add_argument(
        '--bridge-namespace', default=DEFAULT_BRIDGE_NS,
        help='Namespace the recorder bridge advertises under '
             f'(default: {DEFAULT_BRIDGE_NS}).')
    parser.add_argument(
        '--config', default='',
        help='Parameter file to load at startup instead of the usual default.')
    parser.add_argument(
        '--managed-bridge', default='',
        help='Set by dashboard.launch.py when the bridge was started alongside '
             'this window, so closing it also stops the recorder.')
    # A launch file appends "--ros-args -r __node:=..."; everything from
    # --ros-args onwards belongs to rclpy, not to us. Truncating there (rather
    # than dropping tokens individually) stops an option with an empty value
    # from swallowing ROS's own arguments as its argument.
    arguments = argv[1:]
    if '--ros-args' in arguments:
        arguments = arguments[:arguments.index('--ros-args')]
    known, _unknown = parser.parse_known_args(arguments)
    return known


def check_platform_prerequisites():
    """
    Fail readably when Qt's X11 plugin cannot load.
    """
    if sys.platform != 'linux' or os.environ.get('QT_QPA_PLATFORM'):
        return ''
    on_wayland = (os.environ.get('XDG_SESSION_TYPE') == 'wayland'
                  and os.environ.get('WAYLAND_DISPLAY'))
    if on_wayland or not os.environ.get('DISPLAY'):
        return ''
    try:
        ctypes.CDLL('libxcb-cursor.so.0')
    except OSError:
        return ('Qt cannot start its X11 backend because libxcb-cursor0 is not '
                'installed.\n\nFix it with:\n    sudo apt install libxcb-cursor0\n\n'
                'Qt 6.5+ needs that library, the PySide6 wheel does not ship it, '
                'and Ubuntu 22.04 does not install it by default.')
    return ''


def application_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(icons.app_icon_svg().encode('utf-8')))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    args = parse_args(argv)

    problem = check_platform_prerequisites()
    if problem:
        print(f'\nROS 2 Bag Recorder cannot start.\n\n{problem}\n', file=sys.stderr)
        return 1

    # Qt picks up HiDPI automatically on Qt6; this only affects icon crispness.
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName('ROS 2 Bag Recorder')
    app.setApplicationDisplayName('ROS 2 Bag Recorder')
    app.setOrganizationName('rosbag_recorder_ui')
    app.setDesktopFileName('rosbag-recorder-ui')
    app.setWindowIcon(application_icon())
    app.setStyleSheet(stylesheet(PALETTE, icons.stylesheet_assets()))

    ros = RosLink(bridge_ns=args.bridge_namespace or DEFAULT_BRIDGE_NS)
    started = ros.start()

    owns_bridge = args.managed_bridge.strip().lower() in ('1', 'true', 'yes', 'on')
    window = MainWindow(ros, owns_bridge=owns_bridge)
    if not started:
        window.log.log(40, ros.start_error)
        window._notify('error', ros.start_error, timeout=0)
    if args.config:
        try:
            window.store.load(os.path.expanduser(args.config))
        except Exception as err:                          # noqa: BLE001
            window._notify('error', f'Could not load {args.config}: {err}')
    window.show()

    app.aboutToQuit.connect(ros.shutdown)
    _install_signal_handlers(app)
    return app.exec()


def _install_signal_handlers(app):
    """
    Quit cleanly on Ctrl-C and on the SIGTERM that `ros2 launch` sends.
    """
    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(number, lambda *_args: app.quit())
        except (ValueError, OSError):
            continue
    heartbeat = QTimer(app)
    heartbeat.start(250)
    heartbeat.timeout.connect(lambda: None)
    return heartbeat


if __name__ == '__main__':
    sys.exit(main())
