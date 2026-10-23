"""
Configuration: what gets recorded, and the parameter file that describes it.

This page edits the same rosbag_param.yaml the command line already uses. Load
one, change it, save it, and `ros2 launch ros2_bag_recorder recorder.launch.py
params_file:=...` keeps working exactly as before. The dashboard adds no
private configuration format of its own.
"""
import os

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from rosbag_recorder_msgs.msg import RecordingConfig

from rosbag_recorder_ui.core import icons
from rosbag_recorder_ui.core.config_store import (
    ConfigError,
    registry_to_yaml,
    user_config_dir,
)
from rosbag_recorder_ui.core.theme import MONO_STACK, PALETTE, SPACE_MD, SPACE_SM
from rosbag_recorder_ui.views.base import Page
from rosbag_recorder_ui.widgets.cards import Card, SectionCard
from rosbag_recorder_ui.widgets.dialogs import confirm, show_error
from rosbag_recorder_ui.widgets.listeditor import StringListEditor, validate_regex


class ConfigurationPage(Page):
    title_text = 'Configuration'
    subtitle_text = 'Topic selection and the parameter file behind it'

    changed = Signal()
    pick_topics_requested = Signal()
    registry_save_requested = Signal(str, str)   # registry_file, registry_yaml
    registry_reload_requested = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent=parent)
        self._store = store
        self._syncing = False
        self._registry = {}
        self._registry_path = ''
        self._registry_dirty = False

        self._build_actions()
        self.content.addWidget(self._build_file_card())
        self.content.addWidget(self._build_mode_card())

        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)
        row.addWidget(self._build_registry_card(), 3)
        row.addWidget(self._build_keywords_card(), 2)
        self.content.addLayout(row)

        self.content.addWidget(self._build_manual_card())

        self.content.addWidget(self._build_exclude_card())
        self.content.addWidget(self._build_advanced_card())
        self.content.addWidget(self._build_preview_card())
        self.content.addStretch(1)

        store.changed.connect(self._load_from_store)
        store.path_changed.connect(self._update_file_card)
        store.dirty_changed.connect(lambda _d: self._update_file_card())
        store.modules_changed.connect(lambda _m: self._rebuild_modules())
        self._rebuild_modules()
        self._load_from_store(store.config)

    # ------------------------------------------------------------------
    #  Header actions
    # ------------------------------------------------------------------

    def _build_actions(self):
        load = QPushButton('  Load')
        load.setIcon(icons.icon('open', PALETTE.text_muted, 15))
        load.clicked.connect(self._on_load)
        self.add_action(load)

        self.save_button = QPushButton('  Save')
        self.save_button.setIcon(icons.icon('save', PALETTE.text_muted, 15))
        self.save_button.clicked.connect(self._on_save)
        self.add_action(self.save_button)

        save_as = QPushButton('  Save as…')
        save_as.setProperty('variant', 'subtle')
        save_as.setIcon(icons.icon('save', PALETTE.text_muted, 15))
        save_as.clicked.connect(self._on_save_as)
        self.add_action(save_as)

        reset = QPushButton('  Reset')
        reset.setProperty('variant', 'subtle')
        reset.setIcon(icons.icon('reset', PALETTE.text_muted, 15))
        reset.clicked.connect(self._on_reset)
        self.add_action(reset)

    # ------------------------------------------------------------------
    #  Cards
    # ------------------------------------------------------------------

    def _build_file_card(self):
        card = Card(padding=SPACE_MD)
        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap('config', PALETTE.text_muted, 18))
        row.addWidget(glyph)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.file_label = QLabel('Unsaved configuration')
        self.file_label.setStyleSheet('font-weight: 600;')
        text.addWidget(self.file_label)
        self.file_hint = QLabel('')
        self.file_hint.setObjectName('CardHint')
        text.addWidget(self.file_hint)
        row.addLayout(text, 1)

        self.dirty_label = QLabel('')
        self.dirty_label.setObjectName('CardHint')
        row.addWidget(self.dirty_label)
        card.layout().addLayout(row)
        self._update_file_card()
        return card

    def _build_mode_card(self):
        card = SectionCard('Selection method', 'Exactly one applies per recording',
                           'filter')
        self.mode_group = QButtonGroup(self)
        row = QHBoxLayout()
        row.setSpacing(SPACE_MD * 2)

        self.registry_radio = QRadioButton('Registry modules')
        self.registry_radio.setToolTip(
            'Record the curated topic groups defined in topic_registry.yaml.')
        self.keywords_radio = QRadioButton('Keywords')
        self.keywords_radio.setToolTip(
            'Record every live topic whose name contains one of your keywords.')
        self.manual_radio = QRadioButton('Manual')
        self.manual_radio.setToolTip(
            'Record exactly the topics you tick on the Topics page.')
        hints = {
            RecordingConfig.SELECTION_REGISTRY: 'Curated and repeatable.',
            RecordingConfig.SELECTION_KEYWORDS:
                'Quick ad-hoc capture, no registry edit needed.',
            RecordingConfig.SELECTION_MANUAL:
                'Tick topics by hand on the Topics page.',
        }
        for button, value in ((self.registry_radio, RecordingConfig.SELECTION_REGISTRY),
                              (self.keywords_radio, RecordingConfig.SELECTION_KEYWORDS),
                              (self.manual_radio, RecordingConfig.SELECTION_MANUAL)):
            self.mode_group.addButton(button)
            button.toggled.connect(
                lambda checked, v=value: checked and self._push(selection_method=v))
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(button)
            hint = QLabel(hints[value])
            hint.setObjectName('CardHint')
            hint.setContentsMargins(26, 0, 0, 0)
            column.addWidget(hint)
            row.addLayout(column)
        row.addStretch(1)
        card.body.addLayout(row)
        return card

    def _build_registry_card(self):
        self.registry_card = SectionCard(
            'Registry modules', 'Tick the groups to record', 'topics')
        self.registry_path_label = QLabel('')
        self.registry_path_label.setObjectName('CardHint')
        self.registry_card.add_header_widget(self.registry_path_label)

        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(['Module', 'Entries'])
        self.module_tree.setRootIsDecorated(True)
        self.module_tree.setAlternatingRowColors(False)
        self.module_tree.setColumnWidth(0, 260)
        self.module_tree.itemChanged.connect(self._on_module_toggled)
        self.module_tree.setMinimumHeight(230)
        self.module_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.module_tree.customContextMenuRequested.connect(self._registry_menu)
        self.registry_card.body.addWidget(self.module_tree)

        self.registry_empty = QLabel(
            'No registry loaded yet. The bridge supplies it once connected.')
        self.registry_empty.setObjectName('CardHint')
        self.registry_empty.setWordWrap(True)
        self.registry_card.body.addWidget(self.registry_empty)

        # Editing the registry writes to the machine the bridge runs on, which
        # is the machine that will read it back. Doing it here rather than in
        # an editor on the wrong host is the whole point.
        edit_row = QHBoxLayout()
        edit_row.setSpacing(SPACE_SM)
        add_module = QPushButton('  Add module')
        add_module.setProperty('variant', 'ghost')
        add_module.setIcon(icons.icon('plus', PALETTE.text_muted, 14))
        add_module.setToolTip('Add an empty module. Right-click a module to add '
                              'topics or patterns to it.')
        add_module.clicked.connect(self._add_module)
        edit_row.addWidget(add_module)
        self.registry_hint = QLabel('Right-click a module or entry to edit it.')
        self.registry_hint.setObjectName('CardHint')
        edit_row.addWidget(self.registry_hint, 1)

        self.registry_revert = QPushButton('Revert')
        self.registry_revert.setProperty('variant', 'ghost')
        self.registry_revert.setEnabled(False)
        self.registry_revert.setToolTip('Throw the edits away and re-read the '
                                        'registry from the bridge.')
        self.registry_revert.clicked.connect(self._revert_registry)
        edit_row.addWidget(self.registry_revert)

        self.registry_save = QPushButton('  Save registry')
        self.registry_save.setProperty('variant', 'primary')
        self.registry_save.setIcon(icons.icon('save', PALETTE.on_accent, 14))
        self.registry_save.setEnabled(False)
        self.registry_save.setToolTip('Write the registry back to the recording '
                                      'machine, after the bridge validates it.')
        self.registry_save.clicked.connect(self._save_registry)
        edit_row.addWidget(self.registry_save)
        self.registry_card.body.addLayout(edit_row)
        return self.registry_card

    # ------------------------------------------------------------------
    #  Registry editing
    # ------------------------------------------------------------------

    def _registry_menu(self, point):
        item = self.module_tree.itemAt(point)
        menu = QMenu(self)
        if item is None:
            menu.addAction('Add module…', self._add_module)
        elif item.parent() is None:
            module = item.data(0, Qt.UserRole)
            menu.addAction('Add topic…', lambda: self._add_entry(module, 'topic'))
            menu.addAction('Add pattern…', lambda: self._add_entry(module, 'pattern'))
            menu.addSeparator()
            menu.addAction('Remove this module', lambda: self._remove_module(module))
        else:
            module = item.parent().data(0, Qt.UserRole)
            index = item.parent().indexOfChild(item)
            menu.addAction('Remove this entry',
                           lambda: self._remove_entry(module, index))
        menu.exec(self.module_tree.viewport().mapToGlobal(point))

    def _add_module(self):
        name, accepted = QInputDialog.getText(
            self, 'Add a registry module', 'Module name (e.g. lidar):')
        name = (name or '').strip()
        if not accepted or not name:
            return
        if name in self._registry:
            show_error(self, 'That module already exists',
                       f"The registry already has a module called '{name}'.")
            return
        self._registry[name] = []
        self._mark_registry_dirty()

    def _remove_module(self, module):
        entries = self._registry.get(module) or []
        if entries and not confirm(
                self, f'Remove the "{module}" module?',
                f'Its {len(entries)} entr'
                + ('y goes' if len(entries) == 1 else 'ies go')
                + ' with it. Nothing is written until you save the registry.',
                confirm_text='Remove module'):
            return
        self._registry.pop(module, None)
        self._mark_registry_dirty()

    def _add_entry(self, module, kind):
        label = ('Exact topic name (e.g. /lidar/points):' if kind == 'topic'
                 else r'Regex, full-matched (e.g. /lidar/.+/points):')
        value, accepted = QInputDialog.getText(
            self, f'Add a {kind} to "{module}"', label)
        value = (value or '').strip()
        if not accepted or not value:
            return
        if kind == 'pattern':
            problem = validate_regex(value)
            if problem:
                show_error(self, 'That is not a usable regex', problem)
                return
        self._registry.setdefault(module, []).append({kind: value})
        self._mark_registry_dirty()

    def _remove_entry(self, module, index):
        entries = self._registry.get(module) or []
        if 0 <= index < len(entries):
            entries.pop(index)
            self._mark_registry_dirty()

    def _mark_registry_dirty(self, dirty=True):
        self._registry_dirty = dirty
        self.registry_save.setEnabled(dirty)
        self.registry_revert.setEnabled(dirty)
        self.registry_hint.setText(
            'Unsaved registry changes. They reach the recorder only once saved.'
            if dirty else 'Right-click a module or entry to edit it.')
        self.registry_hint.setStyleSheet(
            f'color: {PALETTE.warning};' if dirty else '')
        if dirty:
            self._store.set_available_modules(list(self._registry))
        self._rebuild_modules()

    def _save_registry(self):
        target = self._registry_path or self._store.config.registry_file
        if ((os.sep + 'install' + os.sep) in target
                or (os.sep + 'share' + os.sep) in target) and not confirm(
                self, 'Overwrite the packaged registry?',
                'This registry lives inside a colcon install tree, so saving it '
                'also changes what a plain "ros2 launch ros2_bag_recorder '
                'recorder.launch.py" records.',
                confirm_text='Overwrite', detail=target):
            return
        self.registry_save.setEnabled(False)
        self.registry_save.setText('  Saving…')
        self.registry_save_requested.emit(self._store.config.registry_file,
                                          registry_to_yaml(self._registry))

    def registry_saved(self, response=None, error=''):
        """Report what the bridge said about the registry we just sent."""
        self.registry_save.setText('  Save registry')
        if error or (response is not None and not response.success):
            self.registry_save.setEnabled(True)
            show_error(self, 'The registry could not be saved',
                       error or response.message)
            return
        self._mark_registry_dirty(False)

    def _revert_registry(self):
        if not confirm(self, 'Discard the registry edits?',
                       'The registry is re-read from the recording machine and '
                       'your changes here are lost. The file on disk was never '
                       'touched.', confirm_text='Discard'):
            return
        self._mark_registry_dirty(False)
        self.registry_reload_requested.emit()

    def _build_keywords_card(self):
        self.keywords_card = SectionCard(
            'Keywords', 'Substring match against the topic name', 'search')
        self.keyword_editor = StringListEditor(
            placeholder='camera, gps, imu…',
            empty_hint='No keywords yet. "camera" would record /camera/left/image '
                       'and /front/camera_info.')
        self.keyword_editor.changed.connect(
            lambda values: self._push(keywords=values))
        self.keywords_card.body.addWidget(self.keyword_editor)
        return self.keywords_card

    def _build_manual_card(self):
        self.manual_card = SectionCard(
            'Manual selection', '', 'check')
        go = QPushButton('  Pick on the Topics page')
        go.setProperty('variant', 'ghost')
        go.setIcon(icons.icon('topics', PALETTE.text_muted, 14))
        go.clicked.connect(self.pick_topics_requested)
        self.manual_card.add_header_widget(go)

        self.manual_list = QPlainTextEdit()
        self.manual_list.setReadOnly(True)
        self.manual_list.setMaximumHeight(150)
        self.manual_list.setStyleSheet(
            f'font-family: {MONO_STACK}; font-size: 12px; '
            f'background: {PALETTE.bg_sunken};')
        self.manual_card.body.addWidget(self.manual_list)

        note = QLabel(
            'Saving a manual selection also writes a matching topic registry next to '
            'the parameter file, so the same set of topics can be recorded from a '
            'terminal.')
        note.setObjectName('CardHint')
        note.setWordWrap(True)
        self.manual_card.body.addWidget(note)
        return self.manual_card

    def _build_exclude_card(self):
        card = SectionCard(
            'Exclude patterns',
            'Regular expressions, full-matched against topic names. Applied last, '
            'so an exclusion always wins.', 'close')
        self.exclude_editor = StringListEditor(
            placeholder=r'/camera/debug/.*',
            validator=validate_regex,
            empty_hint='Nothing is excluded.')
        self.exclude_editor.changed.connect(
            lambda values: self._push(exclude_patterns=values))
        card.body.addWidget(self.exclude_editor)
        return card

    def _build_advanced_card(self):
        card = SectionCard('Advanced', '', 'config')
        row = QHBoxLayout()
        row.setSpacing(SPACE_MD)

        column = QVBoxLayout()
        column.setSpacing(2)
        label = QLabel('DISCOVERY INTERVAL')
        label.setObjectName('CardLabel')
        column.addWidget(label)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(' s')
        self.interval_spin.setToolTip(
            'How often the recorder re-scans the graph for topics that appeared '
            'after it started.')
        self.interval_spin.valueChanged.connect(
            lambda value: self._push(discovery_interval_sec=float(value)))
        column.addWidget(self.interval_spin)
        row.addLayout(column)

        column = QVBoxLayout()
        column.setSpacing(2)
        label = QLabel('TOPIC REGISTRY FILE')
        label.setObjectName('CardLabel')
        column.addWidget(label)
        path_row = QHBoxLayout()
        path_row.setSpacing(SPACE_SM)
        self.registry_edit = QLineEdit()
        self.registry_edit.setPlaceholderText(
            'empty = the one installed with ros2_bag_recorder')
        self.registry_edit.textEdited.connect(
            lambda text: self._push(registry_file=text))
        path_row.addWidget(self.registry_edit, 1)
        browse = QPushButton('  Browse')
        browse.setIcon(icons.icon('open', PALETTE.text_muted, 14))
        browse.clicked.connect(self._browse_registry)
        path_row.addWidget(browse)
        column.addLayout(path_row)
        row.addLayout(column, 1)
        card.body.addLayout(row)
        return card

    def _build_preview_card(self):
        card = SectionCard('Parameter file preview',
                           'Exactly what Save would write', 'save')
        self.preview_toggle = QPushButton('Show')
        self.preview_toggle.setProperty('variant', 'ghost')
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.toggled.connect(self._toggle_preview)
        card.add_header_widget(self.preview_toggle)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setVisible(False)
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet(
            f'font-family: {MONO_STACK}; font-size: 12px; '
            f'background: {PALETTE.bg_sunken};')
        card.body.addWidget(self.preview)
        return card

    # ------------------------------------------------------------------
    #  Store synchronisation
    # ------------------------------------------------------------------

    def _push(self, **fields):
        if self._syncing:
            return
        if self._store.update(**fields):
            self.changed.emit()

    def _load_from_store(self, config):
        self._syncing = True
        try:
            is_keywords = config.selection_method == RecordingConfig.SELECTION_KEYWORDS
            is_manual = config.selection_method == RecordingConfig.SELECTION_MANUAL
            self.keywords_radio.setChecked(is_keywords)
            self.manual_radio.setChecked(is_manual)
            self.registry_radio.setChecked(not is_keywords and not is_manual)
            self.keyword_editor.set_values(config.keywords)
            self.exclude_editor.set_values(config.exclude_patterns)
            self.interval_spin.setValue(config.discovery_interval_sec or 1.0)
            if self.registry_edit.text() != config.registry_file:
                self.registry_edit.setText(config.registry_file)
            self._sync_module_checks()
        finally:
            self._syncing = False

        self.registry_card.setEnabled(not is_keywords and not is_manual)
        self.keywords_card.setEnabled(is_keywords)
        self.manual_card.setEnabled(is_manual)
        inactive = 'Ignored while another selection method is active'
        self.registry_card.set_subtitle(
            'Tick the groups to record' if self.registry_card.isEnabled() else inactive)
        self.keywords_card.set_subtitle(
            'Substring match against the topic name' if is_keywords else inactive)
        count = len(config.manual_topics)
        self.manual_card.set_subtitle(
            f'{count} topic(s) ticked on the Topics page' if is_manual else inactive)
        self.manual_list.setPlainText('\n'.join(config.manual_topics)
                                      or 'Nothing ticked yet.')
        if self.preview.isVisible():
            self.preview.setPlainText(self._store.preview_yaml())

    def _update_file_card(self, *_args):
        path = self._store.path
        self.file_label.setText(os.path.basename(path) if path
                                else 'Unsaved configuration')
        self.file_hint.setText(path or
                               'Save writes to ' + os.path.join(user_config_dir(),
                                                                'rosbag_param.yaml'))
        dirty = self._store.dirty
        self.dirty_label.setText('UNSAVED CHANGES' if dirty else 'saved')
        self.dirty_label.setStyleSheet(
            f'color: {PALETTE.warning if dirty else PALETTE.text_dim}; '
            'font-size: 11px; font-weight: 700; letter-spacing: 0.8px;')

    # ------------------------------------------------------------------
    #  Registry
    # ------------------------------------------------------------------

    def set_registry(self, registry_yaml, registry_path, modules):
        """Adopt the registry the bridge reports it will actually use."""
        self._registry_path = registry_path or ''
        self.registry_path_label.setText(registry_path or '')
        if self._registry_dirty:
            # The bridge re-sends the registry on every reconnect. Throwing
            # away edits the operator has not saved yet would be its own bug.
            return
        try:
            parsed = yaml.safe_load(registry_yaml) or {}
        except yaml.YAMLError:
            parsed = {}
        self._registry = parsed if isinstance(parsed, dict) else {}
        self._store.set_available_modules(modules or list(self._registry))
        self._rebuild_modules()

    def _rebuild_modules(self):
        modules = self._store.available_modules
        self.module_tree.setVisible(bool(modules))
        self.registry_empty.setVisible(not modules)
        if not modules:
            return

        self._syncing = True
        try:
            self.module_tree.clear()
            states = self._store.module_states
            for name in modules:
                entries = self._registry.get(name) or []
                item = QTreeWidgetItem([name, f'{len(entries)}'])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if states.get(name)
                                   else Qt.Unchecked)
                item.setData(0, Qt.UserRole, name)
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    for key, value in entry.items():
                        child = QTreeWidgetItem([str(value),
                                                 'regex' if key == 'pattern' else ''])
                        child.setForeground(0, QColor(PALETTE.text_dim))
                        item.addChild(child)
                self.module_tree.addTopLevelItem(item)
        finally:
            self._syncing = False

    def _sync_module_checks(self):
        states = self._store.module_states
        for index in range(self.module_tree.topLevelItemCount()):
            item = self.module_tree.topLevelItem(index)
            name = item.data(0, Qt.UserRole)
            wanted = Qt.Checked if states.get(name) else Qt.Unchecked
            if item.checkState(0) != wanted:
                item.setCheckState(0, wanted)

    def _on_module_toggled(self, item, column):
        if self._syncing or column != 0 or item.parent() is not None:
            return
        name = item.data(0, Qt.UserRole)
        if name:
            self._store.set_module_enabled(name, item.checkState(0) == Qt.Checked)
            self.changed.emit()

    def _browse_registry(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, 'Choose a topic registry', os.path.expanduser('~'),
            'YAML files (*.yaml *.yml);;All files (*)')
        if path:
            self.registry_edit.setText(path)
            self._push(registry_file=path)

    # ------------------------------------------------------------------
    #  File actions
    # ------------------------------------------------------------------

    def _on_load(self):
        if self._store.dirty and not confirm(
                self, 'Discard unsaved changes?',
                'The current configuration has changes that have not been saved.',
                confirm_text='Discard and load'):
            return
        start = os.path.dirname(self._store.path) or user_config_dir()
        path, _filter = QFileDialog.getOpenFileName(
            self, 'Load a recorder parameter file', start,
            'YAML files (*.yaml *.yml);;All files (*)')
        if not path:
            return
        try:
            self._store.load(path)
        except ConfigError as err:
            show_error(self, 'That file could not be loaded', str(err))
            return
        self.changed.emit()

    def _on_save(self):
        target = self._store.path
        if not target:
            self._on_save_as()
            return
        if not self._confirm_overwrite(target):
            return
        self._write(target)

    def _on_save_as(self):
        start = self._store.path or os.path.join(user_config_dir(), 'rosbag_param.yaml')
        path, _filter = QFileDialog.getSaveFileName(
            self, 'Save recorder parameters', start, 'YAML files (*.yaml *.yml)')
        if not path:
            return
        if not path.endswith(('.yaml', '.yml')):
            path += '.yaml'
        self._write(path)

    def _confirm_overwrite(self, target):
        # Writing into an install/ or share/ tree changes what the command line
        # will pick up by default, which is worth a deliberate yes.
        if os.sep + 'install' + os.sep in target or os.sep + 'share' + os.sep in target:
            return confirm(
                self, 'Overwrite the packaged configuration?',
                'This file lives inside a colcon install tree, so saving it changes '
                'the defaults used by "ros2 launch ros2_bag_recorder '
                'recorder.launch.py" as well.',
                confirm_text='Overwrite', detail=target)
        return True

    def _write(self, path):
        try:
            saved = self._store.save(path)
        except ConfigError as err:
            show_error(self, 'The configuration could not be saved', str(err))
            return
        self._update_file_card()
        self.changed.emit()
        self.set_subtitle(f'Saved to {saved}')

    def _on_reset(self):
        if not confirm(self, 'Reset to defaults?',
                       'Every selection, keyword and exclude pattern goes back to the '
                       'built-in defaults. The file on disk is not touched until you '
                       'save.', confirm_text='Reset'):
            return
        self._store.reset()
        self.changed.emit()

    def _toggle_preview(self, shown):
        self.preview.setVisible(shown)
        self.preview_toggle.setText('Hide' if shown else 'Show')
        if shown:
            self.preview.setPlainText(self._store.preview_yaml())
