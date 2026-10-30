"""Real Humble nodes, DDS, rosbag playback and HTTP; no physical devices."""
import importlib.util
import os
import signal
import subprocess
import time

import pytest

if importlib.util.find_spec("rclpy") is None:
    if os.environ.get("DUBDASH_REQUIRE_ROS") == "1":
        raise RuntimeError("ROS integration is required but rclpy is unavailable")
    pytest.skip("Run scripts/test_laptop.sh for ROS integration", allow_module_level=True)

import cv2
import numpy as np
import rclpy
import rosbag2_py
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from rclpy.serialization import serialize_message
from sensor_msgs.msg import CameraInfo, Image, PointCloud2
from std_msgs.msg import Bool
from stereo_msgs.msg import DisparityImage
from vision_msgs.msg import Detection2DArray

from dubdash.command_guard import GuardNode


def test_navigation_cloud_adapter_and_person_stop(ros):
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
    from geometry_msgs.msg import TransformStamped, PoseWithCovarianceStamped
    from nav_msgs.msg import Odometry, OccupancyGrid
    from sensor_msgs_py import point_cloud2
    from std_msgs.msg import Header
    from tf2_ros import StaticTransformBroadcaster
    from vision_msgs.msg import Detection2D, ObjectHypothesisWithPose
    from dubdash.navigation_supervisor import NavigationSupervisor

    probe, executor, nodes, wait = ros
    supervisor = NavigationSupervisor()
    nodes.append(supervisor)
    executor.add_node(supervisor)
    health, clouds = [], []
    probe.create_subscription(Bool, '/perception/healthy', health.append, 10)
    probe.create_subscription(PointCloud2, '/obstacles/points', clouds.append, 10)
    broadcaster = StaticTransformBroadcaster(probe)
    transforms = []
    for parent, child in [('map', 'odom'), ('odom', 'base_link')]:
        transform = TransformStamped()
        transform.header.frame_id, transform.child_frame_id = parent, child
        transform.header.stamp = probe.get_clock().now().to_msg()
        transform.transform.rotation.w = 1.0
        transforms.append(transform)
    broadcaster.sendTransform(transforms)
    occupancy = OccupancyGrid()
    occupancy.header.frame_id = 'map'
    occupancy.info.width = occupancy.info.height = 2
    occupancy.info.resolution = .1
    occupancy.data = [0]*4
    supervisor.map(occupancy)

    def publish(person=False, ground=True):
        stamp = probe.get_clock().now().to_msg()
        header = Header(stamp=stamp, frame_id='base_link')
        cloud = point_cloud2.create_cloud_xyz32(header,
            [[1., 0., .2], [1., .1, .2], [1., -.1, .2], [1., 0., 0.]])
        cloud.height, cloud.width = 2, 2
        cloud.row_step = 2*cloud.point_step
        supervisor.cloud(cloud)
        detection = Detection2DArray(header=header)
        if person:
            box, hypothesis = Detection2D(), ObjectHypothesisWithPose()
            hypothesis.hypothesis.class_id, hypothesis.hypothesis.score = 'person', .9
            box.results.append(hypothesis)
            detection.detections.append(box)
        supervisor.detections(detection)
        if ground:
            supervisor.ground(DiagnosticArray(header=header,
                status=[DiagnosticStatus(name='ground_support', level=DiagnosticStatus.OK)]))
        odom = Odometry(header=Header(stamp=stamp, frame_id='odom'), child_frame_id='base_link')
        odom.pose.pose.orientation.w = 1.
        supervisor.odometry(odom)
        pose = PoseWithCovarianceStamped(header=Header(stamp=stamp, frame_id='map'))
        pose.pose.pose.orientation.w = 1.
        for index in (0, 7, 35):
            pose.pose.covariance[index] = .01
        supervisor.localization(pose)

    wait(lambda: health and health[-1].data and clouds, publish)
    assert clouds[-1].header.frame_id == 'base_link'
    assert clouds[-1].width == 3  # Ground-height point removed, no clearing ray.
    health.clear()
    wait(lambda: health and not health[-1].data, lambda: publish(ground=False))
    wait(lambda: health[-1].data, publish)
    health.clear()
    wait(lambda: health and not health[-1].data, lambda: publish(person=True))


