"""
The dashboard's configuration model.

This deliberately speaks the same YAML that ros2_bag_recorder already reads.
A file saved here can be handed straight to

    ros2 launch ros2_bag_recorder recorder.launch.py params_file:=<path>
"""
import os

import yaml
from PySide6.QtCore import QObject, Signal
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory

from rosbag_recorder_msgs.msg import RecordingConfig

# The node name rosbag_param.yaml is keyed by; must match the recorder's node.
NODE_KEY = 'ros2_bag_recorder_node'
PARAMS_KEY = 'ros__parameters'


class ConfigError(Exception):
    """A configuration file could not be read or made sense of."""


def package_config_path(name='rosbag_param.yaml'):
    """Return the config file installed by ros2_bag_recorder, or '' if absent."""
    try:
        share = get_package_share_directory('ros2_bag_recorder')
    except (PackageNotFoundError, KeyError):
        return ''
    path = os.path.join(share, 'config', name)
    return path if os.path.exists(path) else ''


def user_config_dir():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    path = os.path.join(base, 'rosbag_recorder_ui')
    os.makedirs(path, exist_ok=True)
    return path


def default_config():
    config = RecordingConfig()
    config.selection_method = RecordingConfig.SELECTION_REGISTRY
    config.keywords = []
    config.manual_topics = []
    config.modules = []
    config.exclude_patterns = []
    config.registry_file = ''
    config.bag_path = os.path.expanduser('~/rosbags')
    config.bag_name = 'recording'
    config.append_timestamp = True
    config.storage_sqlite = True
    config.storage_mcap = False
    config.discovery_interval_sec = 1.0
    return config


def clone(config):
    copy = RecordingConfig()
    copy.selection_method = config.selection_method
    copy.keywords = list(config.keywords)
    copy.manual_topics = list(config.manual_topics)
    copy.modules = list(config.modules)
    copy.exclude_patterns = list(config.exclude_patterns)
    copy.registry_file = config.registry_file
    copy.bag_path = config.bag_path
    copy.bag_name = config.bag_name
    copy.append_timestamp = config.append_timestamp
    copy.storage_sqlite = config.storage_sqlite
    copy.storage_mcap = config.storage_mcap
    copy.discovery_interval_sec = config.discovery_interval_sec
    return copy


def _clean_list(values):
    """Drop the placeholder empty strings the YAML uses for 'no entries'."""
    return [str(v) for v in (values or []) if str(v).strip()]


