"""Headless Orin runtime; camera/TF/ground-validator/motor drivers are external."""
from datetime import datetime, timezone
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from dubdash.map_database import localization_copy


def configure(context):
    def arg(name):
        return LaunchConfiguration(name).perform(context)
    share = Path(get_package_share_directory('dubdash'))
    source = Path(arg('database')).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    database = localization_copy(source, source.with_name(f'{source.stem}-run-{timestamp}.db'))
    def include(name, arguments=None):
        return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share/'launch'/name)),
                                        launch_arguments=(arguments or {}).items())
    mapping = Path(get_package_share_directory('rtabmap_launch'))/'launch/rtabmap.launch.py'
    return [
        include('stereo.launch.py'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(mapping)), launch_arguments={
            'stereo': 'true', 'depth': 'false', 'frame_id': 'base_link',
            'approx_sync': 'false', 'use_sim_time': 'false', 'visual_odometry': 'true',
            'odom_topic': '/odom', 'localization': 'true', 'database_path': str(database),
            'left_image_topic': '/stereo/left/image_rect',
            'right_image_topic': '/stereo/right/image_rect',
            'left_camera_info_topic': '/stereo/left/camera_info',
            'right_camera_info_topic': '/stereo/right/camera_info',
            'rviz': 'false', 'rtabmap_viz': 'false', 'args': '--Grid/Sensor 1',
        }.items()),
        Node(package='dubdash', executable='person_detector', parameters=[{
            'endpoint': arg('inference_endpoint'), 'allow_mock_inference': False,
            'confidence': .5, 'detect_all': False}],
            remappings=[('image', '/stereo/left/image_rect')]),
        include('navigation.launch.py', {'robot_config': arg('robot_config'),
                                        'enable_motion': arg('enable_motion')}),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('database', description='Saved calibrated robot RTAB-Map .db, not replay demo'),
        DeclareLaunchArgument('robot_config', description='Measured robot profile YAML'),
        DeclareLaunchArgument('inference_endpoint', default_value='http://127.0.0.1:8090'),
        DeclareLaunchArgument('enable_motion', default_value='false', choices=['true', 'false']),
        OpaqueFunction(function=configure),
    ])
