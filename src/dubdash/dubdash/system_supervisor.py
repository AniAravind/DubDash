"""Require live, qualified battery state and a stamped physical-stop adapter."""
import math
import time
import json
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import BatteryState
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from std_msgs.msg import Bool, String
from dubdash.system_health import SystemHealth


class SystemSupervisor(Node):
    def __init__(self):
        super().__init__('system_supervisor')
        self.policy = SystemHealth(self.declare_parameter('battery_min_fraction', 0.0).value)
        self.publisher = self.create_publisher(Bool, '/system/healthy', 1)
        self.status = self.create_publisher(String, '/system/status', 1)
        self.create_subscription(BatteryState, '/battery/state', self.battery, qos_profile_sensor_data)
        self.create_subscription(DiagnosticArray, '/emergency_stop/diagnostics', self.stop, 1)
        self.create_timer(.05, self.tick)

    def observe(self, name, msg, okay):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec/1e9
        self.policy.observe(name, stamp, self.get_clock().now().nanoseconds/1e9, time.monotonic(), okay)

    def battery(self, msg):
        self.observe('battery', msg, msg.present and math.isfinite(msg.percentage)
            and self.policy.minimum <= msg.percentage <= 1.0
            and msg.power_supply_health == BatteryState.POWER_SUPPLY_HEALTH_GOOD)

    def stop(self, msg):
        checks = [s for s in msg.status if s.name == 'emergency_stop']
        self.observe('emergency_stop', msg, len(checks) == 1 and checks[0].level == DiagnosticStatus.OK)

    def tick(self):
        reasons = self.policy.reasons(self.get_clock().now().nanoseconds/1e9, time.monotonic())
        self.publisher.publish(Bool(data=not reasons))
        self.status.publish(String(data=json.dumps({'healthy': not reasons, 'blocked_by': reasons,
            'last_rejected': self.policy.last_rejected})))


def main(args=None):
    from dubdash.runtime import run
    run(SystemSupervisor, args, lambda node: node.publisher.publish(Bool(data=False)))
