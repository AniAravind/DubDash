import json
import math
import pytest
from webcam_distance import estimate_distance, reference_focal, load_calibration, save_calibration


SIZE = (1280, 720)
BOX = (400, 100, 600, 610)


def test_pinhole_distance_and_inverse_scale():
    assert estimate_distance(BOX, SIZE, 600, 1.7) == pytest.approx(2.0)
    assert estimate_distance((400, 100, 500, 355), SIZE, 600, 1.7) == pytest.approx(4.0)


def test_reference_recovers_measured_distance():
    focal = reference_focal(BOX, SIZE, 3.2, 1.8)
    assert estimate_distance(BOX, SIZE, focal, 1.8) == pytest.approx(3.2)


@pytest.mark.parametrize('box', [(0, 100, 500, 600), (100, 100, 500, 720),
                                  (100, 100, 500, 110), (500, 100, 100, 600),
                                  (100, math.nan, 500, 600)])
def test_bad_or_clipped_boxes_have_no_distance(box):
    assert estimate_distance(box, SIZE, 600) is None


@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf])
def test_bad_reference_distance(value):
    with pytest.raises(ValueError):
        reference_focal(BOX, SIZE, value, 1.7)


def test_save_load_and_camera_resolution_checks(tmp_path):
    path = tmp_path / 'camera.json'
    data = dict(mode='reference', focal_y=600, person_height=1.7,
                camera=0, image_size=list(SIZE))
    save_calibration(path, data)
    assert load_calibration(path, SIZE, 0) == data
    with pytest.raises(ValueError):
        load_calibration(path, (640, 480), 0)
    with pytest.raises(ValueError):
        load_calibration(path, SIZE, 1)
    data['focal_y'] = -1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_calibration(path, SIZE, 0)
