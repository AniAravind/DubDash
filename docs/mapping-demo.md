# RTAB-Map recorded-stereo demo

Watch **stereo visual odometry, map construction, loop closure and saved-map
localization** without a phone, robot or physical cameras. This is a real ROS 2
RTAB-Map pipeline using the project's published outdoor stereo recordings.
It runs in the development-only `dubdash_replay` package, separate from the robot runtime.

## What appears on screen

RViz opens with a 3D reconstructed scene, occupancy map, stereo odometry,
optimized recorded trajectory (green), and localized position. An optional
route to a selected graph node appears in yellow. The green line is where the
recorded camera travelled; the yellow line is a route along learned graph
connections, not a live obstacle-aware or guaranteed shortest safe walking path.

Pass **A builds the map**. Pass **B is another recording used to test localization
against that saved map**. Finding a match is not guaranteed at every frame; image
overlap, texture and odometry quality matter. No motor driver or Nav2 controller
is started, and recorded velocity commands are excluded from replay.

On a Mac, [the Docker browser desktop](docker-mapping.md) packages this environment
without a manually configured VM. Use that guide for Mac-side commands.

## Environment

Run the visualization in an **Ubuntu 22.04 desktop with ROS 2 Humble**, on a Linux
computer, Jetson or a desktop VM on your Mac. The VM needs a working graphical
desktop and enough memory for SLAM; start with 4 CPU cores, 8 GB RAM and at least
8 GB free disk for these bags and maps, then adjust based on workload. Apple
Silicon Macs should use an ARM64 Ubuntu VM.

Native macOS does not provide this ROS 2 Humble environment. This feature
is not a Python-only Mac GUI. Docker Desktop can host ROS, but displaying RViz
requires additional GUI forwarding; a desktop Ubuntu VM is the simpler supported
route for this demo. The repository does not silently install a VM or download
multi-gigabyte data.

After installing ROS 2 Humble using its official Ubuntu instructions, run these
commands **inside Ubuntu**, from this repository's root:

```bash
source /opt/ros/humble/setup.bash
sudo apt update
sudo apt install python3-colcon-common-extensions python3-rosdep \
  ros-humble-rtabmap-ros ros-humble-rviz2 ros-humble-image-pipeline \
  ros-humble-image-transport-plugins ros-humble-rosbag2
# sudo rosdep init only if rosdep has never been initialized.
rosdep update
rosdep install --from-paths src --ignore-src -r -y --rosdistro humble
colcon build --symlink-install
source install/setup.bash
```

The mapping helper uses only Python's standard library, plus the local DubDash
package; it does not need YOLO, PyTorch or a separate vision virtual environment.
Use the system Python in your ROS environment. Source both setup files in every
new ROS terminal. Use a dedicated ROS_DOMAIN_ID if other robots are on the LAN.

## Download and inspect

```bash
python3 scripts/mapping_demo.py fetch --session both
python3 scripts/mapping_demo.py inspect data/rtabmap/stereo_outdoorA_bag
python3 scripts/mapping_demo.py inspect data/rtabmap/stereo_outdoorB_bag
```

The two ZIP files total approximately **1.64 GB** before extraction. Assets are
pinned to release **0.23.13** and SHA-256 digests checked against GitHub's release
metadata during setup. The helper verifies each archive before extraction,
rejects path traversal and links, and checks the required topics. Existing bags
are inspected rather than overwritten. Downloads can take several minutes and
restart from the beginning after interruption. Data is ignored by git.

## First pass: create a map

Terminal 1, from the repository root:

```bash
python3 scripts/mapping_demo.py map --database maps/stereo-demo.db
```

Terminal 2, with the same ROS environment and repository folder:

```bash
python3 scripts/mapping_demo.py play data/rtabmap/stereo_outdoorA_bag
```

Playback starts **paused** at half speed. Wait for RViz and the nodes to start,
then press **Space in Terminal 2** to resume or pause. Use rosbag's keyboard
controls to step when supported by the installed Humble rosbag version. The
playback command emits `/clock`; all processing uses simulated time. It replays
only the stereo images, camera calibration and recorded transforms.

Watch the scene and green trajectory grow. When familiar places are revisited,
loop closure can correct the trajectory. In a third sourced terminal:

```bash
ros2 topic echo /rtabmap/info --once
ros2 topic hz /vo
```

The info message reports mapping/loop-closure results; odometry shows the stereo
motion estimate. A displayed odometry trajectory alone does not prove that loop
closure or localization succeeded. Inspect RTAB-Map's reported matches too.

Let the replay finish, then press **Ctrl+C in Terminal 1 once** and wait for the
nodes to shut down cleanly. RTAB-Map saves to `maps/stereo-demo.db`. The helper
refuses to reuse an existing file in mapping mode. To map again, choose a new name
such as `maps/stereo-demo-2.db`; no `--delete_db_on_start` flag is used.