def config_from_yaml(text, source=''):
    """
    Parse rosbag_param.yaml content into (RecordingConfig, module_states, warnings).
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise ConfigError(f'{source or "The file"} is not valid YAML: {err}') from err
    if not isinstance(document, dict):
        raise ConfigError(f'{source or "The file"} does not contain a parameter mapping.')

    warnings = []
    node = document.get(NODE_KEY)
    if node is None:
        # Tolerate a file keyed by a different node name rather than refusing it.
        candidates = [key for key, value in document.items()
                      if isinstance(value, dict) and PARAMS_KEY in value]
        if not candidates:
            raise ConfigError(
                f'{source or "The file"} has no "{NODE_KEY}: {PARAMS_KEY}:" section.')
        node = document[candidates[0]]
        warnings.append(f"Parameters were read from '{candidates[0]}', not '{NODE_KEY}'.")
    params = node.get(PARAMS_KEY) or {}

    config = default_config()
    config.selection_method = str(params.get('selection_method', config.selection_method))
    if config.selection_method not in ('registry', 'keywords', 'manual'):
        warnings.append(
            f"Unknown selection_method '{config.selection_method}'; using 'registry'.")
        config.selection_method = RecordingConfig.SELECTION_REGISTRY
    config.keywords = _clean_list(params.get('keywords'))
    config.manual_topics = _clean_list(params.get('manual_topics'))
    if config.selection_method == 'manual' and not config.manual_topics:
        warnings.append('The file selects topics manually but ticks none of them.')
    config.exclude_patterns = _clean_list(params.get('exclude_patterns'))
    config.registry_file = str(params.get('registry_file', '') or '')

    folder = params.get('bag_folder') or {}
    config.bag_path = os.path.expanduser(str(folder.get('path', config.bag_path)))
    config.bag_name = str(folder.get('name', config.bag_name))
    config.append_timestamp = bool(folder.get('append_timestamp', True))

    storage = params.get('storage_id') or {}
    config.storage_sqlite = bool(storage.get('sqlite', True))
    config.storage_mcap = bool(storage.get('mcap', False))
    if not (config.storage_sqlite or config.storage_mcap):
        warnings.append('No storage format was enabled; SQLite3 has been switched on.')
        config.storage_sqlite = True

    try:
        config.discovery_interval_sec = float(params.get('discovery_interval_sec', 1.0))
    except (TypeError, ValueError):
        warnings.append('discovery_interval_sec was not a number; using 1.0 s.')
        config.discovery_interval_sec = 1.0

    module_states = {}
    for name, enabled in (params.get('modules') or {}).items():
        module_states[str(name)] = bool(enabled)
    config.modules = sorted(name for name, on in module_states.items() if on)
    return config, module_states, warnings


MANUAL_MODULE = 'manual_selection'


def manual_registry_path(params_path):
    """Name the registry file written beside *params_path* for a manual selection."""
    if not params_path:
        return '<written beside the parameter file>'
    return f'{os.path.splitext(params_path)[0]}_manual_registry.yaml'


def manual_registry_yaml(config):
    """Render the ticked topics as an ordinary topic registry."""
    entries = '\n'.join(f'  - topic: {name}'
                        for name in sorted(t for t in config.manual_topics if t))
    return ('# Written by the ROS 2 Bag Recorder dashboard from a manual topic\n'
            '# selection. It is an ordinary topic registry: point the recorder at it\n'
            f'# with registry_file and enable the "{MANUAL_MODULE}" module.\n'
            f'\n{MANUAL_MODULE}:\n{entries}\n' if entries else
            f'# No topics were ticked.\n\n{MANUAL_MODULE}: []\n')


def registry_to_yaml(registry):
    """
    Render a topic registry dict back to the file format the recorder reads.
    """
    lines = [
        '# ==============================================================',
        '#  Topic Registry',
        '#  Each entry has exactly ONE key:',
        '#    topic:   exact topic name',
        '#    pattern: Python regex, fullmatched against topic names',
        '#  Message types are discovered from the ROS graph automatically.',
        '#  To add a module, create a section here and toggle it in',
        '#  rosbag_param.yaml under modules:.',
        '# ==============================================================',
        '',
    ]
    for module, entries in registry.items():
        lines.append(f'{module}:')
        rendered = 0
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if key in ('topic', 'pattern'):
                    lines.append(f'  - {key}: {value}')
                    rendered += 1
        if not rendered:
            # A module with no entries is legal and means 'nothing yet'; an
            # empty block would parse as None and fail validation.
            lines[-1] = f'{module}: []'
        lines.append('')
    return '\n'.join(lines)


def config_to_yaml(config, module_states, params_path=''):
    """
    Render a config back to rosbag_param.yaml.
    """
    def dump_list(values):
        return yaml.safe_dump(list(values) or [''], default_flow_style=True).strip()

    modules = '\n'.join(f'      {name}: {str(bool(on)).lower()}'
                        for name, on in sorted(module_states.items()))
    registry_line = ''
    if config.registry_file:
        registry_line = (
            '\n    # Alternative topic registry. Empty uses the packaged one.\n'
            f"    registry_file: '{config.registry_file}'\n")

    manual_block = ''
    if config.selection_method == 'manual' or config.manual_topics:
        manual_block = (
            "\n    # Topics ticked by hand, used only in 'manual' mode.\n"
            f'    manual_topics: {dump_list(config.manual_topics)}\n')
    manual_note = ''
    if config.selection_method == 'manual':
        manual_note = (
            "#\n"
            "# NOTE: 'manual' is a dashboard selection mode. The recorder itself only\n"
            "# understands 'registry' and 'keywords', so running THIS file directly\n"
            "# will stop with an error about selection_method. To replay the same\n"
            "# selection from a terminal, use the registry written beside this file:\n"
            f"#   selection_method: 'registry'\n"
            f"#   registry_file: '{manual_registry_path(params_path)}'\n"
            "#   modules: { manual_selection: true }\n")

    return f"""# Written by the ROS 2 Bag Recorder dashboard.
