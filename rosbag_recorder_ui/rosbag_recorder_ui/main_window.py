"""
The application shell.

Owns the pages and is the only place that knows how a UI event becomes a ROS
service call. 
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rosbag_recorder_msgs.msg import RecorderStatus

from rosbag_recorder_ui.core.config_store import ConfigStore
from rosbag_recorder_ui.core.formatting import human_bytes
from rosbag_recorder_ui.core.history import RecordingHistory
from rosbag_recorder_ui.core.theme import SPACE_LG, SPACE_MD
from rosbag_recorder_ui.ros.ros_link import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARN
from rosbag_recorder_ui.views.configuration import ConfigurationPage
from rosbag_recorder_ui.views.dashboard import DashboardPage
from rosbag_recorder_ui.views.diagnostics import DiagnosticsPage
from rosbag_recorder_ui.views.history_view import HistoryPage
from rosbag_recorder_ui.views.recording import RecordingPage
from rosbag_recorder_ui.views.topics import TopicsPage
from rosbag_recorder_ui.widgets.dialogs import confirm
from rosbag_recorder_ui.widgets.indicators import Toast
from rosbag_recorder_ui.widgets.logpanel import LogPanel
from rosbag_recorder_ui.widgets.sidebar import Sidebar
from rosbag_recorder_ui.widgets.topbar import TopBar

# Config edits are noisy (every keystroke); re-asking the bridge on each one
# would be rude. Wait until the operator pauses.
PREVIEW_DEBOUNCE_MS = 600


class MainWindow(QMainWindow):
    """Everything the operator sees."""

    def __init__(self, ros, store=None, history=None, owns_bridge=False, parent=None):
        super().__init__(parent)
        self.ros = ros
        self.store = store or ConfigStore(self)
        self.history = history or RecordingHistory()
        # True when this window was launched together with the bridge, so
        # closing it takes the bridge down too. It changes what the close
        # confirmation is allowed to promise.
        self.owns_bridge = owns_bridge

        self._status = None
        self._last_state = None
        self._registry_loaded = False
        self._stopping = False
        self._rate_monitor_on = False

        self.setWindowTitle('ROS 2 Bag Recorder')
        self.setMinimumSize(1180, 760)
        self.resize(1480, 940)

        self._build_ui()
        self._wire_pages()
        self._wire_ros()
        self._install_shortcuts()

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.store.notice.connect(
            lambda level, message: self._notify(level, message))
        self.store.changed.connect(lambda _c: self._schedule_preview())

        self.topics_page.apply_config(self.store.config)
        loaded = self.store.load_default()
        self.log.log(LEVEL_INFO, f'Loaded configuration from {loaded}' if loaded
                     else 'Started with the built-in default configuration.')
        self.navigate('dashboard')

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        root.setObjectName('Root')
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        right = QWidget()
        right.setObjectName('Root')
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.topbar = TopBar()
        right_layout.addWidget(self.topbar)

        body = QWidget()
        body.setObjectName('Root')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, 0)
        body_layout.setSpacing(SPACE_MD - 4)

        self.toast = Toast()
        body_layout.addWidget(self.toast)

        self.pages = QStackedWidget()
        self.dashboard_page = DashboardPage()
        self.recording_page = RecordingPage(self.store)
        self.topics_page = TopicsPage()
        self.configuration_page = ConfigurationPage(self.store)
        self.diagnostics_page = DiagnosticsPage()
        self.history_page = HistoryPage(self.history)

        self._page_map = {
            'dashboard': self.dashboard_page,
            'recording': self.recording_page,
            'topics': self.topics_page,
            'configuration': self.configuration_page,
            'diagnostics': self.diagnostics_page,
            'history': self.history_page,
        }
        for page in self._page_map.values():
            self.pages.addWidget(page)
        body_layout.addWidget(self.pages, 1)

        self.log = LogPanel()
        log_holder = QWidget()
        log_holder.setObjectName('BottomPanel')
        log_layout = QVBoxLayout(log_holder)
        log_layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        log_layout.addWidget(self.log)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(True)
        splitter.addWidget(body)
        splitter.addWidget(log_holder)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 200])
        self._log_splitter = splitter
        right_layout.addWidget(splitter, 1)

        layout.addWidget(right, 1)
        self.setCentralWidget(root)

    def _wire_pages(self):
        self.sidebar.navigated.connect(self.navigate)
        self.topbar.stop_requested.connect(self.recording_page._on_stop_clicked)

        self.dashboard_page.configure_requested.connect(
            lambda: self.navigate('recording'))
        self.recording_page.configure_requested.connect(
            lambda: self.navigate('configuration'))
        self.recording_page.start_requested.connect(self._start_recording)
        self.recording_page.stop_requested.connect(self._stop_recording)
        self.recording_page.preview_requested.connect(self._refresh_preview)
        self.configuration_page.changed.connect(self._schedule_preview)
        self.configuration_page.pick_topics_requested.connect(
            lambda: self.navigate('topics'))
        self.configuration_page.registry_save_requested.connect(self._save_registry)
        self.configuration_page.registry_reload_requested.connect(self._fetch_registry)
        self.topics_page.rate_monitor_requested.connect(self._set_rate_monitor)
        self.topics_page.manual_topic_toggled.connect(self._on_manual_topic_toggled)
        self.topics_page.manual_topics_set.connect(self.store.set_manual_topics)
        self.topics_page.manual_mode_requested.connect(self._on_manual_mode_requested)
        self.store.changed.connect(self.topics_page.apply_config)
        self.diagnostics_page.refresh_requested.connect(self._refresh_diagnostics)
        self.log.counts_changed.connect(self._on_log_counts)

    def _wire_ros(self):
        self.ros.status_received.connect(self._on_status)
        self.ros.topics_received.connect(self._on_topic_stats)
        self.ros.log_received.connect(self.log.append)
        self.ros.bridge_online_changed.connect(self._on_bridge_online)
        self.ros.ros_online_changed.connect(self._on_ros_online)
        self.ros.graph_counts.connect(self._on_graph_counts)
        self.ros.ros_terminated.connect(self._on_ros_terminated)

    def _install_shortcuts(self):
        QShortcut(QKeySequence('Ctrl+S'), self,
                  activated=self.configuration_page._on_save)
        QShortcut(QKeySequence('Ctrl+L'), self, activated=self._toggle_log)
        QShortcut(QKeySequence('Ctrl+R'), self, activated=self._refresh_preview)
        for index, key in enumerate(('1', '2', '3', '4', '5', '6')):
            name = list(self._page_map)[index]
            QShortcut(QKeySequence(f'Ctrl+{key}'), self,
                      activated=lambda n=name: self.navigate(n))

    # ------------------------------------------------------------------
    #  Navigation
    # ------------------------------------------------------------------

    def navigate(self, key):
        page = self._page_map.get(key)
        if page is None:
            return
        current = self.pages.currentWidget()
        if current is page:
            return
        if current is not None:
            current.on_hidden()
        self.pages.setCurrentWidget(page)
        self.sidebar.select(key)
        self.topbar.set_context(page.subtitle_text or page.title_text)
        page.on_shown()

    def _toggle_log(self):
        sizes = self._log_splitter.sizes()
        if sizes[1] > 20:
            self._log_splitter.setSizes([sizes[0] + sizes[1], 0])
        else:
            total = sum(sizes)
            self._log_splitter.setSizes([int(total * 0.72), int(total * 0.28)])

    def _notify(self, tone, message, timeout=6000):
        self.toast.show_message(tone, message, timeout)
        level = {'error': LEVEL_ERROR, 'warning': LEVEL_WARN}.get(tone, LEVEL_INFO)
        self.log.log(level, message)

    # ------------------------------------------------------------------
    #  Connection state
    # ------------------------------------------------------------------

    def _on_ros_online(self, online):
        self.sidebar.set_ros_state(online)
        self.topbar.set_graph_state(online)
        if not online:
            self._notify('error', 'Lost the connection to ROS 2.')

    def _on_bridge_online(self, online):
        self.sidebar.set_bridge_state(online)
        self.topbar.set_bridge_state(online)
        for page in (self.dashboard_page, self.recording_page, self.topics_page):
            page.set_connection(self.ros.online, online)
        self.diagnostics_page.set_connection(self.ros.online, online)
        if online:
            self.log.log(LEVEL_INFO, 'Connected to the recorder bridge.')
            self._fetch_registry()
            self._schedule_preview(0)
            self._refresh_diagnostics()
        else:
            self.log.log(LEVEL_WARN, 'The recorder bridge went away.')
            self._notify('warning',
                         'The recorder bridge is not reachable. Start it with: '
                         'ros2 launch rosbag_recorder_bridge bridge.launch.py')

    def _on_ros_terminated(self):
        """
        The ROS 2 context has been torn down, so this window is no longer live.
        """
        self._preview_timer.stop()
        self.diagnostics_page.on_hidden()
        self.topbar.set_graph_state(False)
        self.sidebar.set_ros_state(False)
        self._notify('error',
                     'ROS 2 shut down, so this window is no longer live. Any recording '
                     'the bridge started is unaffected. Close and restart the '
                     'dashboard.', timeout=0)

    def _on_graph_counts(self, nodes, topics):
        self.topbar.set_graph_state(nodes >= 0, nodes)
        self.sidebar.set_ros_state(
            nodes >= 0,
            f'{nodes} node' + ('s' if nodes != 1 else '') if nodes >= 0 else 'offline')
        self.diagnostics_page.set_connection(self.ros.online, self.ros.bridge_online,
                                             nodes, topics)

    def _on_log_counts(self, warnings, errors):
        self.sidebar.set_badge('diagnostics', str(errors) if errors else '')
        self.diagnostics_page.set_log_counts(warnings, errors)

    # ------------------------------------------------------------------
    #  Incoming ROS data
    # ------------------------------------------------------------------

    def _on_status(self, status):
        self._status = status
        self.topbar.set_recorder_state(status.state, status.duration_sec)
        self.dashboard_page.on_status(status)
        self.recording_page.on_status(status)
        self.diagnostics_page.on_status(status)
        # Pages retitle themselves as the recording phase changes; keep the
        # header in step rather than only refreshing it on navigation.
        current = self.pages.currentWidget()
        if current is not None:
            self.topbar.set_context(current.subtitle_text or current.title_text)

        if status.state != self._last_state:
            self._on_state_change(self._last_state, status)
            self._last_state = status.state

    def _on_state_change(self, previous, status):
        names = {0: 'idle', 1: 'preparing', 2: 'recording', 3: 'stopping', 4: 'error'}
        if previous is not None:
            self.log.log(
                LEVEL_ERROR if status.state == RecorderStatus.STATE_ERROR else LEVEL_INFO,
                f'Recorder state: {names.get(previous, previous)} -> '
                f'{names.get(status.state, status.state)}')
        if status.state == RecorderStatus.STATE_RECORDING:
            self.sidebar.set_badge('recording', 'REC', 'danger')
        else:
            self.sidebar.set_badge('recording', '')
        if status.state == RecorderStatus.STATE_ERROR and status.last_error:
            self._notify('error', status.last_error, timeout=0)

    def _on_topic_stats(self, stats):
        self.topics_page.on_topic_stats(stats)

    # ------------------------------------------------------------------
    #  Outgoing requests
    # ------------------------------------------------------------------

    def _schedule_preview(self, delay=PREVIEW_DEBOUNCE_MS):
        self._preview_timer.start(delay)

    def _refresh_preview(self):
        if not self.ros.bridge_online:
            self.recording_page.set_preview(None, 'the recorder bridge is not running')
            return
        config = self.store.config
        self.ros.preview_selection(
            config,
            lambda response: self.recording_page.set_preview(response),
            lambda message: self.recording_page.set_preview(None, message))
        self.ros.validate_output(
            config,
            lambda response: self.recording_page.set_validation(response),
            lambda message: self.recording_page.set_validation(None, message))

    def _fetch_registry(self):
        self.ros.get_registry(
            self.store.config.registry_file,
            self._on_registry,
            lambda message: self.log.log(LEVEL_WARN,
                                         f'Could not read the topic registry: {message}'))

    def _on_registry(self, response):
        if not response.success:
            self.log.log(LEVEL_WARN, response.message)
            self._notify('warning', response.message)
            return
        self.configuration_page.set_registry(response.registry_yaml,
                                             response.registry_path,
                                             list(response.modules))
        if not self._registry_loaded:
            self._registry_loaded = True
            self.log.log(LEVEL_INFO,
                         f'Topic registry loaded: {len(response.modules)} module(s) '
                         f'from {response.registry_path}')

    def _save_registry(self, registry_file, registry_yaml):
        """Write the edited registry on the machine that will read it back."""
        if not self.ros.bridge_online:
            self.configuration_page.registry_saved(
                error='The recorder bridge is not reachable, so nothing was written.')
            return
        self.ros.set_registry(registry_file, registry_yaml,
                              self._on_registry_saved,
                              lambda message: self.configuration_page.registry_saved(
                                  error=message))

    def _on_registry_saved(self, response):
        self.configuration_page.registry_saved(response)
        if not response.success:
            self.log.log(LEVEL_ERROR, f'Registry not saved: {response.message}')
            return
        self.log.log(LEVEL_INFO, f'{response.message} ({response.registry_path})')
        self._notify('success', response.message, timeout=5000)
        # Re-read it, so what the page shows is what the bridge now has rather
        # than what we hoped it would have.
        self._fetch_registry()
        self._schedule_preview(0)

    def _refresh_diagnostics(self):
        if not self.ros.bridge_online or not self.ros.online:
            return
        self.ros.get_diagnostics(
            self._on_diagnostics,
            lambda message: self.diagnostics_page.set_diagnostics(None, message))

    def _on_diagnostics(self, diag):
        self.diagnostics_page.set_diagnostics(diag)
        # The only place the operator is told, on every page, which machine is
        # doing the recording.
        self.topbar.set_bridge_state(self.ros.bridge_online, diag.hostname)

    def _on_manual_topic_toggled(self, name, ticked):
        self.store.set_manual_topic(name, ticked)

    def _on_manual_mode_requested(self, seed):
        """
        Switch selection mode on behalf of the Topics page.
        """
        if seed or self.store.config.selection_method != 'manual':
            self.store.update(selection_method='manual',
                              manual_topics=sorted(seed))
            self.log.log(LEVEL_INFO,
                         f'Manual topic selection: {len(seed)} topic(s) ticked.')
        else:
            previous = ('keywords' if self.store.config.keywords else 'registry')
            self.store.update(selection_method=previous)
            self.log.log(LEVEL_INFO, f'Selection method back to {previous}.')

    def _set_rate_monitor(self, enabled, topics=()):
        self._rate_monitor_on = enabled
        self.ros.set_rate_monitor(
            enabled, list(topics),
            lambda response: self.log.log(LEVEL_INFO, response.message),
            lambda message: self._notify('warning',
                                         f'Rate measurement failed: {message}'))

    # -- start / stop ----------------------------------------------------

    def _start_recording(self, config):
        self.log.log(LEVEL_INFO,
                     f'Starting recording "{config.bag_name}" in {config.bag_path}')
        self.ros.start_recording(config, self._on_start_response,
                                 self._on_start_error)

    def _on_start_response(self, response):
        if not response.success:
            self.recording_page.start_failed(response.message, response.detail)
            self.log.log(LEVEL_ERROR, f'Start refused: {response.message}')
            return
        self.recording_page.start_succeeded()
        self._notify('success', response.message, timeout=5000)
        for warning in response.warnings:
            self._notify('warning', warning)
        self.navigate('recording')

    def _on_start_error(self, message):
        self.recording_page.start_failed(
            'The recorder bridge could not be reached, so nothing was started.', message)
        self.log.log(LEVEL_ERROR, f'Start failed: {message}')

    def _stop_recording(self):
        self._stopping = True
        self.log.log(LEVEL_INFO, 'Stopping the recording; waiting for the writers to '
                                 'close.')
        self.ros.stop_recording(self._on_stop_response, self._on_stop_error)

    def _on_stop_response(self, response):
        self._stopping = False
        summary = response.summary
        if response.success:
            self.history.add_from_summary(summary)
            self.recording_page.show_summary(summary)
            # _notify already writes the line to the log; do not double it.
            self._notify('success',
                         f'{summary.bag_name}: {summary.topic_count} topic(s), '
                         f'{human_bytes(summary.total_size_bytes)} written.',
                         timeout=9000)
        else:
            self.history.add_from_summary(summary, status='error',
                                          note=response.message)
            self.recording_page.show_summary(summary, warning=response.message)
            self.recording_page.stop_failed(response.message, response.detail)
            self.log.log(LEVEL_ERROR, f'Stop reported a problem: {response.message}')
        self.history_page.reload()

    def _on_stop_error(self, message):
        self._stopping = False
        self.recording_page.stop_failed(
            'The bridge did not confirm that the recording stopped. The bag may still '
            'be open - check the recorder before using it.', message)
        self.log.log(LEVEL_ERROR, f'Stop failed: {message}')

    # ------------------------------------------------------------------

    def closeEvent(self, event):
        recording = (self._status is not None
                     and self._status.state in (RecorderStatus.STATE_RECORDING,
                                                RecorderStatus.STATE_PREPARING))
        if recording:
            if self.owns_bridge:
                message = ('The recorder was started together with this window, so '
                           'closing it will stop the recording and close the bag. '
                           'Close anyway?')
            else:
                message = ('Closing the dashboard does not stop the recording - the '
                           'bridge keeps writing. Close anyway?')
            if not confirm(self, 'A recording is still running', message,
                           confirm_text='Close dashboard', tone='warning'):
                event.ignore()
                return
        if self.store.dirty and not confirm(
                self, 'Unsaved configuration',
                'The configuration has changes that were never saved to a file.',
                confirm_text='Close without saving'):
            event.ignore()
            return
        event.accept()
