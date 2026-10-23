from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from pathlib import Path


def generate_launch_description():
    source = Path(get_package_share_directory("rtabmap_launch")) / "launch/rtabmap.launch.py"
    return LaunchDescription([IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(source)), launch_arguments={
            "stereo": "true", "frame_id": "base_link", "approx_sync": "false",
            "left_image_topic": "/stereo/left/image_rect",
            "right_image_topic": "/stereo/right/image_rect",
            "left_camera_info_topic": "/stereo/left/camera_info",
            "right_camera_info_topic": "/stereo/right/camera_info",
            "visual_odometry": "true", "rviz": "false",
        }.items(),
    )])
