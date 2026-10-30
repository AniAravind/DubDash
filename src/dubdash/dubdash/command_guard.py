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
        self.permissions = {name: None for name in ('system', 'missions')
                            if self.declare_parameter('require_'+name, False).value}
        self.policy = CommandGuard(**{
            name: self.declare_parameter(name, default).value
            for name, default in [("timeout", 0.25), ("max_linear", 0.2),
                                  ("max_angular", 0.5)]})
        self.publisher = self.create_publisher(Twist, "cmd_vel", 10)
        self.create_subscription(Twist, "cmd_vel_guard_input", self.command, 10)
        self.create_subscription(Bool, "perception/healthy", self.health, 10)
        for name in self.permissions:
            topic = '/system/healthy' if name == 'system' else '/missions/permit'
            self.create_subscription(Bool, topic, lambda msg, key=name: self.permission(key, msg), 1)
        self.create_timer(0.02, self.tick)

    def command(self, msg):
        self.policy.receive_command(msg.linear.x, msg.angular.z, time.monotonic())

    def health(self, msg):
        self.policy.receive_health(msg.data, time.monotonic())

    def permission(self, name, msg):
        self.permissions[name] = time.monotonic() if msg.data else None
        if not msg.data:
            self.policy.command_time = None

    def tick(self):
        msg = Twist()
        now = time.monotonic()
        permitted = all(t is not None and 0 <= now-t <= self.policy.timeout
                        for t in self.permissions.values())
        msg.linear.x, msg.angular.z = self.policy.output(
            now, self.get_parameter("enabled").value and permitted)
        self.publisher.publish(msg)


def main(args=None):
    from dubdash.runtime import run
    run(GuardNode, args, lambda node: node.publisher.publish(Twist()))
