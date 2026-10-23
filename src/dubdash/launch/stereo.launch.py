from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    source = Path(get_package_share_directory("stereo_image_proc")) / "launch/stereo_image_proc.launch.py"
    return LaunchDescription([GroupAction([
        PushRosNamespace("stereo"),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(source)),
                                 launch_arguments={
                                     "approximate_sync": "false",
                                     "stereo_algorithm": "1",
                                     "left_namespace": "left",
                                     "right_namespace": "right",
                                 }.items()),
    ])])
