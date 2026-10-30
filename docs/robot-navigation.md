# Orin Nano navigation integration

The runtime now includes named delivery missions, battery/physical-stop checks
and an opt-in flat-floor ground validator. Read [delivery setup](delivery-missions.md)
alongside this guide. Only an accepted running mission grants motor permission;
direct action goals below are diagnostic and cannot enable movement by themselves.

This adds a Humble Nav2 runtime, not a validated autonomous robot. It uses the
saved RTAB-Map occupancy map to plan a route to a map-frame goal. DWB follows
the route by producing forward speed and yaw rate. The velocity smoother feeds
Collision Monitor, then the existing command guard, then `/cmd_vel`. Positive
linear.x is forward (m/s); positive angular.z is a left turn (rad/s).

The camera is team-reported **IMX319**. Sensor identity alone does not identify
the stereo capture board, driver, synchronization method, baseline or calibration.
The motor controller and footprint are unknown. No motor protocol or dimensions
are invented. A motor adapter must consume only `/cmd_vel`, provide its own
watchdog, and stop independently of the Jetson. A physical emergency stop remains
required. The robot launch uses visual odometry; do not also publish wheel TF.

## Install and test on the laptop

Install Docker Desktop for your Mac architecture from
https://docs.docker.com/desktop/setup/install/mac-install/ . Open the downloaded
DMG, drag Docker to Applications, launch it and complete first-run setup. No
native macOS ROS, CUDA or Jetson model engine is needed for laptop tests.

From the repository root:

```bash
docker version
docker compose version
bash scripts/test_laptop.sh
```

See `laptop-testing.md` for Compose version requirements, native architecture
selection, and the optional ARM64 build. The downloaded outdoor recordings are
for a separate mapping demo; they are not a map of your robot's delivery route.

## Prepare the Jetson

First record the real host versions rather than assuming the README's reported
JetPack/CUDA versions match the installed Orin:

```bash
cat /etc/os-release
cat /etc/nv_tegra_release
uname -m
docker version
docker compose version
```

Install Docker Engine and Compose using Docker's Ubuntu instructions if missing:
https://docs.docker.com/engine/install/ubuntu/ . Install a camera-board vendor's
IMX319 driver matched to that L4T release. Calibrate both cameras together and
publish the camera topics and measured TF specified in `hardware.md`.
No generic IMX319 driver download is selected without the board details.

Run real YOLO inference using the existing `scripts/trt_worker.py` in a Jetson
environment with qualified CUDA/TensorRT, NumPy, and OpenCV. Build/export the
engine on that Jetson; the ROS container does not install NVIDIA Python wheels.
The HTTP endpoint uses the existing JPEG protocol, not the mock JSON protocol:

```bash
python3 scripts/trt_worker.py --engine /absolute/path/to/person.engine --port 8090
```

That worker binds localhost. The ROS container uses host networking to reach it.
Qualifying its NVIDIA libraries and engine against the actual device is mandatory;
the ARM64 CPU ROS image build does not qualify GPU support.

Copy `src/dubdash/config/robot.example.yaml` to a persistent robot configuration
folder. Fill in the enclosing radius and stopping margin from measurements.
Zero values deliberately fail configuration. Review all other bench values.
Keep `hardware_verified: false` during integration.

Create a map using the calibrated robot cameras and `mapping.launch.py` while
manually supervising movement. Stop RTAB-Map cleanly and copy its database to
the persistent map directory as `route.db`. Do not reuse the demo's map.

On the Jetson, in the checkout, set absolute paths to the profile and map folder:

```bash
export ROBOT_CONFIG=/absolute/path/to/robot.yaml
export ROBOT_MAPS=/absolute/path/to/robot-maps
export ROBOT_DESTINATIONS=/absolute/path/to/destinations.json
docker compose -f compose.robot.yaml build
docker compose -f compose.robot.yaml up
```

The standalone ARM64 image installs Humble/Ubuntu 22.04, Nav2 and robot ROS
dependencies. It starts no desktop and needs no GPU access itself; inference
runs in the separate host worker. Camera, measured TF, ground validator and motor
adapter run separately on domain 43, localhost-only. Host networking is intended
for Linux Jetson, not macOS Docker Desktop. Camera device passthrough depends on
the chosen driver and is not guessed here.

## Inputs required before motion

`robot.launch.py` starts stereo processing, RTAB-Map localization using a new
SQLite snapshot of the saved map, the real detector, Nav2, Collision Monitor,
the navigation supervisor and the disabled command guard.

The supervisor requires:

