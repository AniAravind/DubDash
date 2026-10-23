"""Show one annotated live camera stream. Launch twice for a stereo pair."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("model", description="Absolute path to local YOLO weights/engine"),
        DeclareLaunchArgument("image", default_value="/stereo/left/image_raw"),
        DeclareLaunchArgument("camera", default_value="left",
                              description="Unique ROS namespace for this camera"),
        DeclareLaunchArgument("confidence", default_value="0.5"),
        DeclareLaunchArgument("detect_all", default_value="true"),
        Node(package="dubdash", executable="person_detector",
             namespace=LaunchConfiguration("camera"), output="screen",
             parameters=[{
                 "model": LaunchConfiguration("model"),
                 "confidence": ParameterValue(LaunchConfiguration("confidence"), value_type=float),
                 "detect_all": ParameterValue(LaunchConfiguration("detect_all"), value_type=bool),
             }], remappings=[("image", LaunchConfiguration("image")),
                             ("people", "detections")]),
        Node(package="rqt_image_view", executable="rqt_image_view",
             namespace=LaunchConfiguration("camera"), name="detection_view",
             arguments=[["/", LaunchConfiguration("camera"), "/image_annotated"]], output="screen"),
    ])