@pytest.fixture
def ros():
    rclpy.init()
    executor = SingleThreadedExecutor()
    probe = Node("laptop_test_probe")
    executor.add_node(probe)
    nodes = [probe]

    def wait(predicate, tick=lambda: None, timeout=15):
        deadline = time.monotonic() + timeout
        next_tick = 0.0
        while time.monotonic() < deadline:
            # Publish heartbeats at 50 Hz even when ready DDS callbacks make
            # spin_once return immediately; avoid flooding the command queues.
            now = time.monotonic()
            if now >= next_tick:
                tick()
                next_tick = now + 0.02
            executor.spin_once(timeout_sec=0.01)
            if predicate():
                return
        pytest.fail("Timed out waiting for ROS pipeline output")

    yield probe, executor, nodes, wait
    for node in nodes:
        executor.remove_node(node)
        node.destroy_node()
    executor.shutdown()
    rclpy.shutdown()


@pytest.fixture
def processes(tmp_path):
    children = []

    def start(*args):
        log = (tmp_path / f"process-{len(children)}.log").open("w+")
        child = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        children.append((child, log))
        return child

    yield start
    for child, log in reversed(children):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        log.seek(0)
        print(log.read())  # Captured by pytest, shown on failure.
        log.close()


def test_guard_topics_startup_clamp_disable_and_watchdogs(ros):
    probe, executor, nodes, wait = ros
    guard = GuardNode()
    nodes.append(guard)
    executor.add_node(guard)
    output = []
    probe.create_subscription(Twist, "/cmd_vel", output.append, 10)
    commands = probe.create_publisher(Twist, "/cmd_vel_guard_input", 10)
    health = probe.create_publisher(Bool, "/perception/healthy", 10)
    command = Twist()
    command.linear.x, command.angular.z = 9.0, -9.0

    def publish(healthy=True, command_enabled=True, health_enabled=True):
        if command_enabled:
            commands.publish(command)
        if health_enabled:
            health.publish(Bool(data=healthy))

    def stopped():
        return output and output[-1].linear.x == 0 and output[-1].angular.z == 0

    wait(lambda: commands.get_subscription_count() == 1 and
         health.get_subscription_count() == 1)
    wait(stopped, tick=publish)  # Disabled even with healthy input.
    guard.set_parameters([Parameter("enabled", value=True)])
    wait(lambda: output and output[-1].linear.x == 0.2 and
         output[-1].angular.z == -0.5, tick=publish)
    began = time.monotonic()
    wait(lambda: time.monotonic() - began > 0.35 and stopped(),
         tick=lambda: publish(health_enabled=False), timeout=3)
    wait(lambda: output[-1].linear.x == 0.2, tick=publish)
    began = time.monotonic()
    wait(lambda: time.monotonic() - began > 0.35 and stopped(),
         tick=lambda: publish(command_enabled=False), timeout=3)
    wait(lambda: output[-1].linear.x == 0.2, tick=publish)
    output.clear()
    wait(stopped, tick=lambda: publish(healthy=False))
    guard.set_parameters([Parameter("enabled", value=False)])
    output.clear()
    wait(stopped, tick=publish)


def make_camera_bag(path):
    """Tiny deterministic textured pair with an 8-pixel disparity, 0.1m baseline."""
    width, height = 320, 192
    rng = np.random.default_rng(42)
    left = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    right = np.roll(left, -8, axis=1)
    bridge = CvBridge()
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    for side in ("left", "right"):
        for name, kind in (("image_raw", "Image"), ("camera_info", "CameraInfo")):
            writer.create_topic(rosbag2_py.TopicMetadata(
                name=f"/stereo/{side}/{name}", type=f"sensor_msgs/msg/{kind}",
                serialization_format="cdr"))
    for index in range(12):
        timestamp = 10_000_000_000 + index * 100_000_000
        for side, pixels in (("left", left), ("right", right)):
            image = bridge.cv2_to_imgmsg(pixels, encoding="bgr8")
            image.header.frame_id = f"{side}_optical_frame"
            image.header.stamp.sec = timestamp // 1_000_000_000
            image.header.stamp.nanosec = timestamp % 1_000_000_000
            info = CameraInfo()
            info.header = image.header
            info.width, info.height = width, height
            info.distortion_model = "plumb_bob"
            info.d = [0.0] * 5
            info.k = [200.0, 0.0, 160.0, 0.0, 200.0, 96.0, 0.0, 0.0, 1.0]
            info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
            info.p = [200.0, 0.0, 160.0, -20.0 if side == "right" else 0.0,
                      0.0, 200.0, 96.0, 0.0, 0.0, 0.0, 1.0, 0.0]
            for name, msg in (("image_raw", image), ("camera_info", info)):
                writer.write(f"/stereo/{side}/{name}", serialize_message(msg), timestamp)
    del writer  # Finalize metadata before the real rosbag player opens it.
    return left


