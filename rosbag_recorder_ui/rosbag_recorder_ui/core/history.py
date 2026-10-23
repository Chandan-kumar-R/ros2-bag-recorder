"""
Recording history.

Deliberately a flat JSON file, not a database. Sizes are
re-checked from disk on load, so a bag that was moved or deleted shows up as
missing instead of quietly reporting a stale number.
"""
import json
import os
import time

MAX_ENTRIES = 500


def history_path():
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    directory = os.path.join(base, 'rosbag_recorder_ui')
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, 'history.json')


class RecordingHistory:
    """Append-only log of recordings made through the dashboard."""

    def __init__(self, path=None):
        self.path = path or history_path()
        self._entries = []
        self.load()

    def load(self):
        try:
            with open(self.path, 'r') as handle:
                data = json.load(handle)
        except FileNotFoundError:
            self._entries = []
            return self._entries
        except (OSError, json.JSONDecodeError):
            # A corrupt history is not worth an error dialog; start a new one.
            self._entries = []
            return self._entries
        self._entries = data if isinstance(data, list) else []
        return self._entries

    def save(self):
        try:
            with open(self.path, 'w') as handle:
                json.dump(self._entries[-MAX_ENTRIES:], handle, indent=1)
        except OSError:
            return False
        return True

    def add(self, entry):
        self._entries.append(entry)
        self.save()

    def add_from_summary(self, summary, status='completed', note=''):
        """Record a finished session from a RecordingSummary message."""
        entry = {
            'started': summary.started.sec or time.time(),
            'finished': summary.finished.sec or time.time(),
            'name': summary.bag_name,
            'path': summary.bag_path,
            'uris': list(summary.bag_uris),
            'formats': list(summary.formats),
            'size': int(summary.total_size_bytes),
            'topics': int(summary.topic_count),
            'messages': int(summary.message_count),
            'duration': float(summary.duration_sec),
            'recorded_topics': [name for name in summary.recorded_topics if name],
            'failed_topics': [name for name in summary.failed_topics if name],
            'lost_topics': [name for name in summary.lost_topics if name],
            'status': status,
            'note': note,
        }
        self.add(entry)
        return entry

    def entries(self, refresh_sizes=True):
        """Newest first, with on-disk presence re-checked."""
        rows = []
        for entry in reversed(self._entries):
            row = dict(entry)
            uris = row.get('uris') or []
            row['present'] = bool(uris) and all(os.path.exists(u) for u in uris)
            if refresh_sizes and row['present']:
                row['size'] = sum(_dir_size(u) for u in uris)
            rows.append(row)
        return rows

    def remove(self, started, name):
        before = len(self._entries)
        self._entries = [e for e in self._entries
                         if not (e.get('started') == started and e.get('name') == name)]
        if len(self._entries) != before:
            self.save()
        return before - len(self._entries)

    def clear(self):
        self._entries = []
        self.save()


def _dir_size(path):
    total = 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total
