"""ROS-independent command freshness policy; this is not an obstacle detector."""
import math


class CommandGuard:
    def __init__(self, timeout=0.25, max_linear=0.2, max_angular=0.5):
        if any(not math.isfinite(v) or v <= 0 for v in
               (timeout, max_linear, max_angular)):
            raise ValueError("Limits and timeout must be finite and positive")
        self.timeout = timeout
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.command = (0.0, 0.0)
        self.command_time = None
        self.health_time = None

    def receive_command(self, linear, angular, now):
        if not all(math.isfinite(v) for v in (linear, angular)):
            self.command_time = None
            return
        self.command = (max(-self.max_linear, min(self.max_linear, linear)),
                        max(-self.max_angular, min(self.max_angular, angular)))
        self.command_time = now

    def receive_health(self, healthy, now):
        self.health_time = now if healthy else None
        if not healthy:
            self.command_time = None

    def output(self, now, enabled=False):
        fresh = all(t is not None and 0 <= now - t <= self.timeout
                    for t in (self.command_time, self.health_time))
        return self.command if enabled and fresh else (0.0, 0.0)
