"""Stereo obstacle adapter and fail-closed navigation health supervisor.

The external ground validator covers drop-offs and the complete swept footprint;
a height crop alone cannot establish traversability.
"""
import json
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.duration import Duration
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from nav_msgs.msg import Odometry, OccupancyGrid
from geometry_msgs.msg import PoseWithCovarianceStamped
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from std_msgs.msg import Bool, String, Header
from vision_msgs.msg import Detection2DArray
from tf2_ros import Buffer, TransformListener, TransformException

from dubdash.navigation_policy import NavigationHealth


def seconds(stamp):
    return stamp.sec + stamp.nanosec / 1e9


def transform_points(points, transform):
    q = transform.rotation
    x, y, z, w = q.x, q.y, q.z, q.w
    norm = math.sqrt(x*x+y*y+z*z+w*w)
    if not math.isfinite(norm) or norm < 1e-9:
        raise ValueError('Invalid camera transform')
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    matrix = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                       [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                       [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    t = transform.translation
    if not all(math.isfinite(value) for value in (t.x, t.y, t.z)):
        raise ValueError('Invalid camera translation')
    return points @ matrix.T + [t.x, t.y, t.z]


class NavigationSupervisor(Node):
    def __init__(self):
        super().__init__('navigation_supervisor')
        self.policy = NavigationHealth()
        self.minimum = self.declare_parameter('min_obstacle_height', .05).value
        self.maximum = self.declare_parameter('max_obstacle_height', 2.0).value
        self.coverage = self.declare_parameter('min_depth_fraction', .6).value
        self.map_ok = False
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.health = self.create_publisher(Bool, '/perception/healthy', 1)
        self.status = self.create_publisher(String, '/navigation/status', 1)
        self.obstacles = self.create_publisher(PointCloud2, '/obstacles/points', 1)
        self.create_subscription(PointCloud2, '/stereo/points2', self.cloud, qos_profile_sensor_data)
        self.create_subscription(Detection2DArray, '/people', self.detections, 1)
        self.create_subscription(Odometry, '/odom', self.odometry, 1)
        self.create_subscription(PoseWithCovarianceStamped, '/rtabmap/localization_pose', self.localization, 1)
        self.create_subscription(DiagnosticArray, '/ground/diagnostics', self.ground, 1)
        self.create_subscription(OccupancyGrid, '/rtabmap/map', self.map,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(.05, self.tick)

    def observe(self, name, stamp, valid=True):
        self.policy.observe(name, seconds(stamp), self.get_clock().now().nanoseconds/1e9,
                            time.monotonic(), valid)

    def map(self, msg):
        self.map_ok = (msg.header.frame_id == 'map' and msg.info.resolution > 0
                       and len(msg.data) == msg.info.width*msg.info.height
                       and any(value == 0 for value in msg.data))

    def odometry(self, msg):
        p, q, v = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist
        values = [p.x, p.y, p.z, q.x, q.y, q.z, q.w,
                  v.linear.x, v.angular.z, *msg.pose.covariance, *msg.twist.covariance]
        self.observe('odometry', msg.header.stamp,
                     msg.header.frame_id == 'odom' and msg.child_frame_id == 'base_link'
                     and all(math.isfinite(v) for v in values)
                     and .99 <= q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w <= 1.01)

    def localization(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        cov = msg.pose.covariance
        self.observe('localization', msg.header.stamp,
            msg.header.frame_id == 'map'
            and all(math.isfinite(v) for v in [p.x, p.y, p.z, q.x, q.y, q.z, q.w, *cov])
            and .99 <= q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w <= 1.01
            and all(0 < cov[i] <= .25 for i in (0, 7, 35)))

    def ground(self, msg):
        checks = [s for s in msg.status if s.name == 'ground_support']
        self.observe('ground', msg.header.stamp,
                     len(checks) == 1 and checks[0].level == DiagnosticStatus.OK)

    def detections(self, msg):
        valid = bool(msg.header.frame_id)
        for detection in msg.detections:
            for result in detection.results:
                hypothesis = result.hypothesis
                if not math.isfinite(hypothesis.score) or not 0 <= hypothesis.score <= 1:
                    valid = False
                if hypothesis.class_id == 'person' and hypothesis.score >= .5:
                    # No monocular distance guesses: stop for any visible person.
                    self.policy.person(time.monotonic())
        self.observe('detections', msg.header.stamp, valid)

    def cloud(self, msg):
        try:
            # Validate age before expensive conversion. Failed inputs revoke health.
            self.policy.samples.pop('depth', None)
            age = self.get_clock().now().nanoseconds/1e9 - seconds(msg.header.stamp)
            if not 0 <= age <= self.policy.timeout or msg.height <= 1:
                return  # An unorganized cloud cannot provide pixel coverage.
            points = np.asarray(list(point_cloud_2_xyz(msg)), dtype=float).reshape(-1, 3)
            finite = np.isfinite(points).all(axis=1)
            fraction = np.count_nonzero(finite) / max(1, msg.width*msg.height)
            transform = self.buffer.lookup_transform('base_link', msg.header.frame_id,
                                                     Time.from_msg(msg.header.stamp))
            points = transform_points(points[finite], transform.transform)
            mask = ((points[:, 2] >= self.minimum) & (points[:, 2] <= self.maximum))
            cloud = point_cloud2.create_cloud_xyz32(
                Header(stamp=msg.header.stamp, frame_id='base_link'), points[mask].tolist())
            self.obstacles.publish(cloud)
            self.observe('depth', msg.header.stamp, fraction >= self.coverage)
        except (ValueError, TypeError, AssertionError, TransformException) as error:
            self.get_logger().warning(f'Stereo unavailable: {error}')

    def tick(self):
        now = self.get_clock().now()
        # Ask for current transforms, not merely any transform in the cache.
        transforms_ok = all(self.buffer.can_transform(target, source, now-Duration(seconds=.1))
                            for target, source in [('map', 'base_link'), ('odom', 'base_link')])
        reasons = self.policy.reasons(now.nanoseconds/1e9, time.monotonic(), transforms_ok, self.map_ok)
        self.health.publish(Bool(data=not reasons))
        self.status.publish(String(data=json.dumps({'healthy': not reasons, 'blocked_by': reasons})))


def point_cloud_2_xyz(msg):
    # Humble read_points returns tuples; newer sensor_msgs_py may return records.
    for point in point_cloud2.read_points(msg, field_names=('x', 'y', 'z'), skip_nans=False):
        yield (point[0], point[1], point[2])


def main(args=None):
    rclpy.init(args=args)
    node = NavigationSupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.health.publish(Bool(data=False))
        node.destroy_node()
        rclpy.shutdown()
