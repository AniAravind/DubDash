import json
import math
import numpy as np
import pytest
from dubdash.missions import destinations, command, MissionLedger
from dubdash.system_health import SystemHealth
from dubdash.ground import ground_support


def places():
    return destinations({'frame_id': 'map', 'destinations': {'pickup': {'x': 1., 'y': 2., 'yaw': 0.}}})


@pytest.mark.parametrize('pose', [{'x': math.nan, 'y': 0., 'yaw': 0.},
    {'x': True, 'y': 0., 'yaw': 0.}, {'x': 0., 'y': 0., 'yaw': 180.}, {'x': 0.}])
def test_invalid_destinations(pose):
    with pytest.raises(ValueError):
        destinations({'frame_id': 'map', 'destinations': {'pickup': pose}})


def test_unknown_route_and_oversized_routes_rejected():
    for route in ([], ['unknown'], ['pickup']*33):
        with pytest.raises(ValueError):
            command({'request_id': 'job', 'operation': 'start', 'route': route}, places())
    with pytest.raises(ValueError):
        command({'request_id': 'job', 'operation': 'cancel', 'route': {}}, places())


def test_request_id_survives_restart_without_dispatching_again(tmp_path):
    request = command({'request_id': 'job-1', 'operation': 'start', 'route': ['pickup']}, places())
    ledger = MissionLedger(tmp_path/'mission.sqlite')
    assert ledger.previous(request) is None
    reply = dict(request_id='job-1', accepted=True)
    ledger.record(request, reply)
    ledger.close()
    restarted = MissionLedger(tmp_path/'mission.sqlite')
    assert restarted.previous(request) == reply
    with pytest.raises(ValueError):
        restarted.previous(dict(request, route=['pickup', 'pickup']))
    restarted.close()


def test_system_health_fails_on_low_battery_stop_stale_and_frozen_clock():
    policy = SystemHealth(.25)
    for name in ('battery', 'emergency_stop'):
        policy.observe(name, 10., 10., 100., True)
    assert policy.reasons(10.1, 100.1) == []
    assert policy.reasons(10., 100.3) == ['emergency_stop']
    policy.observe('battery', 10.1, 10.1, 100.1, False)
    assert 'battery' in policy.reasons(10.1, 100.1)
    policy.observe('emergency_stop', 10., 10.1, 100.1, True)
    assert 'emergency_stop' in policy.reasons(10.1, 100.1)


@pytest.mark.parametrize('minimum', [None, 0., 1., True, math.nan])
def test_battery_threshold_must_be_configured(minimum):
    with pytest.raises(ValueError):
        SystemHealth(minimum)


def floor():
    axis = np.arange(-20, 21)*.1
    return np.array([[x, y, -.2] for x in axis for y in axis])


def settings():
    return dict(radius=.2, margin=.1, ground_z=-.2, cell_size=.1,
                height_tolerance=.03, min_points=1, max_slope=.1, horizon=2.)


def test_observed_flat_floor_and_turning_swept_area():
    assert ground_support(floor(), **settings(), linear=.15, angular=.4)[0]
    assert not ground_support(floor()[floor()[:, 0] > 0], **settings())[0]


def test_dropoff_nan_depth_and_raised_ground_are_not_support():
    points = floor()
    points[np.abs(points[:, 0]) < .1, 2] = np.nan
    assert not ground_support(points, **settings())[0]
    points = floor()
    points[np.abs(points[:, 0]) < .1, 2] -= .2
    assert not ground_support(points, **settings())[0]
    assert not ground_support(floor()+[0, 0, .2], **settings())[0]


def test_ground_looks_ahead_instead_of_only_under_robot():
    points = floor()
    points = points[points[:, 0] <= .4]
    assert ground_support(points, **settings())[0]
    assert not ground_support(points, **settings(), linear=.2)[0]


def test_unmeasured_ground_cannot_be_enabled():
    with pytest.raises(ValueError):
        ground_support(floor(), **dict(settings(), ground_z=None))


def test_preflight_rejects_empty_catalog_and_preserves_map(tmp_path):
    import sqlite3
    import yaml
    from robot_preflight import files
    profile = tmp_path/'profile.yaml'
    profile.write_text(yaml.safe_dump(dict(robot_radius=.3, stop_margin=.2,
        max_linear=.15, max_angular=.4, min_obstacle_height=.05,
        max_obstacle_height=2., min_depth_fraction=.6, battery_min_fraction=.25)))
    catalog, database = tmp_path/'places.json', tmp_path/'route.db'
    catalog.write_text(json.dumps(dict(frame_id='map', destinations={})))
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE Node(id INTEGER)')
        db.execute('INSERT INTO Node VALUES (1)')
    before = database.read_bytes()
    with pytest.raises(ValueError, match='empty'):
        files(profile, catalog, database)
    catalog.write_text(json.dumps(dict(frame_id='map', destinations=places())))
    assert files(profile, catalog, database)[1] == 1
    assert database.read_bytes() == before
