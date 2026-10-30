"""Opt-in flat-ground prototype; requires measured geometry and full stereo coverage."""
import time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import qos_profile_sensor_data
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import Twist
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header
from tf2_ros import Buffer, TransformListener, TransformException
from dubdash.ground import ground_support
from dubdash.navigation_supervisor import transform_points, point_cloud_2_xyz, seconds


class GroundValidator(Node):
    def __init__(self):
        super().__init__('ground_validator')
        defaults = dict(radius=0.0, margin=0.0, ground_z=0.0, cell_size=.1,
                        height_tolerance=.03, min_points=3, max_slope=.1, horizon=2.0)
        self.settings = {key: self.declare_parameter(key, value).value for key, value in defaults.items()}
        ground_support([], **self.settings)  # Validate configuration before subscribing.
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.publisher = self.create_publisher(DiagnosticArray, '/ground/diagnostics', 1)
        self.velocity, self.command_time = (0., 0.), -1.
        self.create_subscription(Twist, '/navigation/smoothed', self.command, 1)
        self.create_subscription(PointCloud2, '/stereo/points2', self.cloud, qos_profile_sensor_data)

    def command(self, msg):
        self.velocity, self.command_time = (msg.linear.x, msg.angular.z), time.monotonic()

    def cloud(self, msg):
        okay, reason = False, 'Stale or unorganized stereo'
        try:
            age = self.get_clock().now().nanoseconds/1e9-seconds(msg.header.stamp)
            if 0 <= age <= .25 and msg.height > 1:
                transform = self.buffer.lookup_transform('base_link', msg.header.frame_id, Time.from_msg(msg.header.stamp))
                xyz = np.asarray(list(point_cloud_2_xyz(msg)), dtype=float).reshape(-1, 3)
                xyz = transform_points(xyz, transform.transform)
                velocity = self.velocity if 0 <= time.monotonic()-self.command_time <= .25 else (0., 0.)
                okay, reason = ground_support(xyz, **self.settings, linear=velocity[0], angular=velocity[1])
        except (ValueError, TypeError, AssertionError, TransformException) as error:
            reason = str(error)
        self.publisher.publish(DiagnosticArray(header=Header(stamp=msg.header.stamp, frame_id='base_link'),
            status=[DiagnosticStatus(name='ground_support', hardware_id='stereo-flat-floor-prototype',
                level=DiagnosticStatus.OK if okay else DiagnosticStatus.ERROR, message=reason)]))


def main(args=None):
    from dubdash.runtime import run
    run(GroundValidator, args)
