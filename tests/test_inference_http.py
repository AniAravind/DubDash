"""Exercise actual HTTP sockets without ROS, NumPy, model weights or a GPU."""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dubdash.inference_http import HttpInference, InferenceError
from mock_inference_worker import MockHandler


@pytest.fixture
def serve():
    servers = []

    def start(handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02),
                                  daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mock_http_health_predictions_and_confidence(serve):
    url = serve(MockHandler)
    with urlopen(url + "/health", timeout=2) as response:
        assert json.load(response) == {"status": "ok", "backend": "mock", "version": 1}
    client = HttpInference(url, allow_mock=True)
    boxes = client.predict(16, 8, bytes(16 * 8 * 3))
    assert [box["label"] for box in boxes] == ["person", "car"]
    assert boxes[0]["xywh"] == [8, 4, 4, 4]
    assert client.predict(16, 8, bytes(384), confidence=0.99) == []


def test_mock_requires_explicit_opt_in(serve):
    with pytest.raises(InferenceError, match="explicit opt-in"):
        HttpInference(serve(MockHandler)).predict(2, 2, bytes(12))


@pytest.mark.parametrize("mutation", [
    {"version": 2},
    {"confidence": -1},
    {"image": {"width": 2, "height": 2, "encoding": "rgb8", "data": ""}},
    {"image": {"width": 2, "height": 2, "encoding": "bgr8", "data": "@@@"}},
    {"image": {"width": 2, "height": 2, "encoding": "bgr8", "data": ""}},
])
def test_worker_rejects_malformed_images(serve, mutation):
    payload = {"version": 1, "confidence": 0.5, "image": {
        "width": 2, "height": 2, "encoding": "bgr8",
        "data": base64.b64encode(bytes(12)).decode()}}
    payload.update(mutation)
    request = Request(serve(MockHandler) + "/infer", data=json.dumps(payload).encode())
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=2)
    assert error.value.code == 400


@pytest.mark.parametrize("reply", [
    b"not json",
    b'{"version": 2}',
    b'{"version": 1, "backend": "unknown", "detections": []}',
    b'{"version": 1, "backend": "tensorrt", "detections": [{}]}',
    b'{"version": 1, "backend": "tensorrt", "detections": '
    b'[{"label": "person", "score": 0.9, "xywh": [1, 1, -1, 2]}]}',
])
def test_client_rejects_bad_responses(serve, reply):
    class BadWorker(MockHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(reply)

    with pytest.raises(InferenceError):
        HttpInference(serve(BadWorker)).predict(2, 2, bytes(12))


def test_worker_http_error_and_unavailable_worker(serve):
    class FailedWorker(MockHandler):
        def do_POST(self):
            self.reply(503, {"error": "unavailable"})

    url = serve(FailedWorker)
    with pytest.raises(InferenceError, match="503"):
        HttpInference(url).predict(2, 2, bytes(12))
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    offline = f"http://127.0.0.1:{server.server_port}"
    server.server_close()
    with pytest.raises(InferenceError):
        HttpInference(offline, timeout=0.1).predict(2, 2, bytes(12))


def test_worker_timeout_is_bounded(serve):
    class SlowWorker(MockHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(0.3)
            # Deliberately send no response; client must time out first.

    start = time.monotonic()
    with pytest.raises(InferenceError):
        HttpInference(serve(SlowWorker), timeout=0.05).predict(2, 2, bytes(12))
    assert time.monotonic() - start < 2


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        HttpInference("http://localhost:8000", timeout=timeout)
