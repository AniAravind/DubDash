"""Distance policies and persistent calibration, independent of camera access."""
import json
import math
from pathlib import Path


def positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def estimate_distance(box, image_size, focal_y, person_height=1.7):
    """Approximate optical-axis depth for an upright, full-height person."""
    if not positive(focal_y) or not positive(person_height):
        raise ValueError('Focal length and person height must be positive')
    x1, y1, x2, y2 = box
    width, height = image_size
    if not all(math.isfinite(v) for v in box):
        return None
    # A clipped box cannot provide the person's full projected height.
    if x1 <= 3 or y1 <= 3 or x2 >= width - 3 or y2 >= height - 3:
        return None
    pixel_height = y2 - y1
    if pixel_height < 30 or x2 <= x1:
        return None
    return focal_y * person_height / pixel_height


def reference_focal(box, image_size, distance, person_height):
    if not positive(distance):
        raise ValueError('Reference distance must be positive')
    if estimate_distance(box, image_size, 1.0, person_height) is None:
        raise ValueError('Show one full standing person, away from image edges')
    return distance * (box[3] - box[1]) / person_height


def save_calibration(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def load_calibration(path, image_size, camera_index):
    data = json.loads(Path(path).read_text())
    if data.get('image_size') != list(image_size) or data.get('camera') != camera_index:
        raise ValueError('Calibration camera/resolution mismatch. Recalibrate at this resolution.')
    if not positive(data.get('focal_y')):
        raise ValueError('Invalid calibration focal length')
    if data.get('mode') not in ('reference', 'intrinsics'):
        raise ValueError('Unknown calibration mode')
    if data['mode'] == 'reference' and not positive(data.get('person_height')):
        raise ValueError('Invalid reference person height')
    return data
