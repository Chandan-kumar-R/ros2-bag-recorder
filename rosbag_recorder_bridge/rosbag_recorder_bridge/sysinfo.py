"""
Host statistics, with honest fallbacks.
"""
import os
import shutil
import socket

try:
    import psutil
except ImportError:      # pragma: no cover - psutil is a soft dependency
    psutil = None


def disk_usage(path):
    """
    Return (free_bytes, total_bytes, mount_point) for *path*.

    Probes the nearest existing ancestor, and returns (0, 0, '') when nothing
    along the path is readable.
    """
    probe = os.path.abspath(os.path.expanduser(path or os.getcwd()))
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return 0, 0, ''
        probe = parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return 0, 0, ''
    return usage.free, usage.total, probe


def dir_size(path):
    """Total size of every regular file under *path*. Unreadable files count as 0."""
    total = 0
    if not os.path.isdir(path):
        return os.path.getsize(path) if os.path.isfile(path) else 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def cpu_percent():
    """Instantaneous CPU load, or -1.0 when psutil is not installed."""
    if psutil is None:
        return -1.0
    return float(psutil.cpu_percent(interval=None))


def memory():
    """Return (percent, used_bytes, total_bytes); percent is -1.0 when unknown."""
    if psutil is None:
        return -1.0, 0, 0
    virtual = psutil.virtual_memory()
    return float(virtual.percent), int(virtual.used), int(virtual.total)


def hostname():
    try:
        return socket.gethostname()
    except OSError:
        return 'unknown'


def is_writable(path):
    """Report whether a bag could be created under *path*."""
    target = os.path.abspath(os.path.expanduser(path or ''))
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return False
        probe = parent
    return os.path.isdir(probe) and os.access(probe, os.W_OK | os.X_OK)


def human_bytes(count):
    """Format a byte count the way an operator expects to read it."""
    value = float(count)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(value) < 1024.0 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024.0
    return f'{value:.1f} TB'
