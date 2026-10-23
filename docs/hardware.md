# Hardware integration

Record the Orin model, JetPack release, camera driver, image size, frame rate,
camera baseline, wheel radius, wheel separation and encoder counts per revolution.
No camera or motor driver is selected until those interfaces are known.

## Camera contract

Driver must publish `sensor_msgs/Image` and matching `sensor_msgs/CameraInfo`:

- `/stereo/left/image_raw`, `/stereo/left/camera_info`
- `/stereo/right/image_raw`, `/stereo/right/camera_info`

The upstream image_proc launch includes debayer and rectification. Confirm
`image_rect` and `image_rect_color` are published before inspecting disparity
and colored point clouds; use supported mono8, bgr8 or Bayer encodings.
Calibrate both cameras together at the intended resolution with ROS camera
calibration, save the YAML under `calibration/`, and configure the driver to load
it. Right projection matrix must encode the measured stereo baseline. Confirm
images and camera info share capture timestamps and appropriate optical frames.
Calibration data is ignored because it is specific to each robot.

Publish measured transforms from `base_link` through the camera mounts to both
optical frames; optical axes are x right, y down, z forward. Never use guessed
baseline or mounting transforms for driving.

The IMX219-83 lacks hardware synchronization. Record a moving target and a moving
robot, compare disparity and known distances, and quantify failure rate in sun,
shadow and low texture. Exact timestamp matching does not prove simultaneous
exposure. Switch cameras if the measured error exceeds the stopping budget.

## Motor contract

Motor adapter consumes only `/cmd_vel` (`geometry_msgs/Twist`) and publishes
`/wheel/odom` (`nav_msgs/Odometry`) with measured covariances. It must stop on
command timeout independently of ROS and reject nonfinite/out-of-range commands.
Provide a physical emergency stop. Keep the wheels lifted for initial checks.

The Python command guard cannot stop a stalled host or a failed motor controller.
No motor adapter is included because the controller protocol is unspecified.

## Record a calibration trial

```bash
ros2 bag record -o trial_stereo /stereo/left/image_raw \
  /stereo/right/image_raw /stereo/left/camera_info /stereo/right/camera_info \
  /wheel/odom /tf /tf_static
```

Store bag directories outside the repository. Replay only with motors disconnected
and set `use_sim_time` on consumers when using `ros2 bag play --clock`.
