"""Final command gate. Requires an external, validated perception supervisor."""
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool
from dubdash.guard import CommandGuard


class GuardNode(Node):
    def __init__(self):
        super().__init__("command_guard")
        self.declare_parameter("enabled", False)
        self.policy = CommandGuard(**{
            name: self.declare_parameter(name, default).value
            for name, default in [("timeout", 0.25), ("max_linear", 0.2),
                                  ("max_angular", 0.5)]})
        self.publisher = self.create_publisher(Twist, "cmd_vel", 10)
        self.create_subscription(Twist, "cmd_vel_guard_input", self.command, 10)
        self.create_subscription(Bool, "perception/healthy", self.health, 10)
        self.create_timer(0.02, self.tick)

    def command(self, msg):
        self.policy.receive_command(msg.linear.x, msg.angular.z, time.monotonic())

    def health(self, msg):
        self.policy.receive_health(msg.data, time.monotonic())

    def tick(self):
        msg = Twist()
        msg.linear.x, msg.angular.z = self.policy.output(
            time.monotonic(), self.get_parameter("enabled").value)
        self.publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = GuardNode()
    try:
        rclpy.spin(node)
    finally:
        node.publisher.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()