## Second pass: localize against the saved map

Start a fresh launch so simulated time, odometry and synchronizers reset:

```bash
python3 scripts/mapping_demo.py localize --database maps/stereo-demo.db
```

The helper makes a timestamped SQLite snapshot and opens that copy in
localization mode. The original saved map stays intact. Then, in Terminal 2:

```bash
python3 scripts/mapping_demo.py play data/rtabmap/stereo_outdoorB_bag
```

Press Space once the nodes are ready. Observe localization against the earlier
map, inspect `/rtabmap/info`, and confirm the localized position aligns with
previously mapped areas rather than treating odometry alone as proof of a match.
If B does not relocalize, replay A in localization mode as a same-route baseline.
A same-recording match is a pipeline check, not evidence of robustness to a new
route, lighting or viewpoint.

Do not run mapping and localization launches simultaneously. Stop the player and
all processing nodes before switching passes; looping a bag resets clock time and
can invalidate the current tracking state.

## Optional: show a route through the learned graph

During mapping or after a successful localization, request a path back to the
first saved map node:

```bash
python3 scripts/mapping_demo.py goal --node-id 1
```

This calls RTAB-Map's `set_goal` service. RViz's yellow **Graph route** display
subscribes to `/rtabmap/global_path`. The service returns path IDs/poses if it can
find a connection. An empty response means no path was found; try a valid node
from the current saved graph after localization succeeds. The route changes as
the recorded viewpoint moves; there is no controller that follows the goal.

This is the mapping demo's counterpart to the original “ideal path” idea. It
plans along recorded map connectivity; it does not discover unseen free space,
measure moving obstacles or provide a human walking-safety guarantee.

## Options and troubleshooting

- Add `--rate 0.25` to `play` if stereo processing cannot keep up.
- Add `--headless` to `map` or `localize` to run without RViz.
- Add `--dry-run` to `map`, `localize`, `play` or `goal` to inspect commands without
  starting ROS. `play` still validates its bag; `localize` still validates the map.
- Use `localize --run-database maps/localization-test.db` for an explicit new copy.
- A blank RViz view before playback is normal. Afterwards, confirm `/clock` is
  advancing, check transform errors and inspect `/stereo_camera/left/image_rect`,
  `/stereo_camera/right/image_rect` and `/vo`. Fixed frame is `map`.
- Occupancy can be incomplete for outdoor stereo, especially sky and textureless
  surfaces. Unknown cells are not proof of traversable ground.
- Missing bag topics are reported before launch. MCAP, ROS 1 and arbitrary custom
  bags are not supported by this profile; adapt the topic and frame contracts
  explicitly before using other recordings.
- Restart processing after time jumps, odometry loss or interrupted bag replay.
  Never launch this replay beside a real robot using the same ROS domain.

## Implementation and verification

Compressed stereo → grayscale/debayer → rectification using recorded CameraInfo
→ stereo visual odometry → RTAB-Map graph, scene and occupancy outputs. RTAB-Map
owns `map → odom`; stereo odometry owns `odom → base_footprint`; bag transforms
provide the camera mounting frames. The provided profile follows the upstream
outdoor recording conventions. Do not introduce additional odometry/TF publishers.

Automated checks cover bag topic validation, database protection, localization
snapshots, replay rate and topic selection, archive extraction, checksums, and
launch argument construction. CI builds the package and checks launch argument
loading on Humble. These tests do not prove that the recorded scene maps well.

**Docker validation on the M4 Mac:** the ARM64 image builds, the browser desktop
and RViz start, both recordings download with verified checksums, and a short
pass-A replay produces stereo odometry, an occupancy map and a saved database
with 17 nodes. The saved database can be copied and loaded in localization mode.
A same-recording localization replay then returned a connected 15-node route
back to node 1. Full-length pass-A mapping and independent pass-B relocalization
are still pending. Runtime acceptance for the complete demo is:
a nonempty map/graph is visible; a populated database saves cleanly; pass B reports
localization matches; the original map is unchanged; and an optional goal returns
a connected graph path. No quantitative accuracy claim is made from the smoke run.

References:
[upstream outdoor stereo demo](https://github.com/introlab/rtabmap_ros/blob/ros2/rtabmap_demos/launch/stereo_outdoor_demo.launch.py),
[recorded datasets](https://github.com/introlab/rtabmap_ros/releases/tag/0.23.13),
[RTAB-Map ROS interfaces](https://github.com/introlab/rtabmap_ros/blob/ros2/rtabmap_slam/doc/rtabmap.md),
[ROS 2 Humble installation](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html).
