"""Actual Humble Nav2 + mission/system/guard nodes driving a synthetic unicycle.

Runs only inside the isolated laptop-test container: no devices or host mounts.
Synthetic sensors do not qualify real camera, ground, localization or motors.
"""
import json
import math
import time
import threading
import numpy as np
import pytest
pytest.importorskip('rclpy')
import rclpy
import yaml
from rclpy.qos import QoSProfile, DurabilityPolicy
from geometry_msgs.msg import Twist, TransformStamped, PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from sensor_msgs.msg import PointCloud2, BatteryState
from sensor_msgs_py import point_cloud2
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from std_msgs.msg import Header, String, Bool
from vision_msgs.msg import Detection2DArray
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
from test_ros_pipeline import ros, processes


def test_named_route_turns_arrives_cancels_and_stops_on_faults(ros, processes, tmp_path, request):
    probe, executor, nodes, wait = ros
    profile = dict(hardware_verified=True, robot_radius=.12, stop_margin=.1,
        max_linear=.2, max_angular=.5, min_obstacle_height=.05,
        max_obstacle_height=2., min_depth_fraction=.6, battery_min_fraction=.25)
    settings = tmp_path/'robot.yaml'
    settings.write_text(yaml.safe_dump(profile))
    catalog = tmp_path/'places.json'
    catalog.write_text(json.dumps(dict(frame_id='map', destinations={
        'pickup': dict(x=.7, y=.35, yaw=0.), 'dropoff': dict(x=1.1, y=.35, yaw=0.),
        'far': dict(x=2., y=.35, yaw=0.), 'unreachable': dict(x=4., y=0., yaw=0.)})))
    processes('ros2', 'launch', 'dubdash', 'navigation.launch.py',
        f'robot_config:={settings}', f'destinations:={catalog}',
        f'mission_ledger:={tmp_path / "missions.sqlite"}', 'enable_motion:=true')
    pubs = {name: probe.create_publisher(kind, topic, qos) for name, kind, topic, qos in [
        ('map', OccupancyGrid, '/rtabmap/map', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)),
        ('odom', Odometry, '/odom', 10), ('localization', PoseWithCovarianceStamped, '/rtabmap/localization_pose', 10),
        ('cloud', PointCloud2, '/stereo/points2', 10), ('people', Detection2DArray, '/people', 10),
        ('ground', DiagnosticArray, '/ground/diagnostics', 10), ('battery', BatteryState, '/battery/state', 10),
        ('stop', DiagnosticArray, '/emergency_stop/diagnostics', 10), ('command', String, '/missions/command', 10)]}
    state = dict(x=0., y=0., yaw=0., linear=0., angular=0., last=time.monotonic(),
                 ground=True, battery=.8, stopped=False, obstacle=False)
    velocity, status, readiness, diagnostics = [], [], {}, {}
    def moved(msg):
        state['linear'], state['angular'] = msg.linear.x, msg.angular.z
        velocity.append((time.monotonic(), msg.linear.x, msg.angular.z))
    probe.create_subscription(Twist, '/cmd_vel', moved, 10)
    probe.create_subscription(String, '/missions/status', lambda m: status.append(json.loads(m.data)),
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    for name in ('system', 'perception'):
        probe.create_subscription(Bool, f'/{name}/healthy', lambda m, key=name: readiness.update({key: m.data}), 10)
    for name in ('system', 'navigation'):
        probe.create_subscription(String, f'/{name}/status', lambda m, key=name: diagnostics.update({key: json.loads(m.data)}), 10)
    tf = TransformBroadcaster(probe)
    static = StaticTransformBroadcaster(probe)
    transform = TransformStamped()
    transform.header.frame_id, transform.child_frame_id = 'map', 'odom'
    transform.transform.rotation.w = 1.
    static.sendTransform(transform)
    grid = OccupancyGrid(header=Header(frame_id='map'))
    grid.info.resolution, grid.info.width, grid.info.height = .05, 120, 120
    grid.info.origin.position.x = grid.info.origin.position.y = -3.
    grid.info.origin.orientation.w = 1.
    cells = np.zeros((120, 120), dtype=np.int8)
    cells[[0, -1], :] = 100
    cells[:, [0, -1]] = 100
    grid.data = cells.ravel().tolist()
    pubs['map'].publish(grid)  # A static map is latched, not flooded at sensor rate.

    def sensors():
        now = time.monotonic()
        dt, state['last'] = min(now-state['last'], .1), now
        state['x'] += state['linear']*math.cos(state['yaw'])*dt
        state['y'] += state['linear']*math.sin(state['yaw'])*dt
        state['yaw'] += state['angular']*dt
        stamp = probe.get_clock().now().to_msg()
        odom = Odometry(header=Header(stamp=stamp, frame_id='odom'), child_frame_id='base_link')
        odom.pose.pose.position.x, odom.pose.pose.position.y = state['x'], state['y']
        odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = math.sin(state['yaw']/2), math.cos(state['yaw']/2)
        odom.twist.twist.linear.x, odom.twist.twist.angular.z = state['linear'], state['angular']
        pubs['odom'].publish(odom)
        transform = TransformStamped(header=odom.header, child_frame_id='base_link')
        transform.transform.translation.x, transform.transform.translation.y = state['x'], state['y']
        transform.transform.rotation = odom.pose.pose.orientation
        tf.sendTransform(transform)
        pose = PoseWithCovarianceStamped(header=Header(stamp=stamp, frame_id='map'), pose=odom.pose)
        for index in (0, 7, 35):
            pose.pose.covariance[index] = .01
        pubs['localization'].publish(pose)
        header = Header(stamp=stamp, frame_id='base_link')
        distance = .1 if state['obstacle'] else 2.5
        cloud = point_cloud2.create_cloud_xyz32(header,
            [[distance, -.02, .2], [distance, 0., .2], [distance, .02, .2], [distance, .04, .2]])
        cloud.width, cloud.height, cloud.row_step = 2, 2, cloud.point_step*2
        pubs['cloud'].publish(cloud)
        pubs['people'].publish(Detection2DArray(header=header))
        if state['ground']:
            pubs['ground'].publish(DiagnosticArray(header=header,
                status=[DiagnosticStatus(name='ground_support', level=DiagnosticStatus.OK)]))
        pubs['stop'].publish(DiagnosticArray(header=header, status=[DiagnosticStatus(name='emergency_stop',
            level=DiagnosticStatus.ERROR if state['stopped'] else DiagnosticStatus.OK)]))
        pubs['battery'].publish(BatteryState(header=header, percentage=state['battery'], present=True,
            power_supply_health=BatteryState.POWER_SUPPLY_HEALTH_GOOD))

    # Sensor acquisition must continue while the operator waits for acknowledgements
    # or evaluates results. It must not depend on the test's polling callbacks.
    stop_sources = threading.Event()
    source_errors = []
    def acquisition():
        try:
            while not stop_sources.is_set():
                sensors()
                stop_sources.wait(.05)
        except Exception as error:
            source_errors.append(str(error))
    source_thread = threading.Thread(target=acquisition, daemon=True)
    source_thread.start()
    def cleanup_sources():
        stop_sources.set()
        source_thread.join(timeout=3)
        assert not source_thread.is_alive(), 'Synthetic sensor publisher did not stop'
    request.addfinalizer(cleanup_sources)
    def tick():
        assert not source_errors, source_errors

    wait(lambda: readiness.get('system') and readiness.get('perception') and status and status[-1].get('ready'), tick, timeout=40)
    def send(request_id, operation='start', route=None):
        payload = json.dumps(dict(request_id=request_id, operation=operation, route=route or []))
        def step():
            tick()
            pubs['command'].publish(String(data=payload))
        wait(lambda: status and (status[-1].get('last_reply') or {}).get('request_id') == request_id, step)
        assert status[-1]['last_reply']['accepted'], status[-1]

    send('route-1', route=['pickup', 'dropoff'])
    wait(lambda: status[-1]['state'] in ('succeeded', 'failed', 'fault', 'canceled'), tick, timeout=60)
    assert status[-1]['state'] == 'succeeded', json.dumps(dict(mission=status[-1], diagnostics=diagnostics))
    assert status[-1]['completed_stops'] == 2
    assert math.hypot(state['x']-1.1, state['y']-.35) < .3
    assert any(abs(w) > .05 for _, _, w in velocity)
    assert any(v > .05 for _, v, _ in velocity)
    send('route-1', route=['pickup', 'dropoff'])  # Retry must not start another trip.
    assert status[-1]['state'] == 'succeeded'
    send('cancel-trip', route=['far'])
    wait(lambda: status[-1]['state'] == 'running', tick)
    send('cancel-1', operation='cancel')
    wait(lambda: status[-1]['state'] == 'canceled' and velocity[-1][1:] == (0., 0.), tick)
    send('low-battery-trip', route=['far'])
    wait(lambda: status[-1]['state'] == 'running', tick)
    state['battery'] = .1
    wait(lambda: status[-1]['state'] == 'canceled' and velocity[-1][1:] == (0., 0.), tick)
    state['battery'] = .8
    wait(lambda: readiness['system'], tick)
    send('ground-trip', route=['far'])
    wait(lambda: status[-1]['state'] == 'running', tick)
    state['ground'] = False
    wait(lambda: status[-1]['state'] == 'canceled' and velocity[-1][1:] == (0., 0.), tick)
    state['ground'] = True
    wait(lambda: readiness['perception'], tick)
    assert status[-1]['state'] == 'canceled'  # No automatic restart after recovery.
    send('stop-trip', route=['far'])
    wait(lambda: status[-1]['state'] == 'running', tick)
    state['stopped'] = True
    wait(lambda: status[-1]['state'] == 'canceled' and velocity[-1][1:] == (0., 0.), tick)
    state['stopped'] = False
    wait(lambda: readiness['system'], tick)
    send('unreachable-trip', route=['unreachable'])
    wait(lambda: status[-1]['state'] in ('failed', 'fault', 'canceled'), tick)
    assert status[-1]['state'] == 'failed', status[-1]
    wait(lambda: velocity[-1][1:] == (0., 0.), tick)
    send('obstacle-trip', route=['far'])
    wait(lambda: status[-1]['state'] == 'running' and velocity[-1][1] > .01, tick)
    state['obstacle'] = True
    stopped_at = time.monotonic()
    wait(lambda: velocity[-1][1:] == (0., 0.), tick)
    assert time.monotonic()-stopped_at < 1.0
    send('cancel-obstacle', operation='cancel')
    wait(lambda: status[-1]['state'] in ('canceled', 'failed') and velocity[-1][1:] == (0., 0.), tick)
