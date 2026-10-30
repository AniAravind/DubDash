"""Battery and emergency-stop freshness policy, independent of ROS."""
import math


class SystemHealth:
    def __init__(self, minimum):
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 < minimum < 1:
            raise ValueError('Configure battery_min_fraction between 0 and 1 from battery qualification')
        self.minimum = minimum
        self.samples = {}
        self.sources = {}
        self.last_rejected = {}

    def observe(self, name, stamp, now, wall, okay):
        limit = 2.0 if name == 'battery' else .25
        valid = (all(math.isfinite(v) for v in (stamp, now, wall)) and stamp > 0
                 and 0 <= now-stamp <= limit and stamp > self.sources.get(name, -1))
        if math.isfinite(stamp):
            self.sources[name] = max(stamp, self.sources.get(name, -1))
        if valid and okay:
            self.samples[name] = (stamp, wall)
        else:
            self.samples.pop(name, None)
            self.last_rejected[name] = dict(age=now-stamp, condition=bool(okay), timestamp_valid=valid)

    def reasons(self, now, wall):
        result = []
        for name in ('battery', 'emergency_stop'):
            limit = 2.0 if name == 'battery' else .25
            stamp, arrived = self.samples.get(name, (-math.inf, -math.inf))
            if not (0 <= now-stamp <= limit and 0 <= wall-arrived <= limit):
                result.append(name)
        return result
