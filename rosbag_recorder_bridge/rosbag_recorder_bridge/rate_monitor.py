"""
Opt-in topic rate probes.
"""
import time
from collections import deque

from rosbag_recorder_bridge.recorder_api import import_message_type, probe_qos

WINDOW_SEC = 5.0
MAX_SAMPLES = 512


class RateMonitor:
    """Manages the set of live rate probes on behalf of the bridge node."""

    def __init__(self, node, callback_group=None):
        self._node = node
        self._group = callback_group
        self._subs = {}       # topic -> Subscription
        self._samples = {}    # topic -> deque[(monotonic, nbytes)]

    @property
    def topics(self):
        return sorted(self._subs)

    def sync(self, wanted):
        """
        Make the live probe set equal *wanted* (an iterable of topic names).

        Returns (attached, failed) topic name lists.
        """
        wanted = set(wanted)
        for name in list(self._subs):
            if name not in wanted:
                self._detach(name)

        attached, failed = [], []
        for name in sorted(wanted):
            if name in self._subs:
                attached.append(name)
            elif self._attach(name):
                attached.append(name)
            else:
                failed.append(name)
        return attached, failed

    def clear(self):
        for name in list(self._subs):
            self._detach(name)

    # ------------------------------------------------------------------

    def _attach(self, name):
        types = dict(self._node.get_topic_names_and_types()).get(name)
        if not types:
            return False
        msg_class = import_message_type(self._node, types[0])
        if msg_class is None:
            return False
        infos = self._node.get_publishers_info_by_topic(name)
        if not infos:
            return False
        samples = deque(maxlen=MAX_SAMPLES)
        self._samples[name] = samples

        def callback(data):
            samples.append((time.monotonic(), len(data)))

        try:
            self._subs[name] = self._node.create_subscription(
                msg_class, name, callback, probe_qos(infos),
                callback_group=self._group, raw=True)
        except Exception as err:                          # noqa: BLE001
            self._node.get_logger().warning(f"Cannot probe '{name}': {err}")
            self._samples.pop(name, None)
            return False
        return True

    def _detach(self, name):
        subscription = self._subs.pop(name, None)
        if subscription is not None:
            self._node.destroy_subscription(subscription)
        self._samples.pop(name, None)

    def stats(self):
        """Return {topic: (hz, bytes_per_sec)} over the trailing window."""
        now = time.monotonic()
        result = {}
        for name, samples in self._samples.items():
            while samples and now - samples[0][0] > WINDOW_SEC:
                samples.popleft()
            if len(samples) < 2:
                # One sample says 'alive' but cannot say how fast.
                result[name] = (0.0 if not samples else -1.0, -1.0)
                continue
            span = samples[-1][0] - samples[0][0]
            if span <= 0.0:
                result[name] = (-1.0, -1.0)
                continue
            count = len(samples) - 1
            volume = sum(size for _stamp, size in list(samples)[1:])
            result[name] = (count / span, volume / span)
        return result
