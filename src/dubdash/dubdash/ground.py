"""Conservative flat-floor support prototype. No support is inferred in unseen cells."""
import math
import numpy as np


def ground_support(points, radius, margin, ground_z, cell_size, height_tolerance,
                   min_points, max_slope, horizon, linear=0., angular=0.):
    values = (radius, margin, cell_size, height_tolerance, max_slope, horizon)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Ground geometry/limits must be finite and positive')
    if not all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
               for v in (ground_z, linear, angular)) or linear < 0:
        raise ValueError('Invalid ground reference or motion')
    if isinstance(min_points, bool) or not isinstance(min_points, int) or min_points < 1:
        raise ValueError('min_points must be a positive integer')
    extent = radius+margin+linear*horizon
    n = math.ceil(extent/cell_size)+1
    if n > 150:
        raise ValueError('Ground grid exceeds prototype size limit')
    axis = np.arange(-n, n+1)
    gx, gy = np.meshgrid(axis, axis)
    centers = np.column_stack((gx.ravel(), gy.ravel()))*cell_size
    required = np.zeros(len(centers), dtype=bool)
    # Include a cell diagonal so discretization never shrinks the swept disk.
    padding = radius+margin+cell_size/math.sqrt(2)
    steps = max(2, math.ceil(max(linear, abs(angular)*radius)*horizon/(cell_size/2))+1)
    if steps > 10000:
        raise ValueError('Ground motion exceeds prototype size limit')
    for t in np.linspace(0, horizon, steps):
        if abs(angular) < 1e-6:
            x, y = linear*t, 0.
        else:
            x, y = linear/angular*math.sin(angular*t), linear/angular*(1-math.cos(angular*t))
        required |= (centers[:, 0]-x)**2+(centers[:, 1]-y)**2 <= padding**2
    cells = set(map(tuple, np.column_stack((gx.ravel(), gy.ravel()))[required]))
    xyz = np.asarray(points, dtype=float).reshape(-1, 3)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    # Only measured points close to the qualified flat-floor elevation count.
    xyz = xyz[np.abs(xyz[:, 2]-ground_z) <= height_tolerance]
    buckets = {}
    for point in xyz:
        key = tuple(np.floor(point[:2]/cell_size+.5).astype(int))
        if key in cells:
            buckets.setdefault(key, []).append(float(point[2]))
    missing = sum(len(buckets.get(key, [])) < min_points for key in cells)
    if missing:
        return False, f'Unknown/unsupported ground cells: {missing}/{len(cells)}'
    elevations = {key: float(np.median(buckets[key])) for key in cells}
    for (x, y), z in elevations.items():
        for neighbor in ((x+1, y), (x, y+1)):
            if neighbor in elevations and abs(z-elevations[neighbor])/cell_size > max_slope:
                return False, 'Ground step/slope exceeds configured limit'
    return True, f'Measured flat support in {len(cells)} swept cells'
