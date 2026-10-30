"""Ultralytics adapter or local TensorRT HTTP bridge, with wall-clock metrics."""
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray, Detection2D, ObjectHypothesisWithPose
from cv_bridge import CvBridge


class PersonDetector(Node):
    def __init__(self):
        super().__init__('person_detector')
        self.endpoint = self.declare_parameter('endpoint', '').value
        from dubdash.inference_http import HttpInference
        url = self.declare_parameter('inference_url', '').value
        timeout = self.declare_parameter('inference_timeout', 1.0).value
        allow_mock = self.declare_parameter('allow_mock_inference', False).value
        self.allow_mock = allow_mock
        if url and self.endpoint:
            raise ValueError('Choose either endpoint or inference_url')
        self.remote = HttpInference(url, timeout, allow_mock) if url else None
        if allow_mock:
            self.get_logger().warning('Mock inference permitted: development use only')
        self.model = None
        if not self.endpoint and self.remote is None:
            from ultralytics import YOLO
            model = self.declare_parameter('model', '').value
            if not model or not Path(model).is_file():
                raise ValueError('Supply an existing local .pt/.engine or HTTP endpoint')
            self.model = YOLO(model, task='detect')
        self.confidence = self.declare_parameter('confidence', .5).value
        self.detect_all = self.declare_parameter('detect_all', False).value
        self.imgsz = self.declare_parameter('imgsz', 640).value
        self.device = self.declare_parameter('device', '0').value
        self.warmup_frames = self.declare_parameter('warmup_frames', 10).value
        self.metrics_file = None
        metrics_path = self.declare_parameter('metrics_path', '').value
        if metrics_path:
            self.metrics_file = Path(metrics_path).open('x', buffering=1)
        self.bridge = CvBridge()
        self.image_publisher = self.create_publisher(Image, 'image_annotated', 1)
        self.publisher = self.create_publisher(Detection2DArray, 'people', 10)
        self.metrics_publisher = self.create_publisher(String, 'metrics', 10)
        self.processed = 0
        self.first_started = None
        camera_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                               reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, 'image', self.detect, camera_qos)

    def predict(self, frame):
        if getattr(self, 'remote', None) is not None:
            started = time.perf_counter()
            predictions = self.remote.predict(frame.shape[1], frame.shape[0],
                                               frame.tobytes(), self.confidence)
            boxes = []
            for item in predictions:
                x, y, w, h = item['xywh']
                boxes.append(dict(label=item['label'], score=item['score'],
                                  xyxy=[x-w/2, y-h/2, x+w/2, y+h/2]))
            # This development protocol has no GPU timing measurement.
            return boxes, None, (time.perf_counter()-started)*1000
        if self.endpoint:
            import cv2
            ok, jpeg = cv2.imencode('.jpg', frame)
            if not ok:
                raise ValueError('JPEG encoding failed')
            with urlopen(Request(self.endpoint, data=jpeg.tobytes(),
                                 headers={'Content-Type': 'image/jpeg', 'X-Confidence': str(self.confidence)}), timeout=30) as response:
                result = json.load(response)
            if result.get('backend') == 'mock' and not getattr(self, 'allow_mock', False):
                raise ValueError('Mock inference requires explicit opt-in')
            return result['boxes'], result['inference_ms'], result['worker_ms']
        import torch
        gpu = str(self.device) != 'cpu'
        sync_device = int(self.device) if str(self.device).isdigit() else self.device
        if gpu:
            torch.cuda.synchronize(sync_device)
        started = time.perf_counter()
        result = self.model.predict(frame, conf=self.confidence, verbose=False,
                                    imgsz=self.imgsz, device=self.device)[0]
        if gpu:
            torch.cuda.synchronize(sync_device)
        worker_ms = (time.perf_counter()-started)*1000
        boxes = [dict(xyxy=box.xyxy[0].tolist(), score=float(box.conf.item()),
                      label=result.names[int(box.cls.item())]) for box in result.boxes]
        # Ultralytics reports its synchronized inference-stage timer separately
        # from the synchronized outer predict duration (pre/postprocessing included).
        return boxes, float(result.speed['inference']), worker_ms

    def detect(self, msg):
        import cv2
        started = time.perf_counter()
        if self.first_started is None:
            self.first_started = started
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        try:
            boxes, inference_ms, worker_ms = self.predict(frame)
        except Exception as error:
            self.get_logger().error(f'Detection failed: {error}')
            return
        output = Detection2DArray()
        output.header = msg.header
        for box in boxes:
            label = box['label']
            if box['score'] < self.confidence or (not self.detect_all and label != 'person'):
                continue
            x1, y1, x2, y2 = box['xyxy']
            detection = Detection2D()
            detection.header = msg.header
            center = detection.bbox.center
            position = center.position if hasattr(center, 'position') else center
            position.x, position.y = (x1+x2)/2, (y1+y2)/2
            detection.bbox.size_x, detection.bbox.size_y = x2-x1, y2-y1
            hypothesis = ObjectHypothesisWithPose()
            hypothesis.hypothesis.class_id = label
            hypothesis.hypothesis.score = box['score']
            detection.results.append(hypothesis)
            output.detections.append(detection)
            x1, y1, x2, y2 = map(int, (x1,y1,x2,y2))
            cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)
            cv2.putText(frame, f'{label} {box["score"]:.0%}', (max(0,x1),max(20,y1-8)),
                        cv2.FONT_HERSHEY_SIMPLEX, .6, (0,255,0), 2)
        annotated = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        annotated.header = msg.header
        self.image_publisher.publish(annotated)
        self.publisher.publish(output)
        ended = time.perf_counter()
        self.processed += 1
        metrics = dict(stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec,
                       frame_id=msg.header.frame_id, processed=self.processed,
                       callback_started_monotonic_s=started, completed_monotonic_s=ended,
                       warmup=self.processed <= self.warmup_frames,
                       callback_ms=(ended-started)*1000, inference_ms=inference_ms,
                       worker_ms=worker_ms, elapsed_s=ended-self.first_started,
                       detection_fps=self.processed/(ended-self.first_started),
                       detections=len(output.detections))
        # Bag stamps are recorded ROS time, never subtracted from host wall time.
        payload = json.dumps(metrics)
        self.metrics_publisher.publish(String(data=payload))
        if self.metrics_file:
            self.metrics_file.write(payload+'\n')

    def destroy_node(self):
        if self.metrics_file:
            self.metrics_file.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetector()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
