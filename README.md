# DubDash

ROS 2 foundation for a supervised delivery robot on NVIDIA Jetson Orin Nano.
Targets **JetPack 6 / Ubuntu 22.04 / ROS 2 Humble / Python 3.10**. Confirm the
installed JetPack before installing ROS. This repository is an integration
starter; autonomous driving is not yet implemented or validated.

## Try it now with your laptop camera (no ROS)

Use Python 3.10 or newer. From the repository folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-webcam.txt
python scripts/webcam_people.py
```

A window shows your webcam with **person** boxes, confidence scores and the number
of people visible. Allow camera access for Terminal or your IDE when prompted.
Press **Q**, **Esc**, or close the window to stop. The first run downloads the
small pretrained `yolo11n.pt` model; subsequent inference runs locally. It does not
record or upload video. “Person” is a category label, not identification by name.

On Windows, activate with `.venv\Scripts\activate` instead. If the wrong camera
opens, use `python scripts/webcam_people.py --camera 1`. Close FaceTime/Zoom or
other apps using the camera if it cannot open. On macOS, check System Settings →
Privacy & Security → Camera for the app running Python.

The default runs on CPU. On Apple Silicon, try `--device mps` for acceleration;
use `--device cpu` if that backend fails. Adjust the detection threshold with
`--confidence 0.7`. No stereo cameras, Jetson, or ROS are needed for this mode.
See [Ultralytics prediction documentation](https://docs.ultralytics.com/modes/predict/)
for the underlying detector API.

## iPhone 16 sensor-depth demo

Use the iPhone's **front TrueDepth camera** and the Mac YOLO viewer over local
Wi-Fi. Start the receiver with:

```bash
python scripts/webcam_people.py --source iphone
```

Install the included Xcode app on your phone, then enter the Mac address and token
printed by the viewer. See [the complete iPhone setup and validation guide](docs/iphone-depth.md).
The GUI shows people with sensor-based surface distances, or `depth unavailable`;
press **D** for a depth alignment overlay. No person-height estimate is used in
this mode. Physical iPhone accuracy and alignment testing is still pending.

## Distances in the laptop webcam window

The webcam now overlays `person 92% | ~2.3 m`. This is **approximate monocular
optical-axis distance**, based on projected person height, not stereo depth or
an independently measured range. A single image cannot determine absolute scale
without a known size or distance.

### Quick setup without a checkerboard

```bash
python scripts/webcam_people.py --reference-distance 2 --person-height 1.7
```

Measure 2 metres from the camera to a standing person whose height is 1.7 metres
(or change both numbers to your measurements). Keep their entire body in view,
with exactly one person visible, then press **C**. Distances appear immediately
and the reference saves to `calibration/webcam.json` for future runs. Press C
again to replace a reference. No arbitrary focal length is used before calibration.

Reference mode assumes subsequent people have the same standing height as the
reference person. A seated, bent or partly hidden person gives misleading results;
use full standing bodies. Boxes touching image edges show `distance unavailable`.
No automatic pose/occlusion validation is implemented. A laptop showing only a
face or torso cannot use this full-height method reliably.

### Lens calibration with OpenCV (optional, more complete)

Use a flat checkerboard with **9x6 inner corners** (10x7 squares), print at actual
size and measure each square. For 25 mm squares:

```bash
python scripts/calibrate_webcam.py --columns 9 --rows 6 --square-size 0.025
```

Keep the full board visible and press **Space** for each capture. Collect at
least 15 varied positions, distances and tilts covering the image, then press
**C** to solve and save. Near-duplicate captures are rejected. Reprojection RMS
must be at most 1 pixel; this is a fit check, not a distance-accuracy guarantee.
This replaces the quick-reference file. Restart `webcam_people.py` to use it.
The viewer corrects lens distortion before detection and uses calibrated vertical
focal length with `--person-height` (default 1.7 m) for distance estimates.

Keep the same camera, resolution, zoom and crop settings; disable Center Stage
and other automatic framing effects. Camera/resolution mismatches are rejected;
zoom/cropping changes require recalibration even when resolution stays the same.
Calibration files stay local and are excluded from git.

Validate the overlay against tape-measured distances at several positions. Height
variation, pose, camera tilt, occlusion and bounding-box jitter all affect accuracy.
The implemented relation is `distance = focal_y_pixels * person_height_m / box_height_pixels`.
Lens calibration follows [OpenCV's calibration workflow](https://docs.opencv.org/4.10.0/dc/dbb/tutorial_py_calibration.html).

## Included

- Stereo rectification, disparity and point-cloud launch configuration.
- RTAB-Map stereo visual odometry and mapping launch configuration.
- Optional Ultralytics person detector publishing `vision_msgs/Detection2DArray`.
- Command gate that starts disabled and stops on stale commands or health input.
- Unit tests and GitHub Actions checks, including a Humble package build.
- Hardware integration contracts, Nav2 configuration guidance and demo milestones.

## Live camera detections on your screen

The immediate demo is a live camera image with boxes, object names and confidence
scores. Run on the Jetson with a connected display, or on a ROS-connected Ubuntu
computer with a graphical desktop. Camera capture must already be publishing ROS
images; this launch does not configure the physical cameras.

After building and sourcing the workspace, with Ultralytics and compatible
PyTorch installed and a local model available:

```bash
ros2 launch dubdash detection_view.launch.py \
  model:=/absolute/path/to/model.pt \
  image:=/stereo/left/image_raw camera:=left
