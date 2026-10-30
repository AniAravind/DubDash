"""Consistent ROS shutdown without publishing through an invalid SIGINT context."""
import rclpy
from rclpy.executors import ExternalShutdownException


def run(factory, args=None, before_shutdown=None):
    rclpy.init(args=args)
    node = None
    try:
        node = factory()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            if rclpy.ok() and before_shutdown is not None:
                before_shutdown(node)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