# This is a normal ros2_bag_recorder parameter file and stays usable from a
# terminal:
#   ros2 launch ros2_bag_recorder recorder.launch.py params_file:=<this file>
{manual_note}{NODE_KEY}:
  {PARAMS_KEY}:

    # How topics are selected this run:
    #   'registry' - use the modules toggled below (topic_registry.yaml)
    #   'keywords' - record every live topic whose name contains a keyword
    #   'manual'   - record exactly the topics listed in manual_topics
    selection_method: '{config.selection_method}'

    # Substring keywords, used only in 'keywords' mode.
    keywords: {dump_list(config.keywords)}
{manual_block}{registry_line}
    # Bag storage settings.
    bag_folder:
      path: '{config.bag_path}'
      name: '{config.bag_name}'
      append_timestamp: {str(bool(config.append_timestamp)).lower()}

    storage_id:
      sqlite: {str(bool(config.storage_sqlite)).lower()}
      mcap: {str(bool(config.storage_mcap)).lower()}

    # Seconds between ROS graph re-scans for newly appearing topics.
    discovery_interval_sec: {float(config.discovery_interval_sec)}

    # Regexes; any match is never recorded, even if a module includes it.
    exclude_patterns: {dump_list(config.exclude_patterns)}

    # Enable/disable modules defined in topic_registry.yaml.
    modules:
{modules if modules else '      {}'}
"""


class ConfigStore(QObject):
    """
    Holds the config every page edits, plus where it came from.
    """

    changed = Signal(object)          # RecordingConfig
    dirty_changed = Signal(bool)
    path_changed = Signal(str)
    modules_changed = Signal(list)    # available module names, from the registry
    notice = Signal(str, str)         # level, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = default_config()
        self._module_states = {}
        self._available_modules = []
        self._path = ''
        self._dirty = False

    # -- accessors ------------------------------------------------------

    @property
    def config(self):
        return self._config

    @property
    def path(self):
        return self._path

    @property
    def dirty(self):
        return self._dirty

    @property
    def available_modules(self):
        return list(self._available_modules)

    @property
    def module_states(self):
        """Map every known module name to whether it is enabled."""
        states = {name: False for name in self._available_modules}
        states.update(self._module_states)
        for name in self._config.modules:
            states[name] = True
        return states

    # -- mutation -------------------------------------------------------

    def update(self, **fields):
        """Set one or more config fields; no-ops when nothing actually changed."""
        touched = False
        for key, value in fields.items():
            if not hasattr(self._config, key):
                raise AttributeError(f'RecordingConfig has no field {key!r}')
            current = getattr(self._config, key)
            if isinstance(current, (list, tuple)) or isinstance(value, (list, tuple)):
                changed = list(current) != list(value)
                value = list(value)
            else:
                changed = current != value
            if changed:
                setattr(self._config, key, value)
                touched = True
        if touched:
            self._mark_dirty(True)
            self.changed.emit(self._config)
        return touched

    def set_module_enabled(self, name, enabled):
        states = self.module_states
        if states.get(name) == enabled:
            return
        self._module_states[name] = enabled
        states[name] = enabled
        self.update(modules=sorted(n for n, on in states.items() if on))
        self._mark_dirty(True)
        self.changed.emit(self._config)

    def set_manual_topic(self, name, enabled):
        """Tick or untick one topic in the manual selection."""
        topics = [t for t in self._config.manual_topics if t]
        if enabled and name not in topics:
            topics.append(name)
        elif not enabled and name in topics:
            topics.remove(name)
        else:
            return False
        return self.update(manual_topics=sorted(topics))

    def set_manual_topics(self, names):
        """Replace the whole manual selection, e.g. from a bulk tick."""
        return self.update(manual_topics=sorted({n for n in names if n}))

    def set_available_modules(self, modules):
        modules = sorted(modules)
        if modules == self._available_modules:
            return
        self._available_modules = modules
        for name in modules:
            self._module_states.setdefault(name, name in self._config.modules)
        self.modules_changed.emit(modules)

    def _mark_dirty(self, dirty):
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    # -- files ----------------------------------------------------------

    def load(self, path):
        """Load a parameter file. Raises ConfigError with an operator-readable message."""
        try:
            with open(path, 'r') as handle:
                text = handle.read()
        except OSError as err:
            raise ConfigError(f'Cannot read {path}: {err.strerror or err}') from err

        config, module_states, warnings = config_from_yaml(text, os.path.basename(path))
        self._config = config
        self._module_states = module_states
        self._path = path
        self._mark_dirty(False)
        self.path_changed.emit(path)
        self.changed.emit(self._config)
        for warning in warnings:
            self.notice.emit('warning', warning)
        return warnings

    def load_default(self):
        """Load the user's own file if they have one, else the packaged config."""
        user_file = os.path.join(user_config_dir(), 'rosbag_param.yaml')
        for candidate in (user_file, package_config_path()):
            if candidate and os.path.exists(candidate):
                try:
                    self.load(candidate)
                    return candidate
                except ConfigError as err:
                    self.notice.emit('warning', str(err))
        self.reset()
        return ''

    def save(self, path=None):
        target = path or self._path or os.path.join(user_config_dir(), 'rosbag_param.yaml')
        text = config_to_yaml(self._config, self.module_states, target)
        try:
            os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
            with open(target, 'w') as handle:
                handle.write(text)
        except OSError as err:
            raise ConfigError(f'Cannot write {target}: {err.strerror or err}') from err

        # A manual selection is not something the recorder can read directly, so
        # write the equivalent registry alongside it. That is what makes the
        # ticked list replayable from a terminal.
        if self._config.selection_method == 'manual':
            registry = manual_registry_path(target)
            try:
                with open(registry, 'w') as handle:
                    handle.write(manual_registry_yaml(self._config))
            except OSError as err:
                raise ConfigError(
                    f'Saved {target}, but the matching topic registry could not be '
                    f'written to {registry}: {err.strerror or err}') from err
        if target != self._path:
            self._path = target
            self.path_changed.emit(target)
        self._mark_dirty(False)
        return target

    def reset(self):
        self._config = default_config()
        self._module_states = {name: False for name in self._available_modules}
        self._mark_dirty(bool(self._path))
        self.changed.emit(self._config)

    def preview_yaml(self):
        return config_to_yaml(self._config, self.module_states)
