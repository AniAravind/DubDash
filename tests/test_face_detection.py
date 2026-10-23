import numpy as np
import pytest
from face_detection import FaceDetector, detection_targets
from iphone_stream import person_depth


def test_face_only_target_when_yolo_has_no_body():
    face = [20, 20, 80, 80]
    targets = detection_targets([], [], [face])
    assert len(targets) == 1
    assert targets[0] == dict(box=face, score=None, face=face)


def test_face_and_body_count_once_and_sample_face():
    face = [20, 20, 80, 80]
    targets = detection_targets([[10, 10, 100, 200]], [0.92], [face])
    assert len(targets) == 1
    assert targets[0]['score'] == 0.92
    assert targets[0]['face'] == face


def test_separate_face_counts_as_additional_person():
    targets = detection_targets([[0, 0, 100, 200]], [0.92], [[150, 20, 200, 80]])
    assert len(targets) == 2


def test_face_depth_uses_centre_not_surrounding_background():
    depth = np.full((100, 100), 5.0)
    depth[35:65, 35:65] = 0.65
    assert person_depth(depth, [20, 20, 80, 80], face=True) == pytest.approx(0.65)


def test_missing_or_invalid_face_depth_unavailable():
    assert person_depth(None, [20, 20, 80, 80], face=True) is None
    assert person_depth(np.zeros((100, 100)), [20, 20, 80, 80], face=True) is None


def test_bundled_detector_loads_and_handles_blank_image():
    assert FaceDetector().detect(np.zeros((200, 200, 3), dtype=np.uint8)) == []
