import io
from pathlib import Path
import sqlite3
import zipfile
import pytest
from dubdash_replay.replay import (SENSOR_TOPICS, DATASET_SHA256, inspect_bag, validate_database,
                            playback_command, stereo_launch_arguments, dataset_url)
from mapping_demo import extract_bag, snapshot_map, main


def make_bag(path, missing=None):
    path.mkdir(parents=True)
    (path / 'metadata.yaml').write_text('rosbag2_bagfile_information: {}\n')
    with sqlite3.connect(path / 'test.db3') as connection:
        connection.execute('CREATE TABLE topics (name TEXT, type TEXT)')
        for name, kind in {**SENSOR_TOPICS, '/tf_static': 'tf2_msgs/msg/TFMessage'}.items():
            if name != missing:
                connection.execute('INSERT INTO topics VALUES (?, ?)', (name, kind))
        connection.execute('CREATE TABLE messages (id INTEGER)')
        connection.execute('INSERT INTO messages VALUES (1)')
    return path


def make_map(path):
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE Node (id INTEGER)')
        connection.execute('INSERT INTO Node VALUES (1)')
    return path


def test_recorded_bag_contract_and_missing_sensor(tmp_path):
    bag = make_bag(tmp_path / 'valid')
    assert inspect_bag(bag)['messages'] == 1
    bad = make_bag(tmp_path / 'missing', missing=next(iter(SENSOR_TOPICS)))
    with pytest.raises(ValueError, match='stereo topics'):
        inspect_bag(bad)
    with pytest.raises(ValueError, match='metadata'):
        inspect_bag(tmp_path / 'absent')


def test_mapping_never_overwrites_and_localization_requires_map(tmp_path):
    path = tmp_path / 'map.db'
    assert validate_database(path, 'mapping') == path
    with pytest.raises(ValueError, match='No saved map'):
        validate_database(path, 'localization')
    make_map(path)
    with pytest.raises(ValueError, match='already exists'):
        validate_database(path, 'mapping')
    assert validate_database(path, 'localization') == path
    path.write_text('not sqlite')
    with pytest.raises(ValueError, match='Not a readable'):
        validate_database(path, 'localization')


def test_snapshot_preserves_original_and_refuses_overwrite(tmp_path):
    source = make_map(tmp_path / 'map.db')
    before = source.read_bytes()
    target = snapshot_map(source, tmp_path / 'local.db')
    with sqlite3.connect(target) as connection:
        connection.execute('INSERT INTO Node VALUES (2)')
    assert source.read_bytes() == before
    for destination in (source, target):
        with pytest.raises(ValueError):
            snapshot_map(source, destination)


@pytest.mark.parametrize('rate', [0, -1, float('nan'), float('inf')])
def test_bad_rate(rate):
    with pytest.raises(ValueError):
        playback_command('bag', rate)


def test_player_paused_clock_and_sensor_only():
    command = playback_command('bag', 0.5)
    assert '--start-paused' in command
    assert command[command.index('--clock') + 1] == '30'
    assert set(command[command.index('--topics') + 1:]) == {*SENSOR_TOPICS, '/tf', '/tf_static'}
    assert '/cmd_vel' not in command and '--loop' not in command


def test_launch_mode_and_explicit_database():
    args = stereo_launch_arguments('/tmp/map.db', 'localization', '/tmp/view.rviz', False)
    assert args['localization'] == 'true'
    assert args['visual_odometry'] == 'true' and args['stereo'] == 'true'
    assert args['database_path'] == '/tmp/map.db'
    assert args['rviz'] == 'false' and args['use_sim_time'] == 'true'
    assert '-d' not in args['args'] and 'delete' not in args['args']


def test_safe_archive_and_existing_destination(tmp_path):
    bag = make_bag(tmp_path / 'bag')
    archive = tmp_path / 'bag.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for file in bag.iterdir():
            output.write(file, f'bag/{file.name}')
    target = extract_bag(archive, tmp_path / 'extracted', 'bag')
    assert inspect_bag(target)['messages'] == 1
    with pytest.raises(ValueError, match='exists'):
        extract_bag(archive, target, 'bag')


@pytest.mark.parametrize('name', ['../escape.db3', '/outside.db3', 'folder\\escape.db3',
                                  'C:/escape.db3', 'bag/file:stream.db3'])
def test_archive_traversal_rejected(tmp_path, name):
    archive = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        entry = zipfile.ZipInfo(name)
        # Preserve a deliberately unsafe raw name even on Windows, where
        # ZipInfo normally converts backslashes into forward slashes.
        entry.filename = name
        output.writestr(entry, 'bad')
    with pytest.raises(ValueError, match='Unsafe'):
        extract_bag(archive, tmp_path / 'target', 'bag')
    assert not (tmp_path / 'target').exists()


def test_download_checksum_mismatch_never_extracts(monkeypatch, tmp_path):
    import mapping_demo
    monkeypatch.setattr(mapping_demo.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'bad download'))
    assert main(['fetch', '--data-dir', str(tmp_path)]) == 1
    assert not (tmp_path / 'stereo_outdoorA_bag').exists()


def test_dry_run_needs_no_ros_and_does_not_create_databases(tmp_path, capsys):
    database = tmp_path / 'new.db'
    assert main(['map', '--database', str(database), '--dry-run']) == 0
    assert not database.exists()
    assert 'mode:=mapping' in capsys.readouterr().out
    source = make_map(tmp_path / 'saved.db')
    target = tmp_path / 'snapshot.db'
    assert main(['localize', '--database', str(source), '--run-database', str(target), '--dry-run']) == 0
    assert not target.exists()
    assert main(['goal', '--node-id', '1', '--dry-run']) == 0
    assert '/rtabmap/rtabmap/set_goal' in capsys.readouterr().out


def test_release_profiles_are_pinned():
    assert '/0.23.13/stereo_outdoorA_bag.zip' in dataset_url('A')
    assert len(DATASET_SHA256['A']) == len(DATASET_SHA256['B']) == 64
    with pytest.raises(ValueError):
        dataset_url('other')


def test_autoplay_is_opt_in(tmp_path, capsys):
    bag = make_bag(tmp_path / 'bag')
    assert main(['play', str(bag), '--dry-run']) == 0
    assert '--start-paused' in capsys.readouterr().out
    assert main(['play', str(bag), '--autoplay', '--dry-run']) == 0
    assert '--start-paused' not in capsys.readouterr().out
