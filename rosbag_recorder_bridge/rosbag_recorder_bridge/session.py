"""
Recording session lifecycle.
"""
import datetime
import os
import threading
import time
from collections import defaultdict

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter

from ros2_bag_recorder.multiple_topic import MultipleTopicRecorder, WriterPool
from ros2_bag_recorder.topic_selection import RegistryError

from rosbag_recorder_bridge import sysinfo

# Mirrors the suffix ros2_bag_recorder appends when append_timestamp is set.
# The bridge resolves the timestamp itself so it can report the final bag paths
# back to the operator instead of guessing what the recorder chose.
BAG_TIMESTAMP_FORMAT = '_%Y-%m-%d_%H-%M-%S'

# The recorder node lives in its own namespace so it never collides with a
# standalone `ros2 launch ros2_bag_recorder recorder.launch.py` on the same
# graph. Registry and keyword topics are all absolute, so this cannot remap them.
RECORDER_NAMESPACE = 'rosbag_recorder'

# Manual selection is a dashboard concept; the recorder only knows 'registry'
# and 'keywords'. Rather than teach it a third mode, the bridge writes the
# ticked topics out as a one-module registry and runs ordinary registry mode
# against it. The file is a perfectly normal topic_registry.yaml, so the same
# selection can be replayed from a terminal.
MANUAL_MODULE = 'manual_selection'

WRITE_RATE_WINDOW_SEC = 3.0


class SessionError(RuntimeError):
    """A recording could not be started or stopped. Message is operator-facing."""

    def __init__(self, message, detail=''):
        super().__init__(message)
        self.message = message
        self.detail = detail


class ManagedRecorder(MultipleTopicRecorder):
    """
    The stock recorder plus per-topic bookkeeping.
    """

    def __init__(self, **node_kwargs):
        # Set before super().__init__ - the base constructor already subscribes.
        self.message_counts = defaultdict(int)
        self.write_error = None
        super().__init__(**node_kwargs)

    def _make_callback(self, name):
        write = super()._make_callback(name)
        counts = self.message_counts

        def callback(msg):
            try:
                write(msg)
            except Exception as err:                      # noqa: BLE001 - see below
                # A writer failure must surface as a recording error, not as an
                # exception that tears down the executor mid-bag.
                if self.write_error is None:
                    self.write_error = f"Writer failed on '{name}': {err}"
                    self.get_logger().error(self.write_error)
                return
            counts[name] += 1

        return callback

    # -- read-only views over the base class's bookkeeping ------------------
    # Kept in one place so a rename in ros2_bag_recorder is a one-line fix.

    @property
    def recorded_topics(self):
        return sorted(self._subscribed)

    @property
    def failed_topics(self):
        return sorted(self._failed)

    @property
    def total_messages(self):
        return sum(self.message_counts.values())


