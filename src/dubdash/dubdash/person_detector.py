"""Optional Ultralytics adapter. Model weights must be supplied explicitly."""
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray, Detection2D, ObjectHypothesisWithPose
from cv_bridge import CvBridge


class PersonDetector(Node):
    def __init__(self):
        super().__init__("person_detector")
        from pathlib import Path
        from ultralytics import YOLO
        model = self.declare_parameter("model", "").value
        if not model or not Path(model).is_file():
            raise ValueError("Supply an existing local .pt or TensorRT .engine model")
        self.model = YOLO(model, task="detect")
        self.confidence = self.declare_parameter("confidence", 0.5).value
        self.bridge = CvBridge()
        self.publisher = self.create_publisher(Detection2DArray, "people", 10)
        self.create_subscription(Image, "image", self.detect, qos_profile_sensor_data)

    def detect(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        result = self.model.predict(frame, conf=self.confidence, verbose=False)[0]
        output = Detection2DArray()
        output.header = msg.header
        for box in result.boxes:
            class_id = int(box.cls.item())
            if result.names[class_id] != "person":
                continue
            x, y, w, h = box.xywh[0].tolist()
            detection = Detection2D()
            detection.header = msg.header
            center = detection.bbox.center
            # vision_msgs releases use either geometry_msgs or vision_msgs Pose2D.
            position = center.position if hasattr(center, "position") else center
            position.x = x
            position.y = y
            detection.bbox.size_x = w
            detection.bbox.size_y = h
            hypothesis = ObjectHypothesisWithPose()
            hypothesis.hypothesis.class_id = "person"
            hypothesis.hypothesis.score = float(box.conf.item())
            detection.results.append(hypothesis)
            output.detections.append(detection)
        self.publisher.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetector()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
