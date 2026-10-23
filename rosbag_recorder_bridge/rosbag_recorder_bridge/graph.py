"""
A cached view of the ROS graph.

The bridge is asked for topic types, publisher counts and QoS once a second for
every topic on the graph,
"""
import time

from rosbag_recorder_bridge.recorder_api import describe_qos


class GraphCache:
    """Tracks what is on the graph, what just appeared and what just left."""

    NEW_TOPIC_GRACE_SEC = 12.0

    def __init__(self, node):
        self._node = node
        self._types = {}         # topic -> type string
        self._first_seen = {}    # topic -> monotonic time
        self._qos = {}           # topic -> (reliability, durability, history, depth)
        self._qos_key = {}       # topic -> publisher count the QoS was read at
        self.appeared = set()
        self.vanished = set()

    def scan(self):
        """Re-read the graph. Returns {topic: type} for everything currently live."""
        live = {name: types[0] for name, types in self._node.get_topic_names_and_types()
                if types}
        now = time.monotonic()

        self.appeared = set(live) - set(self._types)
        self.vanished = set(self._types) - set(live)
        for name in self.appeared:
            self._first_seen[name] = now
        for name in self.vanished:
            self._qos.pop(name, None)
            self._qos_key.pop(name, None)

        self._types = live
        return dict(live)

    @property
    def types(self):
        return dict(self._types)

    def type_of(self, name):
        return self._types.get(name, '')

    def counts(self, name):
        """Return (publishers, subscribers), or (-1, -1) if the graph query fails."""
        try:
            return self._node.count_publishers(name), self._node.count_subscribers(name)
        except Exception:                                 # noqa: BLE001
            return -1, -1

    def qos(self, name, publisher_count):
        """
        Return QoS for *name*, re-read only when its publisher count changed.

        Returns ('', '', '', -1) when the topic has no publishers, which the
        dashboard renders as N/A rather than guessing a default profile.
        """
        if publisher_count <= 0:
            return '', '', '', -1
        if self._qos_key.get(name) == publisher_count and name in self._qos:
            return self._qos[name]
        try:
            infos = self._node.get_publishers_info_by_topic(name)
        except Exception:                                 # noqa: BLE001
            return '', '', '', -1
        described = describe_qos(infos)
        self._qos[name] = described
        self._qos_key[name] = publisher_count
        return described

    def is_new(self, name):
        seen = self._first_seen.get(name)
        return seen is not None and (time.monotonic() - seen) < self.NEW_TOPIC_GRACE_SEC
