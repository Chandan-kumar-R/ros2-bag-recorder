"""
Vector icons, drawn from inline SVG so the package ships no binary assets.

Icons are recoloured on demand and cached per (name, colour, size), which
matters because the topic table asks for the same handful of icons on every
refresh.
"""
import os
import tempfile

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from rosbag_recorder_ui.core.theme import PALETTE

_STROKE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
           'stroke-linejoin="round">{body}</svg>')

_FILL = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
         'fill="{color}">{body}</svg>')

# Bodies are 24x24 line-art, deliberately simple so they stay legible at 16px.
_PATHS = {
    'dashboard': '<rect x="3" y="3" width="7" height="8" rx="1.5"/>'
                 '<rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                 '<rect x="14" y="11" width="7" height="10" rx="1.5"/>'
                 '<rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    'record': '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2" '
              'fill="{color}" stroke="none"/>',
    'topics': '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1.4"/>'
              '<circle cx="3.5" cy="12" r="1.4"/><circle cx="3.5" cy="18" r="1.4"/>',
    'config': '<path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4"/>'
              '<circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/>'
              '<circle cx="14" cy="18" r="2"/>',
    'diagnostics': '<path d="M3 12h4l2.5-7 4 14 2.5-7h5"/>',
    'history': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    'folder': '<path d="M3 7a2 2 0 012-2h4l2 2.5h8a2 2 0 012 2V17a2 2 0 01-2 2H5a2 2 0 '
              '01-2-2z"/>',
    'search': '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    'refresh': '<path d="M20 11a8 8 0 10-2.3 6.1"/><path d="M20 4.5V11h-6.2"/>',
    'play': '<path d="M8 5.5l11 6.5-11 6.5z"/>',
    'stop': '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    'save': '<path d="M5 3h11l3 3v15H5z"/><path d="M8.5 3v6h7V3M8.5 21v-7h7v7"/>',
    'open': '<path d="M3 7a2 2 0 012-2h4l2 2.5h8a2 2 0 012 2V17a2 2 0 01-2 2H5a2 2 0 '
            '01-2-2z"/><path d="M9 13h6"/>',
    'reset': '<path d="M4 12a8 8 0 102.4-5.7"/><path d="M4 4.5V11h6.2"/>',
    'warning': '<path d="M12 4.5L21 19H3z"/><path d="M12 10v4M12 16.6v.1"/>',
    'error': '<circle cx="12" cy="12" r="9"/><path d="M15.2 8.8l-6.4 6.4M8.8 8.8l6.4 6.4"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.9v.1"/>',
    'check': '<path d="M4.5 12.5l5 5 10-11"/>',
    'close': '<path d="M6 6l12 12M18 6L6 18"/>',
    'disk': '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 '
            '8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    'cpu': '<rect x="7" y="7" width="10" height="10" rx="1.5"/>'
           '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/>'
           '<path d="M9 1.5v2M15 1.5v2M9 20.5v2M15 20.5v2M1.5 9h2M1.5 15h2M20.5 9h2'
           'M20.5 15h2"/>',
    'memory': '<rect x="3" y="7" width="18" height="10" rx="2"/>'
              '<path d="M7 11v2M11 11v2M15 11v2M19 11v2"/>',
    'link': '<path d="M9.5 14.5l5-5"/><path d="M11 7l1.6-1.6a3.9 3.9 0 015.5 5.5L16.5 12.5"/>'
            '<path d="M13 17l-1.6 1.6a3.9 3.9 0 01-5.5-5.5L7.5 11.5"/>',
    'unlink': '<path d="M11 7l1.6-1.6a3.9 3.9 0 015.5 5.5L16.5 12.5"/>'
              '<path d="M13 17l-1.6 1.6a3.9 3.9 0 01-5.5-5.5L7.5 11.5"/>'
              '<path d="M3 3l18 18"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6.5V12l4 2.5"/>',
    'chevron-right': '<path d="M9.5 5l7 7-7 7"/>',
    'chevron-down': '<path d="M5 9.5l7 7 7-7"/>',
    'filter': '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'trash': '<path d="M4 7h16M9.5 7V4.5h5V7M6 7l1 13h10l1-13"/>',
    'bag': '<path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 016 0v2"/>',
    'wave': '<path d="M2 12h3l2-6 3 12 3-9 2 3h7"/>',
    'eye': '<path d="M2 12s3.8-6.5 10-6.5S22 12 22 12s-3.8 6.5-10 6.5S2 12 2 12z"/>'
           '<circle cx="12" cy="12" r="2.6"/>',
}

_cache = {}
_asset_dir = None


def svg_source(name, color=None, width=1.8):
    """Raw SVG text for *name*, tinted with *color*."""
    color = color or PALETTE.text
    body = _PATHS.get(name, _PATHS['info']).replace('{color}', color)
    return _STROKE.format(color=color, width=width, body=body)


def pixmap(name, color=None, size=18, width=1.8):
    key = (name, color, size, width)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(QByteArray(svg_source(name, color, width).encode('utf-8')))
    ratio = 2  # render at 2x so icons stay crisp on HiDPI displays
    image = QPixmap(QSize(size * ratio, size * ratio))
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    image.setDevicePixelRatio(ratio)
    _cache[key] = image
    return image


def icon(name, color=None, size=18, width=1.8):
    return QIcon(pixmap(name, color, size, width))


def app_icon_svg(palette=PALETTE):
    """Build the application icon: a bag with a record dot, for window and .desktop."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="{palette.bg_sunken}"/>
  <rect x="0.75" y="0.75" width="62.5" height="62.5" rx="13.25" fill="none"
        stroke="{palette.border_strong}" stroke-width="1.5"/>
  <path d="M16 22h32l-3 26H19z" fill="none" stroke="{palette.text_muted}"
        stroke-width="3" stroke-linejoin="round"/>
  <path d="M25 22v-4a7 7 0 0114 0v4" fill="none" stroke="{palette.text_muted}"
        stroke-width="3" stroke-linecap="round"/>
  <circle cx="32" cy="37" r="8" fill="{palette.recording}"/>
</svg>'''


def asset_dir():
    """Return a writable directory for SVGs the stylesheet references by path."""
    global _asset_dir
    if _asset_dir is None:
        base = os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache')
        try:
            path = os.path.join(base, 'rosbag_recorder_ui', 'assets')
            os.makedirs(path, exist_ok=True)
        except OSError:
            path = tempfile.mkdtemp(prefix='rosbag_recorder_ui_')
        _asset_dir = path
    return _asset_dir


def stylesheet_assets():
    """
    Write the few SVGs that QSS needs as files and return their paths.

    Qt stylesheets cannot take inline SVG, only url(), so the checkbox tick and
    the combo box arrow have to exist on disk somewhere.
    """
    assets = {
        'check': svg_source('check', PALETTE.on_accent, width=3.0),
        'chevron_down': svg_source('chevron-down', PALETTE.text_muted, width=2.2),
        'search': svg_source('search', PALETTE.text_dim, width=2.0),
    }
    paths = {}
    for name, source in assets.items():
        path = os.path.join(asset_dir(), f'{name}.svg')
        try:
            with open(path, 'w') as handle:
                handle.write(source)
        except OSError:
            continue
        paths[name] = path.replace('\\', '/')
    return paths
