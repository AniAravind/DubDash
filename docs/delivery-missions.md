# Named delivery missions

The headless Orin runtime now includes a mission manager and system supervisor.
Only an accepted, running mission grants `/missions/permit`. The command guard
requires fresh mission permission, system health and perception health in addition
to a fresh velocity command. Startup remains disabled. A direct RViz/action goal
alone does not grant motion permission.

## Configure actual destinations

Make a JSON file associated with the actual saved robot route map:

```json
{
  "frame_id": "map",
  "destinations": {
    "pickup": {"x": 1.0, "y": 2.0, "yaw": 0.0},
    "dropoff": {"x": 3.0, "y": 2.0, "yaw": 1.57},
    "home": {"x": 0.0, "y": 0.0, "yaw": 0.0}
  }
}
```

These numbers only illustrate the format. Replace them with reachable surveyed
positions from your own map; this is not GPS/address geocoding. Coordinates are
meters and yaw is radians. The shipped example is deliberately empty. Keep each
catalog with its corresponding map; the system cannot detect a semantically wrong
destination placed in a different map using the same frame name.

Set `battery_min_fraction` in the measured robot YAML to a battery/BMS-qualified
value between 0 and 1. It ships as null, which blocks startup. Complete the other
measured fields described in `robot-navigation.md`.

```bash
export ROBOT_CONFIG=/absolute/path/to/robot.yaml
export ROBOT_MAPS=/absolute/path/to/robot-maps
export ROBOT_DESTINATIONS=/absolute/path/to/destinations.json
docker compose -f compose.robot.yaml build
docker compose -f compose.robot.yaml up
```

The map folder contains `route.db`, localization snapshots and `missions.sqlite`.
The latter stores command IDs and mission events. Preserve it across restarts;
do not delete it to retry a delivery. Use only one mission manager/guard on the ROS
domain. The Compose configuration stays on Linux host networking, domain 43,
localhost-only; this is not a public remote-control API.

## Send and inspect missions

From another terminal on the Jetson:

```bash
docker compose -f compose.robot.yaml exec robot ros2 run dubdash mission status
docker compose -f compose.robot.yaml exec robot ros2 run dubdash mission start pickup dropoff home --request-id delivery-001
docker compose -f compose.robot.yaml exec robot ros2 run dubdash mission cancel --request-id cancel-001
```

The CLI waits for an acknowledgement, not delivery completion. Use `mission status`
to inspect state, active destination, completed stops, remaining distance and the
last command reply. Requests time out after ten seconds if no acknowledgement
arrives; retry with the **same** ID, because the original may already be accepted.
An ID cannot be reused for a different command. Rejected requests are also stored;
once conditions improve, use a new ID for a new start.

States include idle, dispatching, running, succeeded, canceling, canceled, failed
and fault. Goals run serially through Nav2's NavigateToPose action. A stop, battery
failure, perception-health loss or leg timeout cancels the active goal, revokes
permission and requires an explicit new start after recovery. No mission resumes
automatically after process restart. Default timeout is 300 seconds per leg;
change the mission manager's `leg_timeout` parameter for qualified longer routes.
Goal acceptance/result failures enter fault and require operator intervention and
restart; permission remains false while cancellation/goal outcome is unresolved.
Unconfirmed cancellation enters fault after five seconds; it never silently allows
a replacement mission while the old goal may still be active.

## Required system inputs

Adapters must publish original capture-stamped data on:

| Topic | Type | Requirement |
| --- | --- | --- |
| `/battery/state` | sensor_msgs/BatteryState | present=true, finite percentage between configured threshold and 1, health=GOOD, new source data within 2 seconds |
| `/emergency_stop/diagnostics` | diagnostic_msgs/DiagnosticArray | Exactly one `emergency_stop` status, level=OK only when the physical stop is released, source/arrival age <=250 ms |

Missing/invalid/low battery and missing/active stop revoke `/system/healthy`.
Use ROS's generated `DiagnosticStatus.OK/ERROR` constants; Humble represents this
field as a byte. Software diagnostics do not replace a hardwired emergency stop or
the motor controller's independent watchdog. A healthy dummy publisher is not a
hardware adapter.

## Opt-in ground-support prototype

`ground_validation.enabled: true` starts `ground_validator` using the profile's
measured `ground_z`, grid size, support count, height/slope limits and horizon.
It transforms the organized stereo cloud at capture time and requires actual
finite near-floor points in every grid cell of the swept enclosing disk plus
stopping margin, along the current smoothed forward/turn command. Missing cells,
drop-offs, raised ground or excess local slope reject permission. It publishes
the same `/ground/diagnostics` contract as an external validator; run exactly one.

This is intentionally restricted to a qualified flat floor. The prototype may
remain blocked with front-only stereo because it cannot see the whole footprint,
including ground under/behind the chassis. It does not cache unseen ground or
infer support from missing disparity. It is not an outdoor terrain classifier;
additional coverage or a validated external ground supervisor is still necessary
for general delivery routes. Do not enable it or loosen thresholds just to clear
a blocked status. Validate computation time and coverage on the Orin.

## Read-only deployment preflight

In an environment with Python/PyYAML/NumPy installed (including the robot image):

```bash
python3 scripts/robot_preflight.py --profile /path/to/robot.yaml \
  --destinations /path/to/destinations.json --database /path/to/route.db
```

Use `--files-only` on the Mac. Preflight checks files, configured thresholds, map
nodes, Linux ARM64 and Docker availability; it never certifies the physical robot
or installed NVIDIA stack. Do not install/flash a guessed JetPack image based on
the README's team-reported versions. Record the actual L4T and camera-board model,
then qualify the driver and TensorRT engine on that device.

The current Docker Compose starts with `enable_motion:=false`. Keep that setting
until physical acceptance tests pass. Setting the measured profile's
`hardware_verified: true` does not itself enable motion; an operator must also
launch with `enable_motion:=true` after qualification.
