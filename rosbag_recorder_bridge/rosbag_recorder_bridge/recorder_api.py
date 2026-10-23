"""
Thin adapters over ros2_bag_recorder internals.

The bridge reuses the recorder's own message-type import and QoS matching on
purpose:
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros2_bag_recorder.multiple_topic import MultipleTopicRecorder
from ros2_bag_recorder.topic_selection import (
    RegistryError,
    compile_keywords,
    compile_patterns,
    load_enabled_entries,
    match_topics,
)

__all__ = [
    'RegistryError',
    'compile_keywords',
    'compile_patterns',
    'default_registry_path',
    'describe_qos',
    'import_message_type',
    'load_enabled_entries',
    'load_registry',
    'match_topics',
    'publisher_matched_qos',
    'selectors_for',
]


def default_registry_path():
    """Return the topic_registry.yaml installed by ros2_bag_recorder."""
    return os.path.join(
        get_package_share_directory('ros2_bag_recorder'), 'config', 'topic_registry.yaml')


def load_registry(path=''):
    """
    Read a topic registry file into a dict of module -> entries.

    Only the file handling lives here; the entries themselves are validated by
    the recorder's own load_enabled_entries().
    """
    path = path or default_registry_path()
    try:
        with open(path, 'r') as handle:
            registry = yaml.safe_load(handle)
    except OSError as err:
        raise RegistryError(f"Cannot read registry '{path}': {err}") from err
    except yaml.YAMLError as err:
        raise RegistryError(f"Cannot parse registry '{path}': {err}") from err
    if not isinstance(registry, dict):
        raise RegistryError(f"Registry '{path}' must be a mapping of modules.")
    return registry, path


def import_message_type(node, type_str):
    """
    Resolve 'sensor_msgs/msg/Image' to its Python class, or None on failure.

    Failures are logged through *node*, which is why any Node will do.
    """
    return MultipleTopicRecorder._import_msg_type(node, type_str)


def publisher_matched_qos(infos):
    """Return QoS capturing best_effort sensors and transient_local latched topics."""
    # _pick_qos reads nothing off self; passing None keeps this a pure call.
    return MultipleTopicRecorder._pick_qos(None, infos)


def selectors_for(config, registry):
    """
    Turn a RecordingConfig into (exact_names, include_patterns).

    Delegates to the recorder's selection module so registry parsing, regex
    compilation and keyword escaping cannot drift between preview and reality.
    """
    if config.selection_method == 'manual':
        topics = [t for t in config.manual_topics if t]
        if not topics:
            raise RegistryError('No topics have been ticked for manual recording.')
        return set(topics), []
    if config.selection_method == 'keywords':
        keywords = [k for k in config.keywords if k]
        if not keywords:
            raise RegistryError("Keyword mode needs at least one keyword.")
        return set(), compile_keywords(keywords)
    enabled = {m for m in config.modules if m in registry}
    if not enabled:
        raise RegistryError('No registry modules are enabled.')
    return load_enabled_entries(registry, enabled)


_RELIABILITY = {
    ReliabilityPolicy.RELIABLE: 'RELIABLE',
    ReliabilityPolicy.BEST_EFFORT: 'BEST_EFFORT',
    ReliabilityPolicy.SYSTEM_DEFAULT: 'SYSTEM_DEFAULT',
}
_DURABILITY = {
    DurabilityPolicy.VOLATILE: 'VOLATILE',
    DurabilityPolicy.TRANSIENT_LOCAL: 'TRANSIENT_LOCAL',
    DurabilityPolicy.SYSTEM_DEFAULT: 'SYSTEM_DEFAULT',
}
_HISTORY = {
    HistoryPolicy.KEEP_LAST: 'KEEP_LAST',
    HistoryPolicy.KEEP_ALL: 'KEEP_ALL',
    HistoryPolicy.SYSTEM_DEFAULT: 'SYSTEM_DEFAULT',
}


def describe_qos(infos):
    """
    Describe a topic's QoS in the same terms the recorder subscribes with.
    """
    if not infos:
        return '', '', '', -1
    profile = publisher_matched_qos(infos)
    history = _HISTORY.get(infos[0].qos_profile.history, '')
    depth = infos[0].qos_profile.depth
    if history in ('', 'SYSTEM_DEFAULT') or not depth:
        depth = -1
    return (
        _RELIABILITY.get(profile.reliability, ''),
        _DURABILITY.get(profile.durability, ''),
        history,
        int(depth),
    )


def probe_qos(infos):
    """Build a QoSProfile suitable for a short-lived rate probe on the topic."""
    matched = publisher_matched_qos(infos)
    return QoSProfile(
        depth=5,
        reliability=matched.reliability,
        # A probe must never latch a large history of an already-published topic.
        durability=DurabilityPolicy.VOLATILE,
    )
