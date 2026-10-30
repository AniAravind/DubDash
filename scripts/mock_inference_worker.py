#!/usr/bin/env python3
"""Development-only stand-in for a TensorRT HTTP worker. Never loads a model."""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dubdash.inference_http import MAX_BODY, decode_image


class MockHandler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok", "backend": "mock", "version": 1})
        else:
            self.reply(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if self.path not in ("/", "/infer"):
            self.reply(404, {"error": "Unknown endpoint"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                self.reply(413, {"error": "Invalid request size"})
                return
            raw = self.rfile.read(size)
            jpeg = self.headers.get("Content-Type") == "image/jpeg"
            started = time.perf_counter()
            if jpeg:
                # Match the production trt_worker.py interface inside the ROS
                # image. Imports stay optional for Python-only JSON tests.
                import cv2
                import numpy as np
                frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    raise ValueError("Invalid JPEG")
                height, width = frame.shape[:2]
                confidence = float(self.headers.get("X-Confidence", "0.5"))
                if not 0 < confidence <= 1:
                    raise ValueError("Invalid confidence")
            else:
                payload = json.loads(raw)
                width, height, _ = decode_image(payload)
                confidence = payload["confidence"]
            detections = [
                {"label": "person", "score": 0.95,
                 "xywh": [width / 2, height / 2, width / 4, height / 2]},
                {"label": "car", "score": 0.8,
                 "xywh": [width / 4, height / 4, width / 8, height / 8]},
            ]
            detections = [item for item in detections if item["score"] >= confidence]
            if jpeg:
                boxes = []
                for item in detections:
                    x, y, w, h = item["xywh"]
                    boxes.append(dict(label=item["label"], score=item["score"],
                                      xyxy=[x-w/2, y-h/2, x+w/2, y+h/2]))
                self.reply(200, {"backend": "mock", "boxes": boxes,
                                "inference_ms": None,
                                "worker_ms": (time.perf_counter()-started)*1000})
            else:
                self.reply(200, {"version": 1, "backend": "mock", "detections": detections})
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.reply(400, {"error": str(error)})

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), MockHandler) as server:
        print(f"MOCK inference worker listening on {args.host}:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