@pytest.mark.parametrize("protocol", ["json", "jpeg"])
def test_camera_replay_stereo_and_http_detector(ros, processes, tmp_path, protocol):
    probe, _, _, wait = ros
    bag = tmp_path / "camera"
    original = make_camera_bag(bag)
    received = {key: [] for key in ("raw", "rect", "disparity", "points", "people", "annotated")}
    for key, kind, topic in (
        ("raw", Image, "/stereo/left/image_raw"),
        ("rect", Image, "/stereo/left/image_rect"),
        ("disparity", DisparityImage, "/stereo/disparity"),
        ("points", PointCloud2, "/stereo/points2"),
        ("people", Detection2DArray, "/people"),
        ("annotated", Image, "/image_annotated"),
    ):
        probe.create_subscription(kind, topic, received[key].append, qos_profile_sensor_data)
    stereo = processes("ros2", "launch", "dubdash", "stereo.launch.py")
    url = os.environ.get("INFERENCE_URL", "http://127.0.0.1:8000")
    inference_parameter = "inference_url:=" + url if protocol == "json" else "endpoint:=" + url + "/"
    detector = processes(
        "ros2", "run", "dubdash", "person_detector", "--ros-args",
        "-p", inference_parameter,
        "-p", "allow_mock_inference:=true", "-r", "image:=/stereo/left/image_rect")
    # Wait for DDS discovery rather than guessing process startup with a sleep.
    wait(lambda: probe.count_subscribers("/stereo/left/image_raw") >= 1 and
         probe.count_subscribers("/stereo/right/image_raw") >= 1 and
         probe.count_publishers("/people") >= 1, timeout=30)
    player = processes("ros2", "bag", "play", str(bag), "--loop", "--rate", "1.0")

    def complete():
        assert stereo.poll() is None, "Stereo process exited"
        assert detector.poll() is None, "Detector process exited"
        assert player.poll() is None, "Camera replay exited"
        return all(received.values())

    wait(complete, timeout=30)
    raw, rect = received["raw"][-1], received["rect"][-1]
    assert (rect.width, rect.height, rect.encoding) == (320, 192, "mono8")
    assert rect.header.frame_id == raw.header.frame_id == "left_optical_frame"
    assert any(msg.header.stamp == rect.header.stamp for msg in received["raw"])
    expected = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    assert np.array_equal(CvBridge().imgmsg_to_cv2(rect), expected)
    disparity = received["disparity"][-1]
    values = CvBridge().imgmsg_to_cv2(disparity.image)
    valid = values[np.isfinite(values) & (values > 0)]
    assert valid.size > 100 and abs(float(np.median(valid)) - 8) < 1
    points = received["points"][-1]
    assert points.width * points.height > 0 and len(points.data) > 0
    assert {field.name for field in points.fields} >= {"x", "y", "z"}
    people = received["people"][-1]
    assert len(people.detections) == 1  # Car filtered by the actual detector node.
    person = people.detections[0]
    assert person.results[0].hypothesis.class_id == "person"
    assert person.results[0].hypothesis.score == pytest.approx(0.95)
    assert person.bbox.size_x == 80 and person.bbox.size_y == 96
    annotated = received["annotated"][-1]
    assert annotated.encoding == "bgr8" and annotated.header.frame_id == "left_optical_frame"
    assert any(msg.header.stamp == annotated.header.stamp for msg in received["raw"])
    assert any(msg.header.stamp == people.header.stamp for msg in received["raw"])
    assert not np.array_equal(CvBridge().imgmsg_to_cv2(annotated),
                              cv2.cvtColor(expected, cv2.COLOR_GRAY2BGR))
