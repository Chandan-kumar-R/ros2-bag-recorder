"""
Value formatting.

The rule everywhere in this app: a number we did not measure is shown as
'N/A', never as 0 and never as a guess. The bridge signals 'unknown' with a
negative value, so every helper here treats negatives as unknown.
"""
import datetime

NA = 'N/A'


def human_bytes(count, unknown=NA):
    if count is None or count < 0:
        return unknown
    value = float(count)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(value) < 1024.0 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024.0
    return f'{value:.1f} TB'


def human_rate(bytes_per_sec, unknown=NA):
    if bytes_per_sec is None or bytes_per_sec < 0:
        return unknown
    return f'{human_bytes(bytes_per_sec)}/s'


def human_hz(hz, unknown=NA):
    if hz is None or hz < 0:
        return unknown
    if hz == 0:
        return '0 Hz'
    if hz < 1.0:
        return f'{hz:.2f} Hz'
    if hz < 10.0:
        return f'{hz:.1f} Hz'
    return f'{hz:.0f} Hz'


def duration(seconds, unknown=NA):
    """HH:MM:SS, the format an operator can read off a screen at a glance."""
    if seconds is None or seconds < 0:
        return unknown
    total = int(seconds)
    return f'{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}'


def short_duration(seconds, unknown=NA):
    if seconds is None or seconds < 0:
        return unknown
    if seconds < 60:
        return f'{seconds:.0f}s'
    if seconds < 3600:
        return f'{seconds / 60:.0f}m {int(seconds) % 60}s'
    return f'{seconds / 3600:.1f}h'


def count(value, unknown=NA):
    if value is None or value < 0:
        return unknown
    return f'{int(value):,}'


def percent(value, unknown=NA):
    if value is None or value < 0:
        return unknown
    return f'{value:.0f}%'


def timestamp(epoch_seconds, fmt='%Y-%m-%d %H:%M'):
    try:
        return datetime.datetime.fromtimestamp(epoch_seconds).strftime(fmt)
    except (OSError, OverflowError, ValueError, TypeError):
        return NA


def ros_time_to_epoch(stamp):
    if stamp is None:
        return 0.0
    return stamp.sec + stamp.nanosec * 1e-9


def clock_time(epoch_seconds):
    return timestamp(epoch_seconds, '%H:%M:%S')


def elide(text, limit=60):
    text = text or ''
    return text if len(text) <= limit else text[:limit - 1] + '…'


def short_type(type_str):
    """'sensor_msgs/msg/Image' -> 'sensor_msgs/Image', which is what people say."""
    parts = (type_str or '').split('/')
    if len(parts) == 3:
        return f'{parts[0]}/{parts[2]}'
    return type_str or NA
