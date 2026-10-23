"""
Round-trip tests for the parameter file.

The contract that matters: a file the dashboard writes must be readable by
ros2_bag_recorder from a terminal, and a file written by hand must load into
the dashboard without losing anything.
"""
import os
import tempfile

import pytest
import yaml

from rosbag_recorder_ui.core.config_store import (
    NODE_KEY,
    PARAMS_KEY,
    ConfigError,
    config_from_yaml,
    config_to_yaml,
    default_config,
)

HANDWRITTEN = """
ros2_bag_recorder_node:
  ros__parameters:
    selection_method: 'keywords'
    keywords: ['camera','global']
    bag_folder:
      path: '/data/rosbags'
      name: 'mission_007'
      append_timestamp: true
    storage_id:
      sqlite: true
      mcap: true
    discovery_interval_sec: 2.5
    exclude_patterns: ['/camera/debug/.*']
    modules:
      camera: true
      depth: false
      tf: true
"""


def test_reads_a_handwritten_file():
    config, modules, warnings = config_from_yaml(HANDWRITTEN)
    assert config.selection_method == 'keywords'
    assert list(config.keywords) == ['camera', 'global']
    assert config.bag_path == '/data/rosbags'
    assert config.bag_name == 'mission_007'
    assert config.append_timestamp is True
    assert config.storage_sqlite and config.storage_mcap
    assert config.discovery_interval_sec == 2.5
    assert list(config.exclude_patterns) == ['/camera/debug/.*']
    assert sorted(config.modules) == ['camera', 'tf']
    assert modules == {'camera': True, 'depth': False, 'tf': True}
    assert warnings == []


def test_placeholder_empty_strings_are_dropped():
    # The packaged config uses [''] to mean 'no entries'; that must not become
    # a keyword that matches every topic.
    text = HANDWRITTEN.replace("['camera','global']", "['']") \
                      .replace("['/camera/debug/.*']", "['']")
    config, _modules, _warnings = config_from_yaml(text)
    assert list(config.keywords) == []
    assert list(config.exclude_patterns) == []


def test_round_trip_preserves_everything():
    config, modules, _warnings = config_from_yaml(HANDWRITTEN)
    again, again_modules, warnings = config_from_yaml(config_to_yaml(config, modules))
    assert warnings == []
    assert again.selection_method == config.selection_method
    assert list(again.keywords) == list(config.keywords)
    assert list(again.exclude_patterns) == list(config.exclude_patterns)
    assert again.bag_path == config.bag_path
    assert again.bag_name == config.bag_name
    assert again.append_timestamp == config.append_timestamp
    assert again.storage_sqlite == config.storage_sqlite
    assert again.storage_mcap == config.storage_mcap
    assert again.discovery_interval_sec == config.discovery_interval_sec
    assert again_modules == modules


def test_generated_file_has_the_shape_the_recorder_expects():
    config, modules, _warnings = config_from_yaml(HANDWRITTEN)
    document = yaml.safe_load(config_to_yaml(config, modules))
    params = document[NODE_KEY][PARAMS_KEY]
    for key in ('selection_method', 'keywords', 'bag_folder', 'storage_id',
                'discovery_interval_sec', 'exclude_patterns', 'modules'):
        assert key in params, f'{key} missing from the generated parameter file'
    assert set(params['bag_folder']) == {'path', 'name', 'append_timestamp'}
    assert set(params['storage_id']) == {'sqlite', 'mcap'}


def test_missing_node_section_is_an_error():
    with pytest.raises(ConfigError):
        config_from_yaml('some_other_thing: 3')


def test_broken_yaml_is_an_error():
    with pytest.raises(ConfigError):
        config_from_yaml('a: [1, 2\n  b: }')


def test_no_storage_selected_is_repaired_with_a_warning():
    text = HANDWRITTEN.replace('sqlite: true', 'sqlite: false') \
                      .replace('mcap: true', 'mcap: false')
    config, _modules, warnings = config_from_yaml(text)
    assert config.storage_sqlite is True
    assert any('storage' in w.lower() for w in warnings)


def test_unknown_selection_method_falls_back_with_a_warning():
    text = HANDWRITTEN.replace("'keywords'", "'telepathy'")
    config, _modules, warnings = config_from_yaml(text)
    assert config.selection_method == 'registry'
    assert any('telepathy' in w for w in warnings)


def test_empty_module_map_still_writes_valid_yaml():
    document = yaml.safe_load(config_to_yaml(default_config(), {}))
    assert document[NODE_KEY][PARAMS_KEY]['modules'] in ({}, None)


def test_written_file_is_loadable_from_disk():
    config, modules, _warnings = config_from_yaml(HANDWRITTEN)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'params.yaml')
        with open(path, 'w') as handle:
            handle.write(config_to_yaml(config, modules))
        with open(path, 'r') as handle:
            reloaded, _m, warnings = config_from_yaml(handle.read())
    assert warnings == []
    assert reloaded.bag_name == 'mission_007'


# --- manual selection ------------------------------------------------------

MANUAL = """
ros2_bag_recorder_node:
  ros__parameters:
    selection_method: 'manual'
    manual_topics: ['/camera/left/image', '/tf']
    bag_folder:
      path: '/data/rosbags'
      name: 'ad_hoc'
      append_timestamp: true
    storage_id:
      sqlite: true
      mcap: false
    discovery_interval_sec: 1.0
    exclude_patterns: ['']
    modules: {}
"""


def test_manual_mode_round_trips():
    config, modules, warnings = config_from_yaml(MANUAL)
    assert config.selection_method == 'manual'
    assert list(config.manual_topics) == ['/camera/left/image', '/tf']
    assert warnings == []

    again, _m, warnings = config_from_yaml(config_to_yaml(config, modules))
    assert again.selection_method == 'manual'
    assert list(again.manual_topics) == ['/camera/left/image', '/tf']
    assert warnings == []


def test_manual_mode_with_nothing_ticked_warns():
    text = MANUAL.replace("['/camera/left/image', '/tf']", "['']")
    config, _modules, warnings = config_from_yaml(text)
    assert list(config.manual_topics) == []
    assert any('ticks none' in w for w in warnings)


def test_saving_manual_also_writes_a_usable_registry():
    from rosbag_recorder_ui.core.config_store import ConfigStore, manual_registry_path

    config, _modules, _warnings = config_from_yaml(MANUAL)
    store = ConfigStore()
    store.update(selection_method='manual',
                 manual_topics=list(config.manual_topics))
    with tempfile.TemporaryDirectory() as directory:
        target = os.path.join(directory, 'ad_hoc.yaml')
        store.save(target)
        registry_path = manual_registry_path(target)
        assert os.path.exists(registry_path), 'no registry written beside the params'
        with open(registry_path) as handle:
            registry = yaml.safe_load(handle.read())

    # The registry has to be something ros2_bag_recorder can consume directly:
    # a mapping of module -> list of {topic: name} entries.
    assert set(registry) == {'manual_selection'}
    entries = registry['manual_selection']
    assert [e['topic'] for e in entries] == ['/camera/left/image', '/tf']


def test_manual_params_file_explains_the_cli_route():
    config, modules, _warnings = config_from_yaml(MANUAL)
    text = config_to_yaml(config, modules, '/tmp/ad_hoc.yaml')
    assert '/tmp/ad_hoc_manual_registry.yaml' in text
    assert 'manual_selection: true' in text
