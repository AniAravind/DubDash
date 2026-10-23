"""Optional Ultralytics adapter. Model weights must be supplied explicitly."""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
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
        self.detect_all = self.declare_parameter("detect_all", False).value
        self.bridge = CvBridge()
        self.image_publisher = self.create_publisher(Image, "image_annotated", 1)
        self.publisher = self.create_publisher(Detection2DArray, "people", 10)
        camera_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, "image", self.detect, camera_qos)

    def detect(self, msg):
        import cv2
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        result = self.model.predict(frame, conf=self.confidence, verbose=False)[0]
        output = Detection2DArray()
        output.header = msg.header
        for box in result.boxes:
            class_id = int(box.cls.item())
            label = result.names[class_id]
            if not self.detect_all and label != "person":
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
            hypothesis.hypothesis.class_id = label
            hypothesis.hypothesis.score = float(box.conf.item())
            detection.results.append(hypothesis)
            output.detections.append(detection)
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{label} {hypothesis.hypothesis.score:.0%}",
                        (max(0, x1), max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        annotated = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        annotated.header = msg.header
        self.image_publisher.publish(annotated)
        self.publisher.publish(output)


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetector()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
