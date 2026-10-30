"""Navigation permission, configuration and saved-map protection without ROS."""
import sqlite3
import pytest
from dubdash.guard import CommandGuard
from dubdash.navigation_policy import NavigationHealth
from dubdash.navigation_config import build_config
from dubdash.map_database import localization_copy


def ready():
    policy = NavigationHealth()
    for name in policy.REQUIRED:
        policy.observe(name, 10., 10., 100.)
    return policy


def test_all_inputs_and_guard_enable_required():
    policy, guard = ready(), CommandGuard()
    assert not policy.reasons(10.1, 100.1)
    guard.receive_command(.1, -.3, 100.1)
    guard.receive_health(not policy.reasons(10.1, 100.1), 100.1)
    assert guard.output(100.1, False) == (0., 0.)
    assert guard.output(100.1, True) == (.1, -.3)
    policy.person(100.1)
    guard.receive_health(not policy.reasons(10.1, 100.1), 100.1)
    assert guard.output(100.1, True) == (0., 0.)


@pytest.mark.parametrize('name', NavigationHealth.REQUIRED)
def test_each_missing_or_invalid_input_blocks(name):
    policy = ready()
    policy.observe(name, 10.1, 10.1, 100.1, False)
    assert name in policy.reasons(10.1, 100.1)


def test_frozen_clock_source_replay_and_time_reversal_stop():
    policy = ready()
    assert 'depth' in policy.reasons(10., 100.3)
    assert 'depth' in policy.reasons(9., 100.1)
    assert 'depth' in policy.reasons(10.1, 99.)
    policy.observe('depth', 10., 10.1, 100.1)
    assert 'depth' in policy.reasons(10.1, 100.1)
    policy.observe('depth', 10., 10.1, 100.2)
    assert 'depth' in policy.reasons(10.1, 100.2)


@pytest.mark.parametrize('stamp', [0., 9., 11., float('nan'), float('inf')])
def test_old_future_and_invalid_capture_times_stop(stamp):
    policy = ready()
    policy.observe('depth', stamp, 10.1, 100.1)
    assert 'depth' in policy.reasons(10.1, 100.1)


def test_map_transform_and_person_gates():
    policy = ready()
    assert policy.reasons(10.1, 100.1, False, False) == ['transforms', 'map']
    policy.person(100.)
    for name in policy.REQUIRED:
        policy.observe(name, 11., 11., 101.)
    assert policy.reasons(11., 101.) == ['person detected']
    for name in policy.REQUIRED:
        policy.observe(name, 12.1, 12.1, 102.1)
    assert not policy.reasons(12.1, 102.1)


def defaults():
    result = {name: {'ros__parameters': {}} for name in
              ('bt_navigator', 'controller_server', 'planner_server', 'velocity_smoother', 'behavior_server')}
    result['controller_server']['ros__parameters'] = {'FollowPath': {}, 'progress_checker': {}}
    result['planner_server']['ros__parameters'] = {'GridBased': {}}
    for kind in ('local', 'global'):
        result[kind+'_costmap'] = {kind+'_costmap': {'ros__parameters': {}}}
    return result


def profile():
    return dict(robot_radius=.3, stop_margin=.3, max_linear=.15, max_angular=.4,
                min_obstacle_height=.05, max_obstacle_height=2., min_depth_fraction=.6)


def test_unknown_space_not_traversable_and_stereo_never_clears_blind_rays():
    cfg = build_config(defaults(), profile())
    assert not cfg['planner_server']['ros__parameters']['GridBased']['allow_unknown']
    for kind in ('local', 'global'):
        cost = cfg[kind+'_costmap'][kind+'_costmap']['ros__parameters']
        assert cost['track_unknown_space']
        assert cost['static_layer']['map_topic'] == '/rtabmap/map'
        assert not cost['obstacle_layer']['stereo']['clearing']
    monitor = cfg['collision_monitor']['ros__parameters']
    assert monitor['cmd_vel_out_topic'] == '/cmd_vel_guard_input'
    assert monitor['Stop']['max_points'] == 0
    assert cfg['velocity_smoother']['ros__parameters']['min_velocity'][0] == 0


@pytest.mark.parametrize('key,value', [('robot_radius', 0), ('stop_margin', -1),
    ('max_linear', .3), ('max_angular', float('nan')), ('min_depth_fraction', 1.1),
    ('min_obstacle_height', 3), ('robot_radius', True)])
def test_unmeasured_or_invalid_profile_rejected(key, value):
    settings = profile()
    settings[key] = value
    with pytest.raises(ValueError):
        build_config(defaults(), settings)


def test_saved_robot_map_is_preserved(tmp_path):
    source, target = tmp_path/'route.db', tmp_path/'run.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE Node (id INTEGER)')
        db.execute('INSERT INTO Node VALUES (1)')
    before = source.read_bytes()
    localization_copy(source, target)
    with sqlite3.connect(target) as db:
        db.execute('INSERT INTO Node VALUES (2)')
    assert source.read_bytes() == before
    with pytest.raises(FileExistsError):
        localization_copy(source, target)
    with pytest.raises(ValueError):
        localization_copy(source, source)
