"""Exercise the actual GUI loop with a synthetic stream and stub model, no display."""
from types import SimpleNamespace
import time
import numpy as np
import pytest
import iphone_view
from iphone_stream import LatestFrame, decode_packet
from test_iphone_stream import packet


class Tensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


@pytest.mark.parametrize('face_only', [False, True])
def test_viewer_labels_sensor_distance_and_clears_on_disconnect(monkeypatch, face_only):
    latest = LatestFrame()
    frame = decode_packet(packet(dict(rotation_degrees=90, mirrored=True)))
    latest.publish(frame)
    state = dict(rendered=False, cleared=False, disconnected=False, closed=False, loops=0)
    labels = {}

    class Receiver:
        error = None

        def __init__(self, *args):
            self.latest = latest

        def start(self):
            pass

        def close(self):
            state['closed'] = True

    class Model:
        def predict(self, image, **kwargs):
            assert image.shape == (80, 60, 3)  # portrait transform before inference
            return [SimpleNamespace(boxes=SimpleNamespace(
                xyxy=Tensor([] if face_only else [[0, 0, 60, 80]]),
                conf=Tensor([] if face_only else [0.92])))]

    def put_text(image, text, *args):
        labels.setdefault(id(image), []).append(text)
        return image

    def show(title, image):
        text = labels.get(id(image), [])
        if any('0.85 m' in label and (not face_only or 'person (face)' in label) for label in text):
            state['rendered'] = True
        if state['disconnected'] and any('Connection lost' in label for label in text):
            assert image.shape == (480, 640, 3)
            assert not np.any(image)  # actual clean black canvas, no old RGB
            state['cleared'] = True

    def wait_key(delay):
        state['loops'] += 1
        assert state['loops'] < 100, 'Inference/GUI failed to advance'
        if state['rendered'] and not state['disconnected']:
            latest.clear()
            state['disconnected'] = True
        if state['cleared']:
            return ord('q')
        time.sleep(0.01)
        return -1

    monkeypatch.setattr(iphone_view, 'IPhoneReceiver', Receiver)
    monkeypatch.setattr(iphone_view, 'FaceDetector',
                        lambda: SimpleNamespace(detect=lambda image: [[10, 10, 50, 60]] if face_only else []))
    monkeypatch.setattr(iphone_view.cv2, 'namedWindow', lambda *args: None)
    monkeypatch.setattr(iphone_view.cv2, 'destroyAllWindows', lambda: None)
    monkeypatch.setattr(iphone_view.cv2, 'getWindowProperty', lambda *args: 1)
    monkeypatch.setattr(iphone_view.cv2, 'putText', put_text)
    monkeypatch.setattr(iphone_view.cv2, 'imshow', show)
    monkeypatch.setattr(iphone_view.cv2, 'waitKey', wait_key)
    iphone_view.run_iphone(SimpleNamespace(host='127.0.0.1', port=8765,
                                          confidence=0.5, device='cpu'), Model(), [0])
    assert state['rendered'] and state['cleared'] and state['closed']
