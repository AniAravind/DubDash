"""Stereo VO + mapping/localization for RTAB-Map's outdoor A/B demo bags."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode
from dubdash_replay.replay import validate_database, stereo_launch_arguments


def configure(context):
    mode = LaunchConfiguration('mode').perform(context)
    database = validate_database(LaunchConfiguration('database_path').perform(context), mode)
    database.parent.mkdir(parents=True, exist_ok=True)
    gui = LaunchConfiguration('gui').perform(context).lower() == 'true'
    # Humble's image_transport republish takes transport names as positional args.
    from launch_ros.actions import Node
    republishers = [Node(
        package='image_transport', executable='republish', name=f'demo_{side}_decode',
        namespace=f'/stereo_camera/{side}', arguments=['compressed', 'raw'],
        parameters=[{'use_sim_time': True}],
        remappings=[('in/compressed', 'image_raw_throttle/compressed'), ('out', 'image_raw')],
    ) for side in ('left', 'right')]
    rectifiers = []
    for side in ('left', 'right'):
        namespace = f'/stereo_camera/{side}'
        rectifiers.extend([
            ComposableNode(package='image_proc', plugin='image_proc::DebayerNode',
                           name=f'{side}_mono', namespace=namespace,
                           parameters=[{'use_sim_time': True}]),
            ComposableNode(package='image_proc', plugin='image_proc::RectifyNode',
                           name=f'{side}_rectify', namespace=namespace,
                           parameters=[{'use_sim_time': True}],
                           remappings=[('image', 'image_mono'),
                                       ('camera_info', 'camera_info_throttle')]),
        ])
    container = ComposableNodeContainer(
        name='demo_rectification', namespace='', package='rclcpp_components',
        executable='component_container', composable_node_descriptions=rectifiers,
        output='screen',
    )
    config = Path(get_package_share_directory('dubdash_replay')) / 'config/replay.rviz'
    source = Path(get_package_share_directory('rtabmap_launch')) / 'launch/rtabmap.launch.py'
    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(source)),
        launch_arguments=stereo_launch_arguments(database, mode, config, gui).items(),
    )
    return [*republishers, container, slam]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('database_path', description='New .db for mapping; existing map for localization'),
        DeclareLaunchArgument('mode', default_value='mapping', choices=['mapping', 'localization']),
        DeclareLaunchArgument('gui', default_value='true', choices=['true', 'false']),
        OpaqueFunction(function=configure),
    ])
