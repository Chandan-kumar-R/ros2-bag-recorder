import datetime
import importlib
import os
import yaml

import rclpy
import rosbag2_py
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import serialize_message

from ros2_bag_recorder.topic_selection import (
    RegistryError,
    compile_keywords,
    compile_patterns,
    load_enabled_entries,
    match_topics,
)

class WriterPool:
    """One rosbag2 writer per enabled storage format"""

    FORMATS = {'sqlite': ('sqlite3', '_sqlite'), 'mcap': ('mcap', '_mcap')}

    def __init__(self, bag_path, bag_name, enabled_formats, logger):
        converter = rosbag2_py._storage.ConverterOptions('', '')
        self._writers = []
        for key in enabled_formats:
            storage_id, suffix = self.FORMATS[key]
            options = rosbag2_py._storage.StorageOptions(
                uri=os.path.join(bag_path, f'{bag_name}{suffix}'),
                storage_id=storage_id,
            )
            writer = rosbag2_py.SequentialWriter()
            writer.open(options, converter)
            self._writers.append(writer)
            logger.info(f"Storage '{storage_id}' enabled.")
        if not self._writers:
            raise RuntimeError('Enable at least one storage format (sqlite/mcap).')

    def add_topic(self, name, type_str):
        metadata = rosbag2_py._storage.TopicMetadata(
            name=name, type=type_str, serialization_format='cdr')
        for writer in self._writers:
            writer.create_topic(metadata)

    def write(self, name, data, stamp_ns):
        for writer in self._writers:
            writer.write(name, data, stamp_ns)

    def close(self):
        """Close writers so rosbag2 flushes and finalizes the bags."""
        for writer in self._writers:
            writer.close()
        self._writers.clear()


