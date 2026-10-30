# Navigation integration plan

An initial implementation now exists in `navigation.launch.py` and
`robot.launch.py`; see [runtime setup and limitations](robot-navigation.md).
The remaining sections describe integration requirements. The current height-band
adapter does not replace ground-support validation. The supervisor is implemented
but deliberately requires that external validator. Nav2 parameters are generated
from installed Humble defaults plus a measured robot profile.

## Data and transforms

Camera → stereo_image_proc → `/stereo/points2` → validated ground/obstacle filter
→ `/obstacles/points` → Nav2 voxel costmap and Collision Monitor.
Camera → RTAB-Map → map, visual odometry and localization.
Encoders → `/wheel/odom` → optional robot_localization fusion.

Use `map → odom → base_link → camera optical frames`. Exactly one node owns
each transform. When adding fused wheel/visual odometry, disable RTAB-Map's odom
transform publication and feed the fused odometry into mapping. Do not publish
competing wheel, visual and fused transforms.

## Nav2 hardware tuning still required

Start with the installed Humble nav2_bringup parameter file. Measure the footprint,
configure controller limits and stopping distance, and configure both costmaps.
Use a static layer for the saved route map and a voxel layer consuming filtered
`PointCloud2` in a transformable frame. Tune obstacle height relative to the base,
raytracing ranges, inflation, update rate and `track_unknown_space: true`.
Do not feed an unfiltered ground plane directly into the obstacle layer.
Missing depth is unknown: a costmap clearing ray must not be synthesized from an
invalid disparity. Curbs and downward steps require explicit ground-support
validation, which is not implemented here.

Route the complete velocity chain as follows:

`Nav2 → velocity smoother → Collision Monitor → /cmd_vel_guard_input → command_guard → /cmd_vel → motor adapter`

Configure Collision Monitor's `cmd_vel_out_topic` as `cmd_vel_guard_input`,
and its input to match the smoother's output. Ensure no other node publishes
`/cmd_vel`. Configure lifecycle management and stop/slow polygons for the measured
footprint and stopping distance using Humble parameters (some newer Nav2 examples
use different parameter names). The opt-in robot/navigation launches start Nav2;
other launches do not.

## Ground validation and health qualification still required

The implemented supervisor publishes `/perception/healthy` (`std_msgs/Bool`) only
while depth coverage, source timestamp age, localization, transforms and ground
support are valid. Check source capture age, not just message arrival; rosbag
replay can otherwise look live. A Bool heartbeat is only an integration contract,
not proof of correct perception. The external ground validator is still required;
see the runtime guide for its stamped diagnostic contract. No constant-true
publisher is provided.

The guard requires both a command and healthy heartbeat within 250 ms, clamps
planar commands to 0.2 m/s and 0.5 rad/s, and starts disabled. These limits are
initial bench values, not validated braking limits. It does not detect obstacles.
Enabling `enabled` is a bench operator action after independent stops work.

Acceptance trials: unplug the camera, stop the supervisor, kill command producers,
stop the host, obstruct the route, remove valid depth, lose localization, and
exercise the physical stop. Measure actual stopping distance under load. Only
proceed to supervised route rehearsals after every trial passes.
