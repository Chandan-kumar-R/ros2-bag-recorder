"""
The only place in the dashboard that touches rclpy.

Threading contract, because getting this wrong is how Qt applications freeze:

* rclpy spins on a private worker thread.
* Data crosses into Qt exclusively as signals. 
* Service calls are asynchronous with an explicit timeout.

The dashboard subscribes only to status, statistics and logs. It never
subscribes to a recorded topic, so a 4K image stream costs it nothing.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field

import rclpy
from PySide6.QtCore import QObject, QTimer, Signal
from rcl_interfaces.msg import Log
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from rosbag_recorder_msgs.msg import RecorderStatus, TopicStats
from rosbag_recorder_msgs.srv import (
    GetDiagnostics,
    GetRegistry,
    PreviewSelection,
    SetRateMonitor,
    SetRegistry,
    StartRecording,
    StopRecording,
    ValidateOutput,
)

DEFAULT_BRIDGE_NS = '/rosbag_recorder_bridge'

LEVEL_DEBUG, LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR, LEVEL_FATAL = 10, 20, 30, 40, 50
LEVEL_NAMES = {LEVEL_DEBUG: 'DEBUG', LEVEL_INFO: 'INFO', LEVEL_WARN: 'WARN',
               LEVEL_ERROR: 'ERROR', LEVEL_FATAL: 'FATAL'}

# Log lines from these nodes are the ones an operator cares about. Everything
# else on /rosout is somebody else's business.
LOG_SOURCES = ('rosbag_recorder_bridge', 'ros2_bag_recorder_node', 'rosbag_recorder')

LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL,
                     history=HistoryPolicy.KEEP_LAST)


@dataclass
class LogRecord:
    stamp: float
    level: int
    name: str
    message: str

    @property
    def level_name(self):
        return LEVEL_NAMES.get(self.level, 'INFO')


@dataclass
class _Pending:
    callback: object
    errback: object
    future: object
    timer: object = None
    extra: dict = field(default_factory=dict)


class _DashboardNode(Node):
    """The rclpy side. Holds no Qt objects and knows nothing about widgets."""

    def __init__(self, link, bridge_ns):
        super().__init__('rosbag_recorder_dashboard')
        self._link = link
        self.bridge_ns = bridge_ns.rstrip('/')

        self.create_subscription(RecorderStatus, f'{self.bridge_ns}/status',
                                 self._on_status, LATCHED)
        self.create_subscription(TopicStats, f'{self.bridge_ns}/topic_stats',
                                 self._on_topics, LATCHED)
        self.create_subscription(Log, '/rosout', self._on_log, 50)

        self.clients_by_name = {
            'start': self.create_client(StartRecording, f'{self.bridge_ns}/start_recording'),
            'stop': self.create_client(StopRecording, f'{self.bridge_ns}/stop_recording'),
            'preview': self.create_client(PreviewSelection,
                                          f'{self.bridge_ns}/preview_selection'),
            'validate': self.create_client(ValidateOutput, f'{self.bridge_ns}/validate_output'),
            'rate': self.create_client(SetRateMonitor, f'{self.bridge_ns}/set_rate_monitor'),
            'diagnostics': self.create_client(GetDiagnostics,
                                              f'{self.bridge_ns}/get_diagnostics'),
            'registry': self.create_client(GetRegistry, f'{self.bridge_ns}/get_registry'),
            'set_registry': self.create_client(SetRegistry,
                                               f'{self.bridge_ns}/set_registry'),
        }
        self.create_timer(1.0, self._on_heartbeat)

    def _on_status(self, message):
        self._link.status_received.emit(message)
        self._link.note_bridge_seen()

    def _on_topics(self, message):
        self._link.topics_received.emit(message)
        self._link.note_bridge_seen()

    def _on_log(self, message):
        if not any(source in message.name for source in LOG_SOURCES):
            return
        stamp = message.stamp.sec + message.stamp.nanosec * 1e-9
        self._link.log_received.emit(
            LogRecord(stamp or time.time(), message.level, message.name, message.msg))

    def _on_heartbeat(self):
        try:
            ready = self.clients_by_name['start'].service_is_ready()
            nodes = len(self.get_node_names())
            topics = len(self.get_topic_names_and_types())
        except Exception:                                 # noqa: BLE001
            # The context can be torn down under us (a SIGTERM from ros2 launch,
            # or Ctrl-C in the launching terminal). Report offline rather than
            # letting an RCLError escape into the timer every tick.
            ready, nodes, topics = False, -1, -1
        self._link.heartbeat.emit(bool(ready), nodes, topics)


class RosLink(QObject):
    """Qt-facing handle on the ROS graph."""

    status_received = Signal(object)     # RecorderStatus
    topics_received = Signal(object)     # TopicStats
    log_received = Signal(object)        # LogRecord
    heartbeat = Signal(bool, int, int)   # bridge_ready, node_count, topic_count

    bridge_online_changed = Signal(bool)
    ros_online_changed = Signal(bool)
    graph_counts = Signal(int, int)      # nodes, topics
    ros_terminated = Signal()            # rclpy went away; the window is now dead weight

    # Emitted from the ROS thread when a service future resolves. A queued
    # signal is the only safe way back onto the GUI thread - a QTimer created
    # over there would never fire, because that thread runs no event loop.
    _call_done = Signal(str, object, object)   # token, result, error

    def __init__(self, bridge_ns=DEFAULT_BRIDGE_NS, parent=None):
        super().__init__(parent)
        self.bridge_ns = bridge_ns
        self._node = None
        self._executor = None
        self._thread = None
        self._pending = {}
        self._bridge_online = False
        self._ros_online = False
        self._last_bridge_message = 0.0
        self.start_error = ''

        self.heartbeat.connect(self._on_heartbeat)
        self._call_done.connect(self._deliver)

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """
        Bring up rclpy, returning True on success.

        On failure the reason is in ``start_error`` and the dashboard runs in a
        clearly-degraded state rather than refusing to open.
        """
        try:
            if not rclpy.ok():
                rclpy.init()
            self._node = _DashboardNode(self, self.bridge_ns)
        except Exception as err:                          # noqa: BLE001
            self.start_error = (
                'ROS 2 is not available. Source your workspace and restart '
                f'the dashboard. ({type(err).__name__}: {err})')
            self._set_ros_online(False)
            return False

        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, name='ros-link', daemon=True)
        self._thread.start()
        self._set_ros_online(True)
        return True

    def _spin(self):
        try:
            while rclpy.ok() and self._executor is not None:
                self._executor.spin_once(timeout_sec=0.1)
        except Exception:                                 # noqa: BLE001
            pass
        finally:
            # Either rclpy shut down under us or the executor died. Both mean
            # the same thing to the operator: this window is no longer live.
            if self._executor is not None:
                self._set_ros_online(False)
                self.ros_terminated.emit()

    def shutdown(self):
        executor, self._executor = self._executor, None
        if self._thread is not None:
            self._thread.join(2.0)
            self._thread = None
        for pending in list(self._pending.values()):
            if pending.timer is not None:
                pending.timer.stop()
        self._pending.clear()
        try:
            if executor is not None:
                executor.shutdown()
            if self._node is not None:
                self._node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:                                 # noqa: BLE001
            # Shutting down twice, or after rclpy already tore itself down on a
            # signal, is not worth an error on the way out.
            pass
        self._node = None

    @property
    def online(self):
        return self._ros_online

    @property
    def bridge_online(self):
        return self._bridge_online

    def note_bridge_seen(self):
        self._last_bridge_message = time.time()

    def _set_ros_online(self, value):
        if value != self._ros_online:
            self._ros_online = value
            self.ros_online_changed.emit(value)

    def _on_heartbeat(self, ready, nodes, topics):
        """Handle a heartbeat on the GUI thread; the signal is queued across."""
        fresh = (time.time() - self._last_bridge_message) < 5.0
        online = bool(ready or fresh)
        if online != self._bridge_online:
            self._bridge_online = online
            self.bridge_online_changed.emit(online)
        self._set_ros_online(nodes >= 0)
        self.graph_counts.emit(nodes, topics)

    # ------------------------------------------------------------------
    #  Service calls
    # ------------------------------------------------------------------

    def call(self, client_key, request, callback, errback=None, timeout=15.0):
        """
        Fire a service call and deliver the result on the GUI thread.

        *callback* receives the response; *errback* receives a single
        operator-readable string. Exactly one of them is always invoked.
        """
        errback = errback or (lambda message: None)
        if self._node is None:
            QTimer.singleShot(0, lambda: errback('The dashboard is not connected to ROS 2.'))
            return None
        client = self._node.clients_by_name.get(client_key)
        if client is None:
            QTimer.singleShot(0, lambda: errback(f'Unknown service {client_key!r}.'))
            return None

        token = uuid.uuid4().hex
        try:
            if not client.service_is_ready():
                QTimer.singleShot(0, lambda: errback(
                    'The recorder bridge is not running, so this cannot be done yet.'))
                return None
            future = client.call_async(request)
        except Exception as err:                          # noqa: BLE001
            # Almost always a torn-down rclpy context; the UI stays alive and
            # simply reports that it cannot reach ROS. The message is bound to a
            # local now because Python unbinds `err` at the end of this block.
            reason = f'The connection to ROS 2 is no longer usable ({err}).'
            self._set_ros_online(False)
            QTimer.singleShot(0, lambda: errback(reason))
            return None
        pending = _Pending(callback=callback, errback=errback, future=future)
        self._pending[token] = pending

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_timeout(token, timeout))
        timer.start(int(timeout * 1000))
        pending.timer = timer

        future.add_done_callback(lambda fut, tok=token: self._on_done(tok, fut))
        return token

    def _on_done(self, token, future):
        # Runs on the ROS thread; the signal bounces us to the GUI thread.
        try:
            result = future.result()
            error = None
        except Exception as err:                          # noqa: BLE001
            result, error = None, f'{type(err).__name__}: {err}'
        self._call_done.emit(token, result, error)

    def _deliver(self, token, result, error):
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        if pending.timer is not None:
            pending.timer.stop()
        if error is not None or result is None:
            pending.errback(error or 'The recorder bridge returned nothing.')
        else:
            pending.callback(result)

    def _on_timeout(self, token, timeout):
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        try:
            pending.future.cancel()
        except Exception:                                 # noqa: BLE001
            pass
        pending.errback(f'The recorder bridge did not answer within {timeout:.0f} s.')

    # -- typed conveniences --------------------------------------------

    def start_recording(self, config, callback, errback=None):
        request = StartRecording.Request()
        request.config = config
        return self.call('start', request, callback, errback, timeout=30.0)

    def stop_recording(self, callback, errback=None):
        return self.call('stop', StopRecording.Request(), callback, errback, timeout=45.0)

    def preview_selection(self, config, callback, errback=None):
        request = PreviewSelection.Request()
        request.config = config
        return self.call('preview', request, callback, errback, timeout=10.0)

    def validate_output(self, config, callback, errback=None):
        request = ValidateOutput.Request()
        request.bag_path = config.bag_path
        request.bag_name = config.bag_name
        request.append_timestamp = config.append_timestamp
        request.storage_sqlite = config.storage_sqlite
        request.storage_mcap = config.storage_mcap
        return self.call('validate', request, callback, errback, timeout=10.0)

    def set_rate_monitor(self, enabled, topics, callback, errback=None):
        request = SetRateMonitor.Request()
        request.enabled = enabled
        request.topics = list(topics)
        return self.call('rate', request, callback, errback, timeout=10.0)

    def get_diagnostics(self, callback, errback=None):
        return self.call('diagnostics', GetDiagnostics.Request(), callback, errback,
                         timeout=10.0)

    def get_registry(self, registry_file, callback, errback=None):
        request = GetRegistry.Request()
        request.registry_file = registry_file or ''
        return self.call('registry', request, callback, errback, timeout=10.0)

    def set_registry(self, registry_file, registry_yaml, callback, errback=None):
        request = SetRegistry.Request()
        request.registry_file = registry_file or ''
        request.registry_yaml = registry_yaml
        return self.call('set_registry', request, callback, errback, timeout=15.0)