class MultipleTopicRecorder(Node):
    """
    Records topics selected by module-grouped exact names / regex patterns.

    Topics (and their types) are discovered from the ROS graph on a timer,
    so topics that appear after startup are picked up automatically.
    """

    WARN_EVERY_N_SCANS = 5

    def __init__(self, **node_kwargs):
        super().__init__('ros2_bag_recorder_node', **node_kwargs)

        self.declare_parameter('selection_method', 'registry')
        self.declare_parameter('registry_file', '')
        self.declare_parameter('keywords', [''])
        self.declare_parameter('bag_folder.path', '~/rosbags')
        self.declare_parameter('bag_folder.name', 'multiple')
        self.declare_parameter('bag_folder.append_timestamp', True)
        self.declare_parameter('storage_id.sqlite', True)
        self.declare_parameter('storage_id.mcap', False)
        self.declare_parameter('discovery_interval_sec', 1.0)
        self.declare_parameter('exclude_patterns', [''])

        '''selection_method: 'registry' or 'keywords'''
        method = self.get_parameter('selection_method').value
        if method == 'registry':
            self._exact, self._includes = self._setup_registry_mode()
        elif method == 'keywords':
            self._exact, self._includes = self._setup_keywords_mode()
        else:
            raise RuntimeError(
                "selection_method must be 'registry' or 'keywords', "
                f"got '{method}'.")
            
        '''exclude patterns: regexes; any match is never recorded, even if a module includes it'''
        raw_excludes = [p for p in self.get_parameter('exclude_patterns').value if p]
        self._excludes = compile_patterns(raw_excludes)

        '''bag storage settings: path, name, append_timestamp'''
        bag_path = os.path.expanduser(self.get_parameter('bag_folder.path').value)
        bag_name = self.get_parameter('bag_folder.name').value
        if self.get_parameter('bag_folder.append_timestamp').value:
            bag_name += datetime.datetime.now().strftime('_%Y-%m-%d_%H-%M-%S')
        os.makedirs(bag_path, exist_ok=True)
        self._check_collision(bag_path, bag_name)

        '''storage formats: sqlite, mcap'''
        formats = [k for k in WriterPool.FORMATS
                   if self.get_parameter(f'storage_id.{k}').value]
        self.writers = WriterPool(bag_path, bag_name, formats, self.get_logger())

        self._subscribed = {}   # topic name -> Subscription
        self._failed = set()    # topics whose message type could not be imported
        self._scan_count = 0
        interval = self.get_parameter('discovery_interval_sec').value
        self._discover()
        self.create_timer(interval, self._discover)
        self.get_logger().info('Recorder ready.')

    # ------------------------------------------------------------------
    #  Setup helpers
    # ------------------------------------------------------------------

    def _setup_registry_mode(self):
        """Select topics from enabled modules of the topic registry."""
        registry = self._load_registry()
        for module in registry:
            self.declare_parameter(f'modules.{module}', False)
        enabled = {m for m in registry
                   if self.get_parameter(f'modules.{m}').value}
        for module in sorted(registry):
            state = 'enabled' if module in enabled else 'disabled'
            self.get_logger().info(f"Module '{module}' {state}.")
        if not enabled:
            raise RuntimeError(
                'No topics to record. Enable at least one module.')
        return load_enabled_entries(registry, enabled)

    def _setup_keywords_mode(self):
        """Select every live topic whose name contains a configured keyword."""
        keywords = [k for k in self.get_parameter('keywords').value if k]
        if not keywords:
            raise RuntimeError(
                "selection_method 'keywords' requires a non-empty "
                "'keywords' list.")
        self.get_logger().info(f'Keyword mode: {keywords}')
        return set(), compile_keywords(keywords)

    def _load_registry(self):
        path = self.get_parameter('registry_file').value
        if not path:
            share = get_package_share_directory('ros2_bag_recorder')
            path = os.path.join(share, 'config', 'topic_registry.yaml')
        try:
            with open(path, 'r') as handle:
                registry = yaml.safe_load(handle)
        except OSError as err:
            raise RegistryError(f"Cannot read registry '{path}': {err}") from err
        except yaml.YAMLError as err:
            raise RegistryError(f"Cannot parse registry '{path}': {err}") from err
        if not isinstance(registry, dict):
            raise RegistryError(f"Registry '{path}' must be a mapping of modules.")
        return registry

    def _check_collision(self, bag_path, bag_name):
        for _, suffix in WriterPool.FORMATS.values():
            target = os.path.join(bag_path, f'{bag_name}{suffix}')
            if os.path.exists(target):
                raise RuntimeError(
                    f"Bag '{target}' already exists. Use a unique name or "
                    'enable bag_folder.append_timestamp.')

    # ------------------------------------------------------------------
    #  Discovery
    # ------------------------------------------------------------------

    def _discover(self):
        self._scan_count += 1
        live = dict(self.get_topic_names_and_types())
        matched = match_topics(
            live.keys(), self._exact, self._includes, self._excludes)
        for name in sorted(matched - set(self._subscribed) - self._failed):
            self._subscribe(name, live[name][0])
        if self._scan_count % self.WARN_EVERY_N_SCANS == 0:
            self._warn_unmatched()

    def _subscribe(self, name, type_str):
        infos = self.get_publishers_info_by_topic(name)
        if not infos:
            self.get_logger().debug(
                f"No publisher info for '{name}' yet; deferring.")
            return
        msg_class = self._import_msg_type(type_str)
        if msg_class is None:
            self._failed.add(name)
            return
        self.writers.add_topic(name, type_str)
        subscription = self.create_subscription(
            msg_class, name, self._make_callback(name), self._pick_qos(infos))
        self._subscribed[name] = subscription
        self.get_logger().info(f"Recording '{name}' [{type_str}].")

    def _pick_qos(self, infos):
        """Match publisher QoS so best_effort and latched topics are captured."""
        reliability = ReliabilityPolicy.RELIABLE
        durability = DurabilityPolicy.VOLATILE
        for info in infos:
            if info.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT:
                reliability = ReliabilityPolicy.BEST_EFFORT
            if info.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL:
                durability = DurabilityPolicy.TRANSIENT_LOCAL
        return QoSProfile(depth=10, reliability=reliability, durability=durability)

    def _warn_unmatched(self):
        handled = set(self._subscribed) | self._failed
        for name in sorted(self._exact - handled):
            self.get_logger().warning(f"Topic '{name}' not seen yet.")
        for pattern in self._includes:
            if not any(pattern.fullmatch(t) for t in handled):
                self.get_logger().warning(
                    f"Pattern '{pattern.pattern}' has matched no topics yet.")

    # ------------------------------------------------------------------
    #  Recording
    # ------------------------------------------------------------------

    def _make_callback(self, name):
        def callback(msg):
            stamp = self.get_clock().now().nanoseconds
            self.writers.write(name, serialize_message(msg), stamp)
        return callback

    def _import_msg_type(self, type_str):
        try:
            module_path, class_name = type_str.rsplit('/', 1)
            module = importlib.import_module(module_path.replace('/', '.'))
            return getattr(module, class_name)
        except (ModuleNotFoundError, AttributeError, ValueError) as err:
            self.get_logger().error(f"Cannot import '{type_str}': {err}")
            return None

def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = MultipleTopicRecorder()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except (RuntimeError, RegistryError) as err:
        print(f'Recorder failed: {err}')
    finally:
        if node is not None:
            node.writers.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()