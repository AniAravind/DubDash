"""Dependency-free benchmark statistics; callers choose units; samples retain those units."""
import math


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0, 'mean': None, 'p50': None, 'p95': None, 'p99': None}
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Samples must be finite and nonnegative')
    def percentile(q):
        index = (len(values) - 1) * q
        lo = int(index)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return dict(count=len(values), mean=sum(values) / len(values),
                p50=percentile(.5), p95=percentile(.95), p99=percentile(.99))
