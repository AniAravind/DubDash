"""Adapt the installed Humble defaults without vendoring upstream configuration."""
from copy import deepcopy
import math


def build_config(defaults, profile):
    required = ('robot_radius', 'stop_margin', 'max_linear', 'max_angular',
                'min_obstacle_height', 'max_obstacle_height', 'min_depth_fraction')
    for key in required:
        value = profile[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be measured/configured and positive')
    if profile['min_depth_fraction'] > 1:
        raise ValueError('min_depth_fraction must be <= 1')
    if profile['min_obstacle_height'] >= profile['max_obstacle_height']:
        raise ValueError('Obstacle height interval is empty')
    if profile['max_linear'] > .2 or profile['max_angular'] > .5:
        raise ValueError('Do not exceed the existing command guard bench limits')
    cfg = deepcopy(defaults)
    radius, margin = profile['robot_radius'], profile['stop_margin']
    linear, angular = profile['max_linear'], profile['max_angular']
    for node in cfg.values():
        if isinstance(node, dict) and 'ros__parameters' in node:
            node['ros__parameters']['use_sim_time'] = False
    def params(name):
        return cfg[name]['ros__parameters']
    params('bt_navigator').update(robot_base_frame='base_link', odom_topic='/odom')
    control = params('controller_server')
    control['failure_tolerance'] = 0.0
    control['progress_checker'].update(required_movement_radius=.1, movement_time_allowance=10.0)
    control['FollowPath'].update(max_vel_x=linear, max_speed_xy=linear,
                               min_vel_x=0.0, max_vel_theta=angular,
                               trans_stopped_velocity=.02, acc_lim_x=.2,
                               decel_lim_x=-.2, acc_lim_theta=.5, decel_lim_theta=-.5)
    params('planner_server')['GridBased'].update(allow_unknown=False, use_astar=True)
    params('velocity_smoother').update(max_velocity=[linear, 0.0, angular],
        min_velocity=[0.0, 0.0, -angular], max_accel=[.2, 0.0, .5],
        max_decel=[-.2, 0.0, -.5], velocity_timeout=.25, odom_topic='/odom')
    params('behavior_server').update(behavior_plugins=['wait'])
    for kind in ('local', 'global'):
        cost = cfg[f'{kind}_costmap'][f'{kind}_costmap']['ros__parameters']
        cost.update(use_sim_time=False, robot_base_frame='base_link',
                    robot_radius=radius, track_unknown_space=True,
                    plugins=['static_layer', 'obstacle_layer', 'inflation_layer'])
        cost['static_layer'] = dict(plugin='nav2_costmap_2d::StaticLayer',
            map_topic='/rtabmap/map', map_subscribe_transient_local=True, subscribe_to_updates=True)
        cost['obstacle_layer'] = dict(plugin='nav2_costmap_2d::ObstacleLayer',
            enabled=True, observation_sources='stereo', stereo=dict(
                topic='/obstacles/points', data_type='PointCloud2', marking=True,
                clearing=False, obstacle_max_range=4.0, obstacle_min_range=0.0,
                min_obstacle_height=profile['min_obstacle_height'],
                max_obstacle_height=profile['max_obstacle_height'],
                expected_update_rate=.25, observation_persistence=0.0))
        cost['inflation_layer'] = dict(plugin='nav2_costmap_2d::InflationLayer',
            inflation_radius=radius+margin, cost_scaling_factor=3.0)
    stop_radius = radius + margin
    cfg['collision_monitor'] = {'ros__parameters': dict(
        use_sim_time=False, base_frame_id='base_link', odom_frame_id='odom',
        cmd_vel_in_topic='/navigation/smoothed', cmd_vel_out_topic='/cmd_vel_guard_input',
        transform_tolerance=.1, source_timeout=.25, base_shift_correction=True,
        stop_pub_timeout=1.0, polygons=['Stop'],
        Stop=dict(type='polygon', points=[stop_radius, stop_radius, stop_radius, -stop_radius,
            -stop_radius, -stop_radius, -stop_radius, stop_radius], action_type='stop',
            max_points=0, visualize=True, polygon_pub_topic='/navigation/stop_polygon'),
        observation_sources=['stereo'], stereo=dict(type='pointcloud',
            topic='/obstacles/points', min_height=profile['min_obstacle_height'],
            max_height=profile['max_obstacle_height'], enabled=True))}
    return cfg
