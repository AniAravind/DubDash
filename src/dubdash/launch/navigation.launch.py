"""Humble navigation using an existing live RTAB-Map localization session."""
from pathlib import Path
import tempfile
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnShutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from dubdash.navigation_config import build_config


def configure(context):
    share = Path(get_package_share_directory('dubdash'))
    profile = yaml.safe_load(Path(LaunchConfiguration('robot_config').perform(context)).read_text())
    enabled = LaunchConfiguration('enable_motion').perform(context) == 'true'
    if enabled and profile.get('hardware_verified') is not True:
        raise ValueError('Complete hardware acceptance and set hardware_verified before enabling motion')
    upstream = Path(get_package_share_directory('nav2_bringup')) / 'params/nav2_params.yaml'
    config = build_config(yaml.safe_load(upstream.read_text()), profile)
    from dubdash.system_health import SystemHealth
    SystemHealth(profile.get('battery_min_fraction'))
    config['bt_navigator']['ros__parameters']['default_nav_to_pose_bt_xml'] = str(share/'config/navigate.xml')
    config['bt_navigator']['ros__parameters']['default_nav_through_poses_bt_xml'] = str(share/'config/navigate_through.xml')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', prefix='dubdash-nav-', delete=False) as output:
        yaml.safe_dump(config, output)
        filename = output.name
    # Explicit remappings keep ALL Nav2 producers away from motor /cmd_vel.
    specifications = [
        ('nav2_controller', 'controller_server', [('cmd_vel', '/navigation/raw')]),
        ('nav2_planner', 'planner_server', []),
        ('nav2_smoother', 'smoother_server', []),
        ('nav2_behaviors', 'behavior_server', [('cmd_vel', '/navigation/raw')]),
        ('nav2_bt_navigator', 'bt_navigator', []),
        ('nav2_velocity_smoother', 'velocity_smoother',
         [('cmd_vel', '/navigation/raw'), ('cmd_vel_smoothed', '/navigation/smoothed')]),
        ('nav2_collision_monitor', 'collision_monitor', []),
    ]
    nodes = [Node(package=package, executable=name, name=name, parameters=[filename],
                  remappings=remaps, output='screen') for package, name, remaps in specifications]
    nodes += [
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_navigation', parameters=[{'use_sim_time': False,
             'autostart': True, 'node_names': [spec[1] for spec in specifications]}]),
        Node(package='dubdash', executable='navigation_supervisor', parameters=[{
             key: profile[key] for key in ('min_obstacle_height', 'max_obstacle_height', 'min_depth_fraction')}]),
        Node(package='dubdash', executable='command_guard', parameters=[{'enabled': enabled,
             'timeout': .25, 'max_linear': profile['max_linear'], 'max_angular': profile['max_angular'],
             'require_system': True, 'require_missions': True}]),
        Node(package='dubdash', executable='system_supervisor', parameters=[{
             'battery_min_fraction': float(profile['battery_min_fraction'])}]),
        Node(package='dubdash', executable='mission_manager', parameters=[{
             'destinations': LaunchConfiguration('destinations').perform(context),
             'ledger': LaunchConfiguration('mission_ledger').perform(context)}]),
        RegisterEventHandler(OnShutdown(on_shutdown=[OpaqueFunction(
            function=lambda context: Path(filename).unlink(missing_ok=True))])),
    ]
    ground = profile.get('ground_validation', {})
    if ground.get('enabled', False):
        required = ('ground_z', 'cell_size', 'height_tolerance', 'min_points', 'max_slope', 'horizon')
        if not all(name in ground for name in required):
            raise ValueError('Provide all measured ground-validation parameters')
        nodes.append(Node(package='dubdash', executable='ground_validator', parameters=[{
            **{key: ground[key] for key in required},
            'radius': float(profile['robot_radius']), 'margin': float(profile['stop_margin'])}]))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot_config', description='Absolute path to measured robot YAML'),
        DeclareLaunchArgument('enable_motion', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('destinations', default_value=str(
            Path(get_package_share_directory('dubdash'))/'config/destinations.example.json')),
        DeclareLaunchArgument('mission_ledger', description='Persistent writable mission SQLite file'),
        OpaqueFunction(function=configure),
    ])