| Input | Contract |
| --- | --- |
| `/stereo/points2` | Organized cloud; finite-pixel coverage above profile threshold, capture age <=250 ms, camera-to-base TF at capture |
| `/people` | Successful, advancing detector output at <=250 ms source/arrival age, including empty results |
| `/odom` | Finite `odom` to `base_link` visual odometry, <=250 ms |
| `/rtabmap/localization_pose` | Finite map-frame pose, positive x/y/yaw variances <=0.25, <=2 seconds |
| `/rtabmap/map` | Map-frame occupancy grid with free cells, transient-local subscription |
| `/ground/diagnostics` | Stamped DiagnosticArray, exactly one status named `ground_support`, level OK, <=250 ms |
| TF | Current `map -> base_link` and `odom -> base_link` chains |

The localization interval allows RTAB-Map's approximately 1 Hz place matches;
odom and depth must still update within 250 ms. Tune thresholds only after
measuring actual rates, covariance and stopping behavior. Losing matches stops
motion even when odometry continues. Clock reversal requires restarting the
supervisor; time is never made fresh by replaying old headers.

Ground validation remains a **hardware qualification requirement**. The optional
flat-floor prototype is described in the delivery guide; a general validator must evaluate
valid depth, ground support, slopes and drop-offs across the entire planned swept
footprint, including turns, and publish a new capture-stamped diagnostic only
when valid. A front camera may not cover that footprint; add coverage or restrict
the operating area accordingly. Do not substitute a constant OK publisher.
Without this input the delivered runtime stays stopped.

The stereo adapter transforms finite points into base_link and crops a configured
height band. This is not ground-plane segmentation or proof of traversability.
Points mark both costmaps; clearing rays are disabled because missing stereo depth
does not prove free space. Old obstacle marks can therefore block routes until
costmaps are deliberately cleared after inspection. Unknown map cells remain
nontraversable. Collision Monitor stops on any point inside a measured square
enclosing the robot plus its stopping margin. Both turning and forward movement
still require valid ground support.

YOLO does not estimate distance. Any person >=50% confidence stops permission
for at least two seconds, regardless of box location. Stereo supplies geometric
obstacles for other objects. This conservative initial implementation can pause
for distant people; it does not associate boxes with measured depth yet.
Automatic backing and spin recovery behaviors are omitted. The navigation tree
aborts on planning/controller failure instead of blindly recovering.

## Goals, cancellation and enabling

In a ROS shell on the same domain, inspect `/navigation/status` for blocked
inputs. With the motor controller disconnected, a goal can exercise planning:

```bash
ros2 topic echo /navigation/status
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  '{pose: {header: {frame_id: map}, pose: {position: {x: 2.0, y: 1.0}, orientation: {w: 1.0}}}}' --feedback
```

Replace coordinates with a known reachable location in the actual map. Nav2
reports success/aborted/canceled; RViz's Nav2 Goal tool can also submit goals.
Cancel using the action cancel service, then verify zero output:

```bash
ros2 service call /navigate_to_pose/_action/cancel_goal action_msgs/srv/CancelGoal \
  '{goal_info: {goal_id: {uuid: [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}, stamp: {sec: 0, nanosec: 0}}}'
ros2 topic echo /cmd_vel
```

Setting `enable_motion:=true` at launch requires `hardware_verified: true` in the
profile. Do that only after independent motor timeout/emergency stop, footprint,
camera depth, source loss, person stop, collision stop, localization loss and
loaded braking trials pass. No other node may publish `/cmd_vel`. Leave the
disabled runtime stopped and restart with the measured profile for bench trials;
do not change the guard parameter to bypass profile qualification.

For an independently started localization/detector setup, use
`ros2 launch dubdash navigation.launch.py robot_config:=/absolute/path/to/robot.yaml mission_ledger:=/absolute/path/to/missions.sqlite destinations:=/absolute/path/to/destinations.json`.
The combined launch always starts its own visual odometry; do not run another
mapping launch simultaneously.

## Validation limits

Native tests exercise permission-to-command stopping, stale/repeated/future
captures, frozen clocks, person hold, unknown-space policy, configuration rejection
and map snapshot preservation. Container tests load the new launch arguments and
exercise the supervisor adapter. Actual Nav2 planning/control is additionally
exercised with a synthetic base in the isolated laptop container. Real
stereo/localization, motor behavior and Jetson inference still require hardware
validation. Software configuration is not evidence those physical trials passed.

Reference interfaces: Humble Nav2 navigation launch and defaults at
https://github.com/ros-navigation/navigation2/tree/humble/nav2_bringup and
https://github.com/ros-navigation/navigation2/tree/humble/nav2_collision_monitor .
