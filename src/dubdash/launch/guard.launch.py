from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([Node(
        package="dubdash", executable="command_guard", output="screen",
        parameters=[{"enabled": False, "timeout": 0.25,
                     "max_linear": 0.2, "max_angular": 0.5}],
    )])
