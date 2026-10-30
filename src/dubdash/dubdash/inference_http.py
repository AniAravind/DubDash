"""Versioned CPU-testable HTTP inference contract; no ROS or GPU imports."""
import base64
import json
import math
from urllib.error import URLError
from urllib.request import Request, urlopen

MAX_BODY = 16 * 1024 * 1024


class InferenceError(RuntimeError):
    pass


def decode_image(payload):
    """Validate tightly packed BGR8 input, including actual pixel byte count."""
    if payload.get("version") != 1:
        raise ValueError("Expected protocol version 1")
    image = payload["image"]
    width, height = image["width"], image["height"]
    if any(type(v) is not int or not 1 <= v <= 4096 for v in (width, height)):
        raise ValueError("Invalid image dimensions")
    if image["encoding"] != "bgr8":
        raise ValueError("Expected bgr8")
    pixels = base64.b64decode(image["data"], validate=True)
    if len(pixels) != width * height * 3:
        raise ValueError("Image byte count does not match dimensions")
    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Invalid confidence")
    return width, height, pixels


class HttpInference:
    def __init__(self, url, timeout=1.0, allow_mock=False):
        if not url.startswith(("http://", "https://")):
            raise ValueError("Inference URL must use HTTP(S)")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Inference timeout must be finite and positive")
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.allow_mock = allow_mock

    def predict(self, width, height, pixels, confidence=0.5):
        payload = {"version": 1, "confidence": confidence, "image": {
            "width": width, "height": height, "encoding": "bgr8",
            "data": base64.b64encode(pixels).decode("ascii")}}
        decode_image(payload)
        body = json.dumps(payload).encode()
        if len(body) > MAX_BODY:
            raise InferenceError("Image request exceeds size limit")
        request = Request(self.url + "/infer", data=body,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ValueError("Response exceeds size limit")
            result = json.loads(raw)
            if result["version"] != 1:
                raise ValueError("Wrong response version")
            backend = result["backend"]
            if backend not in ("mock", "tensorrt"):
                raise ValueError("Unknown inference backend")
            if backend == "mock" and not self.allow_mock:
                raise ValueError("Mock inference requires explicit opt-in")
            detections = result["detections"]
            if not isinstance(detections, list):
                raise ValueError("Expected detection list")
            for item in detections:
                label, score, box = item["label"], item["score"], item["xywh"]
                if not isinstance(label, str) or not label:
                    raise ValueError("Invalid label")
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("Invalid score")
                if len(box) != 4 or not all(math.isfinite(v) for v in box):
                    raise ValueError("Invalid box")
                x, y, w, h = box
                if not (0 <= x <= width and 0 <= y <= height and
                        0 < w <= width and 0 < h <= height):
                    raise ValueError("Box outside image")
            return [item for item in detections if item["score"] >= confidence]
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
            raise InferenceError(f"Inference request failed: {error}") from error
