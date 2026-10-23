"""
Tests for the parts of the bridge that need no ROS graph.

Bag naming and pre-flight are where a mistake costs an operator a recording,
so they are checked directly rather than only through the end-to-end path.
"""
import os
import tempfile

import pytest

from rosbag_recorder_msgs.msg import RecordingConfig

from rosbag_recorder_bridge.session import RecordingSession, SessionError


class _Logger:
    def info(self, *_args):
        pass

    def warning(self, *_args):
        pass

    def error(self, *_args):
        pass


def make_config(**overrides):
    config = RecordingConfig()
    config.selection_method = 'keywords'
    config.keywords = ['camera']
    config.bag_path = '/tmp/does_not_matter'
    config.bag_name = 'run'
    config.append_timestamp = False
    config.storage_sqlite = True
    config.storage_mcap = False
    config.discovery_interval_sec = 1.0
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def session(**overrides):
    return RecordingSession(make_config(**overrides), _Logger())


def test_uri_per_enabled_format():
    both = session(storage_mcap=True)
    assert both.formats == ['sqlite', 'mcap']
    assert [os.path.basename(u) for u in both.bag_uris] == ['run_sqlite', 'run_mcap']


def test_timestamp_is_resolved_up_front():
    # The bridge, not the recorder, decides the final name, so it can report
    # the real bag paths back to the operator.
    stamped = session(append_timestamp=True)
    assert stamped.bag_name.startswith('run_')
    assert len(stamped.bag_name) == len('run_2026-08-10_10-00-00')
    assert all(stamped.bag_name in uri for uri in stamped.bag_uris)


def test_preflight_rejects_no_storage_format():
    with pytest.raises(SessionError, match='storage format'):
        session(storage_sqlite=False, storage_mcap=False).preflight()


def test_preflight_rejects_a_slash_in_the_name():
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(SessionError, match='slash'):
            session(bag_path=directory, bag_name='nested/run').preflight()


def test_preflight_rejects_an_unwritable_path():
    with pytest.raises(SessionError, match='Cannot write'):
        session(bag_path='/proc/nope/nowhere').preflight()


def test_preflight_rejects_an_existing_bag():
    with tempfile.TemporaryDirectory() as directory:
        os.makedirs(os.path.join(directory, 'run_sqlite'))
        with pytest.raises(SessionError, match='already exists'):
            session(bag_path=directory).preflight()


def test_preflight_rejects_an_unknown_selection_method():
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(SessionError, match='selection method'):
            session(bag_path=directory, selection_method='vibes').preflight()


def test_preflight_passes_on_a_clean_directory():
    with tempfile.TemporaryDirectory() as directory:
        assert session(bag_path=directory).preflight() == []


def test_duration_is_zero_before_start():
    assert session().duration() == 0.0


def test_write_rate_is_unknown_until_there_are_two_samples():
    active = session()
    assert active.write_rate(0) == -1.0


# --- manual selection ------------------------------------------------------

def test_manual_mode_is_accepted_by_preflight():
    with tempfile.TemporaryDirectory() as directory:
        assert session(bag_path=directory, selection_method='manual',
                       manual_topics=['/a', '/b']).preflight() == []


def test_manual_mode_with_nothing_ticked_is_refused():
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(SessionError, match='ticked'):
            session(bag_path=directory, selection_method='manual',
                    manual_topics=[]).preflight()


def test_manual_selection_becomes_a_registry_the_recorder_can_read(monkeypatch):
    import yaml

    from rosbag_recorder_bridge.session import MANUAL_MODULE

    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setenv('XDG_STATE_HOME', directory)
        active = session(bag_path=directory, selection_method='manual',
                         manual_topics=['/camera/left/image', '/tf'])
        overrides = {p.name: p.value for p in active._parameter_overrides()}

        # The recorder never sees 'manual'; it sees ordinary registry mode.
        assert overrides['selection_method'] == 'registry'
        assert overrides[f'modules.{MANUAL_MODULE}'] is True

        with open(overrides['registry_file']) as handle:
            registry = yaml.safe_load(handle.read())
        assert set(registry) == {MANUAL_MODULE}
        assert [e['topic'] for e in registry[MANUAL_MODULE]] == [
            '/camera/left/image', '/tf']


def test_registry_and_keyword_modes_are_passed_through_untouched():
    with tempfile.TemporaryDirectory() as directory:
        keywords = session(bag_path=directory, selection_method='keywords')
        overrides = {p.name: p.value for p in keywords._parameter_overrides()}
        assert overrides['selection_method'] == 'keywords'
        assert overrides['registry_file'] == ''
