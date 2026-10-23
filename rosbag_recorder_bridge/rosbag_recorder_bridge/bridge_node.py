"""
The ROS control surface for ros2_bag_recorder.

This node is the only thing that talks to the recorder. It exposes recording as
services and publishes what is happening as topics, so a dashboard - or a
mission script, or another node - can drive a recording without importing
rosbag2 or knowing that WriterPool exists.

It is headless on purpose. Run it on the robot; run the dashboard wherever the
operator is sitting.
"""
import os
import threading
import time

import rclpy
import yaml
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from rosbag_recorder_msgs.msg import RecorderStatus, RecordingConfig, TopicStat, TopicStats
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

from rosbag_recorder_bridge import sysinfo
from rosbag_recorder_bridge.graph import GraphCache
from rosbag_recorder_bridge.rate_monitor import RateMonitor
from rosbag_recorder_bridge.recorder_api import (
    RegistryError,
    compile_patterns,
    default_registry_path,
    load_enabled_entries,
    load_registry,
    match_topics,
    selectors_for,
)
from rosbag_recorder_bridge.session import (
    RecordingSession,
    SessionError,
    registered_writers,
)

# Latched: a dashboard that connects late still learns the state immediately.
LATCHED = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class RecorderBridge(Node):
    """Owns at most one RecordingSession and reports on it."""

    def __init__(self, **kwargs):
        super().__init__('rosbag_recorder_bridge', **kwargs)

        self.declare_parameter('status_period_sec', 0.5)
        self.declare_parameter('topic_stats_period_sec', 1.0)
        self.declare_parameter('registry_file', '')
        self.declare_parameter('default_bag_path', '~/rosbags')
        self.declare_parameter('stop_timeout_sec', 15.0)

        self._lock = threading.RLock()
        self._session = None
        self._state = RecorderStatus.STATE_IDLE
        self._state_detail = ''
        self._last_error = ''
        self._last_summary = None
        self._started_wall = None
        self._boot_time = time.time()

        # The most recent config the dashboard previewed. Used to colour the
        # topic table; replaced by the live config while a recording runs.
        self._staged_config = self._default_config()
        self._selection = (set(), set())      # (matched, excluded)
        self._unmatched = []
        self._warned_lost = set()             # topics already logged as lost

        self._graph = GraphCache(self)
        self._services_group = MutuallyExclusiveCallbackGroup()
        self._timers_group = MutuallyExclusiveCallbackGroup()
        self._probe_group = MutuallyExclusiveCallbackGroup()
        self._rates = RateMonitor(self, self._probe_group)
        self._rate_monitor_enabled = False
        self._rate_monitor_topics = []

        self._status_pub = self.create_publisher(RecorderStatus, '~/status', LATCHED)
        self._topics_pub = self.create_publisher(TopicStats, '~/topic_stats', LATCHED)

        self._make_service(StartRecording, '~/start_recording', self._on_start)
        self._make_service(StopRecording, '~/stop_recording', self._on_stop)
        self._make_service(PreviewSelection, '~/preview_selection', self._on_preview)
        self._make_service(ValidateOutput, '~/validate_output', self._on_validate)
        self._make_service(SetRateMonitor, '~/set_rate_monitor', self._on_set_rate_monitor)
        self._make_service(GetDiagnostics, '~/get_diagnostics', self._on_diagnostics)
        self._make_service(GetRegistry, '~/get_registry', self._on_get_registry)
        self._make_service(SetRegistry, '~/set_registry', self._on_set_registry)

        self.create_timer(max(0.1, self.get_parameter('status_period_sec').value),
                          self._publish_status, callback_group=self._timers_group)
        self.create_timer(max(0.2, self.get_parameter('topic_stats_period_sec').value),
                          self._publish_topic_stats, callback_group=self._timers_group)

        self.get_logger().info('Recorder bridge ready. No recording is running.')

    def _make_service(self, srv_type, name, handler):
        return self.create_service(srv_type, name, handler,
                                   callback_group=self._services_group)

    # ------------------------------------------------------------------
    #  Config helpers
    # ------------------------------------------------------------------

    def _default_config(self):
        config = RecordingConfig()
        config.selection_method = RecordingConfig.SELECTION_REGISTRY
        config.bag_path = self.get_parameter('default_bag_path').value
        config.bag_name = 'recording'
        config.append_timestamp = True
        config.storage_sqlite = True
        config.storage_mcap = False
        config.discovery_interval_sec = 1.0
        config.registry_file = self.get_parameter('registry_file').value
        return config

    def _registry_path(self, override=''):
        return override or self.get_parameter('registry_file').value or default_registry_path()

    def _evaluate(self, config, live_topics):
        """
        Work out what *config* selects on the current graph.

        Returns (matched, excluded, unmatched_selector_labels). Raises
        RegistryError for a malformed registry or a bad regex, which the
        callers turn into an operator-readable message.
        """
        registry = {}
        if config.selection_method == RecordingConfig.SELECTION_REGISTRY:
            registry, _path = load_registry(self._registry_path(config.registry_file))
        exact, includes = selectors_for(config, registry)
        excludes = compile_patterns([p for p in config.exclude_patterns if p])

        selected = match_topics(live_topics, exact, includes, [])
        matched = match_topics(live_topics, exact, includes, excludes)
        excluded = selected - matched

        if config.selection_method == RecordingConfig.SELECTION_KEYWORDS:
            labels = [k for k in config.keywords if k]
        else:
            labels = [pattern.pattern for pattern in includes]
        unmatched = sorted(exact - set(live_topics))
        for label, pattern in zip(labels, includes):
            if not any(pattern.fullmatch(name) for name in live_topics):
                unmatched.append(label)
        return matched, excluded, unmatched

    # ------------------------------------------------------------------
    #  Services
    # ------------------------------------------------------------------

    def _on_preview(self, request, response):
        """
        Answer 'what would this record right now?' and stage the config.

        Staging is what lets the topic table colour rows without the dashboard
        having to re-implement any matching logic of its own.
        """
        live = self._graph.types or self._graph.scan()
        try:
            matched, excluded, unmatched = self._evaluate(request.config, live.keys())
        except RegistryError as err:
            response.success = False
            response.message = str(err)
            return response
        except Exception as err:                          # noqa: BLE001
            response.success = False
            response.message = 'The selection could not be evaluated.'
            response.warnings = [f'{type(err).__name__}: {err}']
            return response

        with self._lock:
            if self._state == RecorderStatus.STATE_IDLE:
                self._staged_config = request.config
            self._selection = (matched, excluded)
            self._unmatched = unmatched

        response.success = True
        response.matched_topics = sorted(matched)
        response.matched_types = [live.get(name, '') for name in response.matched_topics]
        response.excluded_topics = sorted(excluded)
        response.unmatched_selectors = unmatched
        response.message = (f'{len(matched)} topic(s) would be recorded.' if matched
                            else 'No live topic matches this selection.')
        if not matched:
            response.warnings = ['Nothing to record: check the modules, keywords '
                                 'and exclude patterns.']
        return response

    def _on_validate(self, request, response):
        config = RecordingConfig()
        config.bag_path = request.bag_path
        config.bag_name = request.bag_name
        config.append_timestamp = request.append_timestamp
        config.storage_sqlite = request.storage_sqlite
        config.storage_mcap = request.storage_mcap
        session = RecordingSession(config, self.get_logger())

        response.path_exists = os.path.isdir(session.bag_path)
        response.path_writable = sysinfo.is_writable(session.bag_path)
        response.collision_uris = [uri for uri in session.bag_uris if os.path.exists(uri)]
        response.collision = bool(response.collision_uris)
        free, total, _mount = sysinfo.disk_usage(session.bag_path)
        response.disk_free_bytes = free
        response.disk_total_bytes = total
        response.available_writers = sorted(registered_writers())

        missing = session.missing_writers()
        if not session.formats:
            response.ok = False
            response.message = 'Pick at least one storage format.'
        elif missing:
            # Caught here rather than at START, so the operator learns that MCAP
            # is unavailable while the checkbox is still in front of them.
            response.ok = False
            response.message = (f"The '{missing[0]}' storage plugin is not installed "
                                'on the recording machine.')
        elif not response.path_writable:
            response.ok = False
            response.message = f'{session.bag_path} is not writable.'
        elif response.collision:
            response.ok = False
            response.message = f'A bag named {session.bag_name} is already there.'
        else:
            response.ok = True
            response.message = f'Ready to write to {session.bag_path}.'
        if total and free < 5 << 30:
            response.warnings = [f'Only {sysinfo.human_bytes(free)} free on this disk.']
        return response

    def _on_start(self, request, response):
        with self._lock:
            if self._session is not None:
                response.success = False
                response.message = 'A recording is already running. Stop it first.'
                return response
            self._set_state(RecorderStatus.STATE_PREPARING, 'validating configuration')

        session = RecordingSession(request.config, self.get_logger())
        try:
            # Fail before touching the disk if the selection is nonsense.
            live = self._graph.scan()
            matched, _excluded, _unmatched = self._evaluate(request.config, live.keys())
            if not matched:
                raise SessionError(
                    'Nothing on the graph matches this selection, so there is '
                    'nothing to record.')
            warnings = session.start()
        except (SessionError, RegistryError) as err:
            detail = getattr(err, 'detail', '')
            message = getattr(err, 'message', str(err))
            with self._lock:
                self._set_state(RecorderStatus.STATE_ERROR, 'start failed')
                self._last_error = message
            self.get_logger().error(f'Start failed: {message} {detail}'.strip())
            response.success = False
            response.message = message
            response.detail = detail
            return response
        except Exception as err:                          # noqa: BLE001
            with self._lock:
                self._set_state(RecorderStatus.STATE_ERROR, 'start failed')
                self._last_error = 'The recorder could not be started.'
            self.get_logger().error(f'Start failed: {err}')
            response.success = False
            response.message = 'The recorder could not be started.'
            response.detail = f'{type(err).__name__}: {err}'
            return response

        with self._lock:
            self._session = session
            self._staged_config = request.config
            self._started_wall = time.time()
            self._last_error = ''
            self._last_summary = None
            self._set_state(RecorderStatus.STATE_RECORDING, '')
            # The recorder counts its own messages; drop any probes duplicating it.
            if self._rate_monitor_enabled:
                self._rates.sync(set(self._rate_monitor_topics) - matched)

        self.get_logger().info(
            f"Recording started: {session.bag_name} -> {', '.join(session.bag_uris)}")
        response.success = True
        response.message = f'Recording {len(matched)} topic(s) to {session.bag_name}.'
        response.bag_uris = session.bag_uris
        response.warnings = warnings
        return response

    def _on_stop(self, request, response):
        with self._lock:
            session = self._session
            if session is None:
                response.success = False
                response.message = 'Nothing is being recorded.'
                return response
            self._set_state(RecorderStatus.STATE_STOPPING, 'closing writers')

        timeout = float(self.get_parameter('stop_timeout_sec').value)
        # Fresh, not cached: this is the number the operator will be shown.
        counts = dict(session.snapshot(max_age=0.0)['counts'])
        error = None
        try:
            session.stop(timeout=timeout)
        except SessionError as err:
            error = err

        summary = self._build_summary(session, counts)
        with self._lock:
            self._session = None
            self._last_summary = summary
            if error is not None:
                self._set_state(RecorderStatus.STATE_ERROR, 'stop reported an error')
                self._last_error = error.message
            else:
                self._set_state(RecorderStatus.STATE_IDLE, '')
            if self._rate_monitor_enabled:
                self._rates.sync(self._rate_monitor_topics)

        response.summary = summary
        response.success = error is None
        if error is not None:
            response.message = error.message
            response.detail = error.detail
            self.get_logger().error(f'Stop failed: {error.message}')
        else:
            response.message = (
                f'Recording finished: {summary.topic_count} topic(s), '
                f'{sysinfo.human_bytes(summary.total_size_bytes)} in '
                f'{summary.duration_sec:.0f} s.')
            self.get_logger().info(response.message)
        return response

    def _on_set_rate_monitor(self, request, response):
        with self._lock:
            recording = set()
            if self._session is not None:
                recording = set(self._session.snapshot()['topics'])
            wanted = set(request.topics) if request.topics else set(self._selection[0])
            self._rate_monitor_enabled = request.enabled
            self._rate_monitor_topics = sorted(wanted)
            target = (wanted - recording) if request.enabled else set()
            attached, failed = self._rates.sync(target)

        response.success = True
        response.monitored = attached
        if not request.enabled:
            response.message = 'Rate probes removed.'
        elif failed:
            response.message = (f'Probing {len(attached)} topic(s); '
                                f'{len(failed)} could not be probed.')
        else:
            response.message = f'Probing {len(attached)} topic(s).'
        return response

    def _on_diagnostics(self, request, response):
        response.success = True
        response.hostname = sysinfo.hostname()
        response.ros_distro = os.environ.get('ROS_DISTRO', 'unknown')
        try:
            response.ros_domain_id = int(os.environ.get('ROS_DOMAIN_ID', '0'))
        except ValueError:
            response.ros_domain_id = -1

        try:
            names = self.get_node_names_and_namespaces()
            response.node_count = len(names)
            response.topic_count = len(self.get_topic_names_and_types())
            services = self.get_service_names_and_types()
            response.service_count = len(services)
            # Actions surface as a set of hidden services; counting the goal
            # service is the cheapest reliable proxy without action_msgs.
            response.action_count = sum(
                1 for _name, types in services
                if any(t.endswith('_SendGoal') for t in types))
        except Exception as err:                          # noqa: BLE001
            response.success = False
            response.message = 'The ROS graph could not be queried.'
            response.errors = [f'{type(err).__name__}: {err}']
            return response

        response.cpu_percent = sysinfo.cpu_percent()
        percent, used, total = sysinfo.memory()
        response.memory_percent = percent
        response.memory_used_bytes = used
        response.memory_total_bytes = total

        with self._lock:
            path = (self._session.bag_path if self._session
                    else os.path.expanduser(self._staged_config.bag_path or '~'))
        free, disk_total, mount = sysinfo.disk_usage(path)
        response.disk_free_bytes = free
        response.disk_total_bytes = disk_total
        response.disk_mount = mount
        response.bridge_uptime_sec = time.time() - self._boot_time

        warnings = []
        if percent < 0:
            warnings.append('psutil is not installed; CPU and memory are unavailable.')
        if disk_total and free < 5 << 30:
            warnings.append(f'Only {sysinfo.human_bytes(free)} free on {mount}.')
        with self._lock:
            if self._last_error:
                response.errors = [self._last_error]
        response.warnings = warnings
        response.message = 'Bridge healthy.' if not warnings else warnings[0]
        return response

    def _on_get_registry(self, request, response):
        path = self._registry_path(request.registry_file)
        try:
            registry, path = load_registry(path)
        except RegistryError as err:
            response.success = False
            response.message = str(err)
            response.registry_path = path
            return response
        try:
            with open(path, 'r') as handle:
                response.registry_yaml = handle.read()
        except OSError as err:
            response.registry_yaml = ''
            response.message = f'Registry parsed but could not be re-read: {err}'
        response.success = True
        response.registry_path = path
        response.modules = sorted(registry)
        if not response.message:
            response.message = f'{len(registry)} module(s) available.'
        return response

    def _on_set_registry(self, request, response):
        """
        Write a topic registry back, after proving the recorder would accept it.
        """
        path = self._registry_path(request.registry_file)
        response.registry_path = path

        try:
            parsed = yaml.safe_load(request.registry_yaml)
        except yaml.YAMLError as err:
            response.success = False
            response.message = f'That is not valid YAML: {err}'
            return response
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            response.success = False
            response.message = 'A registry must be a mapping of module name to entries.'
            return response
        try:
            load_enabled_entries(parsed, set(parsed))
        except RegistryError as err:
            response.success = False
            response.message = str(err)
            return response

        with self._lock:
            recording = self._state == RecorderStatus.STATE_RECORDING
        if recording:
            # The running recorder read the registry at start and will not read
            # it again, but the next scan of a *pattern* module uses the
            # compiled selectors it already holds. Saving is still safe; say so
            # rather than letting the operator wonder.
            response.message = ('Saved. The recording already running keeps the '
                                'selection it started with.')

        temporary = f'{path}.{os.getpid()}.tmp'
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(temporary, 'w') as handle:
                handle.write(request.registry_yaml)
            os.replace(temporary, path)
        except OSError as err:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            response.success = False
            response.message = f'Cannot write {path}: {err.strerror or err}'
            return response

        response.success = True
        response.modules = sorted(parsed)
        if not response.message:
            response.message = f'Registry saved: {len(parsed)} module(s).'
        self.get_logger().info(f'Topic registry written to {path}.')
        return response

    # ------------------------------------------------------------------
    #  Publishing
    # ------------------------------------------------------------------

    def _set_state(self, state, detail):
        """Caller must hold the lock."""
        if state != self._state:
            self._state = state
            self._state_detail = detail
            self._publish_status()
        else:
            self._state_detail = detail

    def _publish_status(self):
        message = RecorderStatus()
        message.stamp = self.get_clock().now().to_msg()

        with self._lock:
            session = self._session
            message.state = self._state
            message.state_detail = self._state_detail
            message.last_error = self._last_error
            message.config = self._staged_config

        if session is not None:
            snapshot = session.snapshot()
            if snapshot['error']:
                self._salvage(session, snapshot['error'])
                return
            # lost_topics is maintained by _publish_topic_stats, which already
            # has the publisher counts in hand.
            message.duration_sec = snapshot['duration']
            message.bag_size_bytes = int(snapshot['size'])
            message.write_rate_bytes_per_sec = snapshot['write_rate']
            message.topic_count = len(snapshot['topics'])
            message.message_count = int(snapshot['messages'])
            message.failed_topic_count = len(snapshot['failed'])
            message.lost_topic_count = len(session.lost_topics)
            message.bag_path = session.bag_path
            message.bag_name = session.bag_name
            message.bag_uris = session.bag_uris
            message.active_writers = [key for key in session.formats]
            disk_probe = session.bag_path
        else:
            summary = self._last_summary
            if summary is not None:
                message.bag_name = summary.bag_name
                message.bag_path = summary.bag_path
                message.bag_uris = list(summary.bag_uris)
                message.duration_sec = summary.duration_sec
                message.bag_size_bytes = summary.total_size_bytes
                message.topic_count = summary.topic_count
                message.message_count = summary.message_count
            disk_probe = os.path.expanduser(message.config.bag_path or '~')

        free, total, _mount = sysinfo.disk_usage(disk_probe)
        message.disk_free_bytes = free
        message.disk_total_bytes = total
        self._status_pub.publish(message)

    def _publish_topic_stats(self):
        live = self._graph.scan()
        for name in self._graph.appeared:
            self.get_logger().debug(f"Topic appeared: {name}")

        with self._lock:
            session = self._session
            matched, excluded = self._selection
            snapshot = session.snapshot() if session is not None else None

        recording = set(snapshot['topics']) if snapshot else set()
        failed = set(snapshot['failed']) if snapshot else set()
        counts = snapshot['counts'] if snapshot else {}
        session_hz = snapshot['hz'] if snapshot else {}
        probe_stats = self._rates.stats()
        probed = set(probe_stats)
        lost = set()

        message = TopicStats()
        message.stamp = self.get_clock().now().to_msg()
        for name in sorted(set(live) | recording):
            stat = TopicStat()
            stat.name = name
            stat.type = live.get(name, self._graph.type_of(name))
            publishers, subscribers = self._graph.counts(name)
            stat.publisher_count = publishers
            stat.subscriber_count = subscribers
            reliability, durability, history, depth = self._graph.qos(name, publishers)
            stat.reliability = reliability
            stat.durability = durability
            stat.history = history
            stat.depth = depth
            stat.newly_discovered = self._graph.is_new(name)
            stat.rate_monitored = name in probed

            # A recorded topic whose last publisher went away is 'lost', even
            # though the recorder's own subscription keeps it on the graph.
            orphaned = name in recording and (name not in live or publishers <= 0)
            if orphaned:
                lost.add(name)
                if name not in self._warned_lost:
                    self._warned_lost.add(name)
                    self.get_logger().warning(
                        f"Topic '{name}' stopped publishing while it was being recorded.")

            if orphaned:
                stat.state = TopicStat.STATE_LOST
            elif name not in live:
                stat.state = TopicStat.STATE_LOST
            elif name in failed:
                stat.state = TopicStat.STATE_FAILED
            elif name in recording:
                stat.state = TopicStat.STATE_RECORDING
            elif name in excluded:
                stat.state = TopicStat.STATE_EXCLUDED
            elif name in matched:
                stat.state = TopicStat.STATE_SELECTED
            else:
                stat.state = TopicStat.STATE_UNSELECTED

            if name in recording:
                stat.hz = float(session_hz.get(name, -1.0))
                stat.message_count = int(counts.get(name, 0))
                stat.bytes_per_sec = -1.0
            elif name in probed:
                hz, bytes_per_sec = probe_stats[name]
                stat.hz = hz
                stat.bytes_per_sec = bytes_per_sec
                stat.message_count = -1
            else:
                stat.hz = -1.0
                stat.bytes_per_sec = -1.0
                stat.message_count = -1
            message.topics.append(stat)

        with self._lock:
            if self._session is session and session is not None:
                session.lost_topics = lost
            self._warned_lost &= lost

        self._topics_pub.publish(message)

    # ------------------------------------------------------------------
    #  Failure handling
    # ------------------------------------------------------------------

    def _salvage(self, session, error):
        """
        Close the writers after the recorder broke mid-bag.

        Whatever was already recorded stays readable, and the failure is
        reported through the status topic.
        """
        self.get_logger().error(f'Recording failed: {error}')
        counts = {}
        try:
            counts = dict(session.snapshot(max_age=0.0)['counts'])
            session.stop(timeout=5.0)
        except Exception as err:                          # noqa: BLE001
            self.get_logger().error(f'Could not close the bag cleanly: {err}')
        with self._lock:
            self._last_summary = self._build_summary(session, counts)
            self._session = None
            self._last_error = error
            self._set_state(RecorderStatus.STATE_ERROR, 'the recorder stopped unexpectedly')

    def _build_summary(self, session, counts):
        from rosbag_recorder_msgs.msg import RecordingSummary

        summary = RecordingSummary()
        summary.bag_name = session.bag_name
        summary.bag_path = session.bag_path
        summary.duration_sec = session.duration()
        summary.recorded_topics = sorted(counts) or []
        summary.topic_count = len(summary.recorded_topics)
        summary.message_count = int(sum(counts.values()))
        summary.total_size_bytes = int(session.size_bytes())
        summary.bag_uris = session.bag_uris
        summary.formats = list(session.formats)
        summary.lost_topics = sorted(session.lost_topics)
        summary.started = _to_time_msg(session.started_at)
        summary.finished = _to_time_msg(session.finished_at or time.time())
        return summary

    def shutdown(self):
        """Close an in-flight bag rather than leaving it truncated on exit."""
        with self._lock:
            session = self._session
            self._session = None
        if session is not None:
            self.get_logger().warning('Bridge shutting down: closing the open bag.')
            try:
                session.stop(timeout=10.0)
            except Exception as err:                      # noqa: BLE001
                self.get_logger().error(f'Could not close the bag: {err}')
        self._rates.clear()


def _to_time_msg(seconds):
    from builtin_interfaces.msg import Time

    stamp = Time()
    if seconds is None:
        return stamp
    stamp.sec = int(seconds)
    stamp.nanosec = int((seconds - int(seconds)) * 1e9)
    return stamp


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        node = RecorderBridge()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.shutdown()
            node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
