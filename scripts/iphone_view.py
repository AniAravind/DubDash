"""Main-thread OpenCV GUI with background YOLO inference for TrueDepth frames."""
import threading
import time

import cv2
import numpy as np
from face_detection import FaceDetector, detection_targets
from iphone_stream import IPhoneReceiver, aligned_images, person_depth, visible_result


def run_iphone(args, model, people):
    faces = FaceDetector()
    receiver = IPhoneReceiver(args.host, args.port)
    receiver.start()
    stop = threading.Event()
    output_lock = threading.Lock()
    output = {'frame': None, 'error': None}
    show_depth = threading.Event()

    def infer():
        last_frame = None
        while not stop.is_set():
            frame = receiver.latest.snapshot()
            if frame is None or frame is last_frame:
                stop.wait(0.01)
                continue
            last_frame = frame
            try:
                image, depth = aligned_images(frame)
                result = model.predict(image, classes=people, conf=args.confidence,
                                       device=args.device, verbose=False)[0]
                face_boxes = faces.detect(image)
                if show_depth.is_set() and depth is not None:
                    valid = np.isfinite(depth) & (depth > 0)
                    # Fixed 0..3 m visualization only; sampling still uses raw metres.
                    colors = cv2.applyColorMap(
                        (np.nan_to_num(depth, nan=0, posinf=0, neginf=0).clip(0, 3) / 3 * 255).astype(np.uint8),
                        cv2.COLORMAP_TURBO)
                    blended = cv2.addWeighted(image, 0.55, colors, 0.45, 0)
                    image[valid] = blended[valid]
                boxes = result.boxes.xyxy.cpu().tolist()
                scores = result.boxes.conf.cpu().tolist()
                targets = detection_targets(boxes, scores, face_boxes)
                for target in targets:
                    box, score, face = target['box'], target['score'], target['face']
                    distance = person_depth(depth, face if face is not None else box,
                                            face=face is not None)
                    label = 'person (face)' if score is None else f'person {score:.0%}'
                    label += ' | ' + (f'{distance:.2f} m' if distance is not None else 'depth unavailable')
                    x1, y1, x2, y2 = (int(v) for v in box)
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(image, label, (max(0, x1), max(65, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                cv2.putText(image, f'People: {len(targets)} | TrueDepth surface distance',
                            (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                status = 'Sensor depth available' if depth is not None else 'Depth unavailable'
                cv2.putText(image, status, (12, 45), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 220, 255), 1)
                with output_lock:
                    output['frame'] = (frame, image)
            except Exception as error:
                with output_lock:
                    output['error'] = str(error)
                stop.set()

    worker = threading.Thread(target=infer, daemon=True)
    worker.start()
    title = 'DubDash TrueDepth - D: depth overlay, Q: quit'
    try:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        while True:
            with output_lock:
                rendered = output['frame']
                error = output['error']
            if error:
                raise RuntimeError(f'iPhone inference: {error}')
            if receiver.error:
                raise RuntimeError(f'iPhone receiver: {receiver.error}')
            current = receiver.latest.snapshot()
            image = visible_result(current, rendered, time.monotonic())
            if image is None:
                image = np.zeros((480, 640, 3), dtype=np.uint8)
                status = ('Processing current frame...' if current is not None else
                          'Connection lost / waiting for iPhone')
                cv2.putText(image, status, (20, 220), cv2.FONT_HERSHEY_SIMPLEX,
                            0.65, (0, 220, 255), 2)
                cv2.putText(image, 'Enter Mac address and token on the iPhone', (20, 255),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow(title, image)
            key = cv2.waitKey(20) & 0xff
            if key in (ord('d'), ord('D')):
                if show_depth.is_set():
                    show_depth.clear()
                else:
                    show_depth.set()
            if key in (27, ord('q'), ord('Q')):
                break
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        stop.set()
        receiver.close()
        worker.join(timeout=2)
        cv2.destroyAllWindows()