class RecordingSession:
    """One start-to-stop recording, including the thread the recorder runs on."""

    def __init__(self, config, logger):
        self.config = config
        self._logger = logger
        self.bag_name = self._resolve_bag_name(config)
        self.bag_path = os.path.abspath(os.path.expanduser(config.bag_path or '~/rosbags'))
        self.formats = [key for key, enabled in (('sqlite', config.storage_sqlite),
                                                 ('mcap', config.storage_mcap)) if enabled]
        self.bag_uris = [os.path.join(self.bag_path, f'{self.bag_name}{WriterPool.FORMATS[k][1]}')
                         for k in self.formats]

        self._node = None
        self._executor = None
        self._thread = None
        self._stop_event = threading.Event()
        self._thread_error = None

        self.started_at = None
        self.finished_at = None
        self._size_samples = []      # (monotonic, bytes) for the write-rate window
        self._last_counts = {}
        self._last_count_time = None
        self._topic_hz = {}
        self._snapshot = None
        self._snapshot_time = 0.0
        self.lost_topics = set()

    # ------------------------------------------------------------------
    #  Naming and pre-flight
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_bag_name(config):
        name = (config.bag_name or 'recording').strip()
        if config.append_timestamp:
            name += datetime.datetime.now().strftime(BAG_TIMESTAMP_FORMAT)
        return name

    @property
    def storage_ids(self):
        """rosbag2's own ids for the enabled formats, e.g. ['sqlite3', 'mcap']."""
        return [WriterPool.FORMATS[key][0] for key in self.formats]

    def missing_writers(self):
        """
        Return the enabled formats whose rosbag2 plugin is missing here.

        Empty when nothing is missing *and* when rosbag2 could not be asked at
        all: an unknown answer must not be reported as a missing plugin.
        """
        available = registered_writers()
        if not available:
            return []
        return [name for name in self.storage_ids if name not in available]

    def preflight(self):
        """
        Raise SessionError for anything we can detect before opening a writer.

        Returns a list of non-fatal warnings.
        """
        warnings = []
        if not self.formats:
            raise SessionError('Pick at least one storage format (SQLite3 or MCAP).')

        for storage_id in self.missing_writers():
            raise SessionError(
                f"The '{storage_id}' storage plugin is not installed on the "
                'recording machine.',
                f'rosbag2 knows about: {", ".join(sorted(registered_writers()))}')

        if not self.bag_name or '/' in self.bag_name:
            raise SessionError('Bag name must not be empty or contain a slash.')

        if not sysinfo.is_writable(self.bag_path):
            raise SessionError(f'Cannot write to {self.bag_path}. Check the path and permissions.')

        for uri in self.bag_uris:
            if os.path.exists(uri):
                raise SessionError(
                    f'A bag already exists at {uri}.',
                    'Choose another name or switch on "append timestamp".')

        free, total, _mount = sysinfo.disk_usage(self.bag_path)
        if total and free < 1 << 30:
            warnings.append(
                f'Only {sysinfo.human_bytes(free)} free on the recording disk.')
        if self.config.selection_method not in ('registry', 'keywords', 'manual'):
            raise SessionError(
                f"Unknown selection method '{self.config.selection_method}'.",
                "Expected 'registry', 'keywords' or 'manual'.")
        if self.config.selection_method == 'manual' and not [
                t for t in self.config.manual_topics if t]:
            raise SessionError('No topics have been ticked for manual recording.')
        return warnings

    # ------------------------------------------------------------------
    #  Start / stop
    # ------------------------------------------------------------------

    def manual_registry_path(self):
        """Where the generated registry for manual selection lives on this host."""
        base = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
        return os.path.join(base, 'rosbag_recorder_bridge', 'manual_selection.yaml')

    def _write_manual_registry(self):
        """
        Render the ticked topics as a topic registry the recorder can read.
        """
        topics = [t for t in self.config.manual_topics if t]
        path = self.manual_registry_path()
        entries = '\n'.join(f'  - topic: {name}' for name in sorted(topics))
        text = (
            '# Generated by the ROS 2 Bag Recorder dashboard from a manual topic\n'
            '# selection. It is overwritten every time a manual recording starts.\n'
            '#\n'
            '# This is an ordinary topic registry, so the same selection runs from a\n'
            '# terminal with:\n'
            '#   selection_method: \'registry\'\n'
            f'#   registry_file: \'{path}\'\n'
            f'#   modules: {{ {MANUAL_MODULE}: true }}\n'
            f'\n{MANUAL_MODULE}:\n{entries}\n')
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as handle:
                handle.write(text)
        except OSError as err:
            raise SessionError(
                'The ticked topic list could not be written to disk, so the '
                'recording cannot start.', f'{path}: {err}') from err
        return path

    def _parameter_overrides(self):
        config = self.config
        method = config.selection_method
        registry_file = config.registry_file or ''
        if method == 'manual':
            # The recorder never sees 'manual'; it sees a registry with one
            # enabled module, which is exactly what the ticked list means.
            method = 'registry'
            registry_file = self._write_manual_registry()

        overrides = [
            Parameter('selection_method', Parameter.Type.STRING, method),
            Parameter('registry_file', Parameter.Type.STRING, registry_file),
            Parameter('keywords', Parameter.Type.STRING_ARRAY, list(config.keywords) or ['']),
            Parameter('exclude_patterns', Parameter.Type.STRING_ARRAY,
                      list(config.exclude_patterns) or ['']),
            Parameter('bag_folder.path', Parameter.Type.STRING, self.bag_path),
            # The timestamp is already baked into bag_name by _resolve_bag_name.
            Parameter('bag_folder.name', Parameter.Type.STRING, self.bag_name),
            Parameter('bag_folder.append_timestamp', Parameter.Type.BOOL, False),
            Parameter('storage_id.sqlite', Parameter.Type.BOOL, bool(config.storage_sqlite)),
            Parameter('storage_id.mcap', Parameter.Type.BOOL, bool(config.storage_mcap)),
            Parameter('discovery_interval_sec', Parameter.Type.DOUBLE,
                      float(config.discovery_interval_sec or 1.0)),
        ]
        modules = [MANUAL_MODULE] if config.selection_method == 'manual' \
            else list(config.modules)
        overrides += [Parameter(f'modules.{module}', Parameter.Type.BOOL, True)
                      for module in modules]
        return overrides

    def start(self):
        """Construct the recorder and spin it. Raises SessionError on failure."""
        warnings = self.preflight()
        os.makedirs(self.bag_path, exist_ok=True)

        try:
            self._node = ManagedRecorder(
                namespace=RECORDER_NAMESPACE,
                parameter_overrides=self._parameter_overrides(),
            )
        except RegistryError as err:
            raise SessionError('The topic registry could not be read.', str(err)) from err
        except RuntimeError as err:
            # The recorder raises plain RuntimeError for 'no modules enabled',
            # 'bag exists' and 'no storage enabled'; all are operator problems.
            raise SessionError(str(err)) from err
        except Exception as err:                          # noqa: BLE001
            raise SessionError('The recorder failed to start.', f'{type(err).__name__}: {err}') \
                from err

        self.started_at = time.time()
        self._stop_event.clear()
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, name='bag-recorder', daemon=True)
        self._thread.start()
        return warnings

    def _spin(self):
        try:
            while not self._stop_event.is_set() and rclpy.ok():
                self._executor.spin_once(timeout_sec=0.1)
        except Exception as err:                          # noqa: BLE001
            self._thread_error = f'{type(err).__name__}: {err}'
            self._logger.error(f'Recorder thread died: {self._thread_error}')

    def stop(self, timeout=15.0):
        """
        Stop the recorder and close the writers, in that order.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise SessionError(
                    'The recorder did not stop within '
                    f'{timeout:.0f} s; the bag has been left open.',
                    'Its writer thread is still running. Inspect the bag before reusing it.')

        if self._executor is not None:
            self._executor.remove_node(self._node)
            self._executor.shutdown()
            self._executor = None

        detail = ''
        try:
            self._node.writers.close()
        except Exception as err:                          # noqa: BLE001
            detail = f'{type(err).__name__}: {err}'
            self._logger.error(f'Closing the bag writers failed: {detail}')

        self.finished_at = time.time()
        size = self.size_bytes()
        try:
            self._node.destroy_node()
        except Exception:                                 # noqa: BLE001
            pass

        if detail:
            raise SessionError('Recording stopped, but closing the bag reported an error.',
                               detail)
        return size

    # ------------------------------------------------------------------
    #  Live statistics
    # ------------------------------------------------------------------

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self):
        """First fatal problem seen by the recorder, or None."""
        if self._thread_error:
            return self._thread_error
        if self._node is not None and self._node.write_error:
            return self._node.write_error
        return None

    def duration(self):
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at)

    def size_bytes(self):
        return sum(sysinfo.dir_size(uri) for uri in self.bag_uris)

    def write_rate(self, size=None):
        """Bytes per second averaged over the last few seconds, or -1.0 if unknown."""
        now = time.monotonic()
        size = self.size_bytes() if size is None else size
        self._size_samples.append((now, size))
        while (len(self._size_samples) > 2
               and now - self._size_samples[0][0] > WRITE_RATE_WINDOW_SEC):
            self._size_samples.pop(0)
        if len(self._size_samples) < 2:
            return -1.0
        span = now - self._size_samples[0][0]
        if span <= 0.0:
            return -1.0
        return max(0.0, (size - self._size_samples[0][1]) / span)

    def sample_topic_rates(self):
        """
        Refresh per-topic Hz from the recorder's own message counters.
        """
        if self._node is None:
            return self._topic_hz
        now = time.monotonic()
        counts = dict(self._node.message_counts)
        if self._last_count_time is not None:
            span = now - self._last_count_time
            if span > 0.2:
                for name, count in counts.items():
                    previous = self._last_counts.get(name, 0)
                    self._topic_hz[name] = max(0.0, (count - previous) / span)
                self._last_counts = counts
                self._last_count_time = now
        else:
            self._last_counts = counts
            self._last_count_time = now
        return self._topic_hz

    def snapshot(self, max_age=0.4):
        """
        Everything the status publisher needs, gathered in one pass.
        """
        now = time.monotonic()
        if self._snapshot is not None and now - self._snapshot_time < max_age:
            return self._snapshot
        size = self.size_bytes()
        node = self._node
        self._snapshot_time = now
        self._snapshot = {
            'duration': self.duration(),
            'size': size,
            'write_rate': self.write_rate(size),
            'topics': node.recorded_topics if node else [],
            'failed': node.failed_topics if node else [],
            'messages': node.total_messages if node else 0,
            'counts': dict(node.message_counts) if node else {},
            'hz': dict(self.sample_topic_rates()),
            'error': self.error,
        }
        return self._snapshot


def registered_writers():
    """Storage plugin ids rosbag2 can actually use, or an empty set if unknown."""
    try:
        import rosbag2_py
        return set(rosbag2_py.get_registered_writers())
    except Exception:                                     # noqa: BLE001
        return set()
