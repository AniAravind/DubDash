"""Fail-closed freshness policy shared by the ROS supervisor and laptop tests."""
import math


class NavigationHealth:
    REQUIRED = ('depth', 'detections', 'odometry', 'ground', 'localization')

    def __init__(self, timeout=0.25, person_hold=2.0):
        if any(not math.isfinite(v) or v <= 0 for v in (timeout, person_hold)):
            raise ValueError('Timeouts must be finite and positive')
        self.timeout, self.person_hold = timeout, person_hold
        self.samples = {}
        self.last_sources = {}
        self.last_rejected = {}
        self.person_until = -math.inf

    def observe(self, name, source_time, ros_now, wall_now, valid=True):
        # Both capture age and monotonic arrival age matter. Repeated old images
        # and a stopped ROS clock must never keep permission alive.
        previous = self.last_sources.get(name)
        limit = 2.0 if name == 'localization' else self.timeout
        fresh = (all(math.isfinite(v) for v in (source_time, ros_now, wall_now))
                 and source_time > 0 and 0 <= ros_now-source_time <= limit)
        if previous is not None and source_time <= previous:
            self.samples.pop(name, None)
            self.last_rejected[name] = 'Repeated/reversed source timestamp'
            return
        if math.isfinite(source_time):
            self.last_sources[name] = source_time
        if not valid or not fresh:
            self.samples.pop(name, None)
            self.last_rejected[name] = f'valid={valid}, capture_age={ros_now-source_time}'
        else:
            self.samples[name] = (source_time, wall_now)

    def person(self, wall_now):
        self.person_until = wall_now + self.person_hold

    def reasons(self, ros_now, wall_now, transforms_ok=True, map_ok=True):
        reasons = []
        for name in self.REQUIRED:
            sample = self.samples.get(name)
            limit = 2.0 if name == 'localization' else self.timeout
            if sample is None or not (0 <= ros_now-sample[0] <= limit
                                      and 0 <= wall_now-sample[1] <= limit):
                reasons.append(name)
        if wall_now < self.person_until:
            reasons.append('person detected')
        if not transforms_ok:
            reasons.append('transforms')
        if not map_ok:
            reasons.append('map')
        return reasons