```

This opens an image viewer showing detections for every class supported by the
model. Set `detect_all:=false` for people only, or `confidence:=0.7` to raise the
threshold. The annotated stream is `/left/image_annotated` and structured boxes
are `/left/detections`. Frames without detections still appear as live images.
If the viewer starts blank, select `/left/image_annotated` from its topic list.

For the right camera, run a second launch in another terminal:

```bash
ros2 launch dubdash detection_view.launch.py \
  model:=/absolute/path/to/model.pt \
  image:=/stereo/right/image_raw camera:=right
```

Each camera has its own window and detector. Running two models increases GPU
load; benchmark one stream first. Use bgr8/rgb8/mono images, or a debayered driver
output. This display shows 2D recognition; it does not measure distance or drive
the robot. A remote screen requires working ROS networking and matching domain
IDs. No browser dashboard is included.

## Build on the Jetson

Install ROS 2 Humble using its official Ubuntu deb instructions first. Then,
from the repository root:

```bash
source /opt/ros/humble/setup.bash
sudo apt update
sudo apt install python3-colcon-common-extensions python3-rosdep python3-pytest \
  ros-humble-navigation2 ros-humble-nav2-bringup ros-humble-robot-localization \
  ros-humble-camera-calibration ros-humble-rviz2
# Run sudo rosdep init once if rosdep has not already been initialized.
rosdep update
rosdep install --from-paths src --ignore-src -r -y --rosdistro humble
colcon build --symlink-install
source install/setup.bash
python3 -m pytest -q
```

ROS binaries follow Humble distribution updates rather than an immutable lock.
Before hardware trials, record `dpkg-query -W 'ros-humble-*'` and `pip freeze`
alongside the JetPack, CUDA and TensorRT versions. No NVIDIA Python packages
are installed automatically: use wheels compatible with the actual device.

## First run

1. Connect the camera driver and calibration using [hardware setup](docs/hardware.md).
2. Launch `ros2 launch dubdash stereo.launch.py` and inspect `/stereo/points2`
   in RViz. Exact timestamp synchronization is the default; mismatched capture
   timestamps produce no stereo output. Approximate sync cannot repair capture skew.
3. With valid camera transforms, launch `ros2 launch dubdash mapping.launch.py`.
   RTAB-Map owns `odom → base_link` in this visual-only mode; do not start another
   publisher of that transform. Its database uses the upstream default location.
4. Launch `ros2 launch dubdash guard.launch.py` to inspect zero command output.
   It intentionally stays disabled and has no health publisher in this starter.

### Optional person detection

Install a tested Ultralytics release and Jetson-compatible PyTorch in your
hardware environment, then provide a local nano model trained with a `person`
class. Weights and TensorRT engines are excluded from git. Review the model's
license before distribution. Export an engine on the target Jetson, then use:

```bash
ros2 run dubdash person_detector --ros-args \
  -p model:=/absolute/path/to/model.engine \
  -r image:=/stereo/left/image_rect
```

The adapter publishes `/people` with image timestamps and pixel boxes. It does
not estimate person distance or publish health. Depth association and temporal
tracking are pending. Inference performance must be measured on the Orin.

## Navigation integration

Read [the integration plan](docs/navigation.md) before connecting motors.
Nav2 and Collision Monitor are upstream dependencies; full navigation launch,
robot dimensions, ground filtering, localization fusion and motor drivers must
be supplied and tested for the actual robot. No route or fake calibration is
provided.

## Development

Tests run without ROS using Python, pytest and the webcam dependencies:

```bash
python3 -m pip install pytest==8.3.5 -r requirements-webcam.txt
python3 -m pytest -q
python3 -m compileall -q src scripts
```

See [the four-week plan](docs/milestones.md). Project license is undecided;
`UNLICENSED` is a placeholder, not a grant of redistribution rights.

## Upstream references

- [ROS 2 Humble installation](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)
- [Humble stereo image processing](https://github.com/ros-perception/image_pipeline/tree/humble/stereo_image_proc)
- [RTAB-Map ROS](https://github.com/introlab/rtabmap_ros/tree/ros2)
- [Nav2 Humble Collision Monitor API](https://api.nav2.org/nav2-humble/html/classnav2__collision__monitor_1_1CollisionMonitor.html)
- [Ultralytics Jetson deployment](https://docs.ultralytics.com/guides/nvidia-jetson/)
- [Waveshare IMX219-83 stereo camera](https://www.waveshare.com/wiki/IMX219-83_Stereo_Camera)
