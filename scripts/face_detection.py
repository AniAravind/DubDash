"""Local frontal-face fallback for person detectors trained on body images."""
from pathlib import Path
import cv2


class FaceDetector:
    def __init__(self):
        path = Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'
        self.classifier = cv2.CascadeClassifier(str(path))
        if self.classifier.empty():
            raise RuntimeError('OpenCV face detector is missing; reinstall opencv-python.')

    def detect(self, image):
        gray = cv2.equalizeHist(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        # Limit CPU work on high-resolution inputs, preserving the original coordinates.
        scale = min(1.0, 640 / max(gray.shape))
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        faces = self.classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                                 minSize=(30, 30))
        return [[x / scale, y / scale, (x + w) / scale, (y + h) / scale]
                for x, y, w, h in faces]


def detection_targets(boxes, scores, faces):
    """Count a face inside a body once; prefer face depth when a face is visible."""
    targets = [dict(box=box, score=score, face=None) for box, score in zip(boxes, scores)]
    for face in faces:
        fx1, fy1, fx2, fy2 = face
        area = (fx2 - fx1) * (fy2 - fy1)
        if area <= 0:
            continue
        matches = []
        for index, box in enumerate(boxes):
            x1, y1, x2, y2 = box
            overlap = max(0, min(fx2, x2) - max(fx1, x1)) * max(0, min(fy2, y2) - max(fy1, y1))
            if overlap / area >= 0.6:
                matches.append((overlap / area, -((x2 - x1) * (y2 - y1)), index))
        if matches:
            target = targets[max(matches)[2]]
            old_face = target['face']
            if old_face is None or area > (old_face[2] - old_face[0]) * (old_face[3] - old_face[1]):
                target['face'] = face
        else:
            # A face detector has no YOLO probability: don't invent a confidence percentage.
            targets.append(dict(box=face, score=None, face=face))
    return targets
