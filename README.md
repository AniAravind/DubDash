# DubDash

Software foundation for a supervised delivery robot on NVIDIA Jetson Orin Nano.
Target: **JetPack 6 / Ubuntu 22.04 / ROS 2 Humble / Python 3.10**. Confirm the
installed JetPack before installing ROS. Autonomous driving is not implemented
or validated yet.

## Robot software

`src/dubdash` contains the code intended for the robot:

- Stereo rectification, disparity and point-cloud launch configuration.
- RTAB-Map stereo visual odometry and mapping launch configuration.
- An optional YOLO person detector publishing structured detections and annotated images.
- A command watchdog that starts disabled and stops on stale commands or health input.
- A ROS camera viewer for calibration/perception diagnostics.

The package does not include a camera driver, motor driver, wheel odometry,
perception health supervisor, ground/obstacle filtering or a configured Nav2
navigation stack. Those depend on the physical robot. See
[hardware interfaces](docs/hardware.md) and [navigation integration](docs/navigation.md).

## Build on the Jetson

Install [ROS 2 Humble](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)
on the compatible Ubuntu system, then from the repository root:

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

The remaining policy and replay tests need Python and pytest, not ROS, OpenCV,
PyTorch, WebSockets or Xcode:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q src scripts
```

CI also builds both ROS packages and checks the replay launch arguments on Humble.
The mapping Docker image runs the policy/replay tests against its ROS environment.
See [the hardware milestones](docs/milestones.md) for the remaining integration work.

The iPhone capture app, laptop webcam demo, face-only fallback, monocular distance
heuristics and their dedicated dependencies/tests were removed during the robot
scope cleanup. Earlier versions remain in Git history (last demo commit `685f9eb`).
Local recordings, maps, calibration data and model files are left intact.

Project licensing is undecided; `UNLICENSED` is a placeholder, not a grant of
redistribution rights.
