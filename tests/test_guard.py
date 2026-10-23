import math
import pytest
from dubdash.guard import CommandGuard


def ready():
    guard = CommandGuard()
    guard.receive_command(0.1, 0.3, 10)
    guard.receive_health(True, 10)
    return guard


def test_disabled_and_startup_stop():
    assert CommandGuard().output(10, True) == (0, 0)
    assert ready().output(10) == (0, 0)


def test_fresh_command_and_clamping():
    guard = ready()
    assert guard.output(10.1, True) == (0.1, 0.3)
    guard.receive_command(9, -9, 10.1)
    assert guard.output(10.1, True) == (0.2, -0.5)


def test_stale_health_stops_despite_new_command():
    guard = ready()
    guard.receive_command(0.1, 0, 11)
    assert guard.output(11, True) == (0, 0)


def test_stale_command_stops_despite_new_health():
    guard = ready()
    guard.receive_health(True, 11)
    assert guard.output(11, True) == (0, 0)


def test_unhealthy_invalidates_command():
    guard = ready()
    guard.receive_health(False, 10.1)
    guard.receive_health(True, 10.2)
    assert guard.output(10.2, True) == (0, 0)


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_command_stops(value):
    guard = ready()
    guard.receive_command(value, 0, 10.1)
    assert guard.output(10.1, True) == (0, 0)


def test_clock_reversal_stops():
    assert ready().output(9, True) == (0, 0)


@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf])
def test_invalid_limits(value):
    with pytest.raises(ValueError):
        CommandGuard(timeout=value)
