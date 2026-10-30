# DubDash

Software foundation for a supervised delivery robot on NVIDIA Jetson Orin Nano.
Team-reported device: **ARM64 / Ubuntu 24.04 / JetPack 7.2.1 / CUDA 13.2 /
TensorRT 10.16.2**, with **ROS 2 Humble inside Docker**. The existing Humble
development image uses **Ubuntu 22.04 / Python 3.10** inside the container.
NVIDIA runtime compatibility still requires device validation. Autonomous driving
is not hardware-validated. Initial Nav2 integration is available but stays disabled
until measured geometry and required health inputs are supplied.

## Robot navigation (Orin Nano)

See [robot navigation setup](docs/robot-navigation.md) for the headless ARM64
container, saved-map localization, map-coordinate goals, and forward/turn commands.
The pipeline is RTAB-Map + live stereo obstacles → Nav2 → velocity smoother →
Collision Monitor → command guard → `/cmd_vel`. Person detections stop permission;
the new supervisor checks source age, depth coverage, localization and TF.
`compose.robot.yaml` is standalone and does not change the laptop/demo overlays.

The team reports IMX319 stereo cameras; board/driver and synchronization still
need confirmation. The footprint and motor controller are unknown. A measured
robot profile, calibrated camera/TF, external ground-support validator and motor
adapter with an independent watchdog are still required. No placeholder dimensions
or constant healthy publisher enable movement. The saved-map robot launch uses
the real TensorRT JPEG endpoint and rejects mock inference by default.

## Laptop development and CI

On Windows (Git Bash/WSL2), macOS or Linux with Docker running:

```bash
bash scripts/test_laptop.sh
```

This runs CPU-only unit and ROS integration tests with generated camera replay
and a mock HTTP inference worker, using the laptop's native architecture.
The existing `compose.yaml` is unchanged; the script explicitly selects
`compose.laptop.yaml`. Run `bash scripts/test_laptop.sh arm64-build` for the slower
Buildx/QEMU pre-merge build. See [laptop testing](docs/laptop-testing.md) for setup,
CI coverage, the mock contract and checks that still require Jetson hardware.

## Robot software

`src/dubdash` contains the code intended for the robot:

- Stereo rectification, disparity and point-cloud launch configuration.
- RTAB-Map stereo visual odometry and mapping launch configuration.
- An optional YOLO person detector publishing structured detections and annotated images.
- A command watchdog that starts disabled and stops on stale commands or health input.
- A ROS camera viewer for calibration/perception diagnostics.

The package does not include a camera driver, motor driver, wheel odometry or
ground-support validator. It now includes an initial navigation supervisor,
height-filtered stereo obstacle adapter and Nav2 configuration generator.
These still require physical robot integration and validation. See
[hardware interfaces](docs/hardware.md) and [navigation integration](docs/navigation.md).

## Build on the Jetson

Run these commands **inside an Ubuntu 22.04 / ROS 2 Humble container**, not directly
on the Ubuntu 24.04 Jetson host. For a separate native Ubuntu 22.04 system, first
install [ROS 2 Humble](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html).
From the repository root in that environment:

```bash
source /opt/ros/humble/setup.bash
sudo apt update
sudo apt install python3-colcon-common-extensions python3-rosdep \
  ros-humble-camera-calibration
# Run sudo rosdep init once if rosdep has not already been initialized.
rosdep update
rosdep install --from-paths src/dubdash --ignore-src -r -y --rosdistro humble
colcon build --symlink-install --packages-select dubdash
source install/setup.bash
```

This installs/builds the robot package only. `dubdash_replay` is not a dependency
of the robot package. GUI dependencies inherited from upstream ROS packages may
still be installed; the robot launch does not start a desktop automatically.

ROS binaries follow Humble updates rather than an immutable lock. Before trials,
record installed ROS packages, JetPack, CUDA, TensorRT and Python package versions.
Install a tested Ultralytics release and Jetson-compatible PyTorch separately;
no model weights, NVIDIA wheels or TensorRT engines are bundled or downloaded by
the robot nodes. Export engines on the target Jetson and review model licensing.

## Bring up robot components

1. Integrate the camera driver and calibration using [hardware setup](docs/hardware.md).
2. Run `ros2 launch dubdash stereo.launch.py` and inspect `/stereo/points2` in RViz
   on a development display. Exact timestamp synchronization is the default;
   timestamp matching cannot repair capture skew between unsynchronized cameras.
3. With measured transforms, run `ros2 launch dubdash mapping.launch.py`.
   RTAB-Map owns `odom → base_link` in this visual-only configuration. Do not start
   a second publisher for that transform. Its database uses the upstream default
   location; the replay development tools use separate explicit database paths.
4. Run `ros2 launch dubdash guard.launch.py` to inspect zero velocity output.
   The watchdog stays disabled and no health publisher is supplied in this starter.

For person detection on a ROS image stream:

```bash
ros2 run dubdash person_detector --ros-args \
  -p model:=/absolute/path/to/model.engine \
  -r image:=/stereo/left/image_rect
```

This publishes `/people` and `/image_annotated`, with the source image timestamp.
Distance association with measured stereo depth is still to be implemented.
There are no person-height distance estimates or face-recognition requirements
in the robot stack.

For an optional camera diagnostic window on a graphical ROS machine:

```bash
ros2 launch dubdash detection_view.launch.py \
  model:=/absolute/path/to/model.pt \
  image:=/stereo/left/image_raw camera:=left detect_all:=false
```

The window uses rqt_image_view. Annotated images are also ROS topics, so a separate
ROS-connected development machine can visualize them. Benchmark inference on the
actual Orin before selecting model size and frame rate.

## Mapping development without hardware

`src/dubdash_replay` is a separate ROS package for recorded stereo data. The CLI
helpers in `scripts/`, RViz configuration, Docker desktop and dataset downloads
are development tools; they are not part of the robot's deployment package.
They exercise mapping, localization and graph routing while cameras are unavailable.

On an M-series Mac, open Docker Desktop and run:

```bash
bash scripts/mapping_docker.sh start
```

Open [the mapping desktop](http://localhost:6080/vnc.html?autoconnect=true&resize=remote).
Follow [the Docker guide](docs/docker-mapping.md) for recordings, mapping,
localization and preserving maps. Native Ubuntu instructions and validation limits
are in [the replay guide](docs/mapping-demo.md). A graph route is not live obstacle
avoidance or a motor-control command.

## Development and checks

The native policy, replay, HTTP and benchmark tests need Python, pytest and NumPy. ROS integration
is skipped outside ROS and required by the laptop Docker workflow:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q src scripts
```

CI runs native tests on all three laptop operating systems, validates Compose,
builds both ROS packages and runs CPU ROS integration. Pull requests also build
the existing Humble image for ARM64 using Buildx/QEMU.
See [the hardware milestones](docs/milestones.md) for the remaining integration work.

The iPhone capture app, laptop webcam demo, face-only fallback, monocular distance
heuristics and their dedicated dependencies/tests were removed during the robot
scope cleanup. Earlier versions remain in Git history (last demo commit `685f9eb`).
Local recordings, maps, calibration data and model files are left intact.

Project licensing is undecided; `UNLICENSED` is a placeholder, not a grant of
redistribution rights.
