# CPU ROS userspace; inference runs in the separately qualified Jetson host worker.
FROM ros:humble-ros-base-jammy
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
WORKDIR /workspace
COPY src/dubdash src/dubdash
RUN apt-get update && apt-get install -y --no-install-recommends python3-colcon-common-extensions python3-rosdep \
    && rosdep update --rosdistro humble \
    && rosdep install --from-paths src --ignore-src -r -y --rosdistro humble \
    && source /opt/ros/humble/setup.bash && colcon build --symlink-install \
    && source install/setup.bash \
    && ros2 launch dubdash navigation.launch.py --show-args \
    && ros2 launch dubdash robot.launch.py --show-args \
    && rm -rf /var/lib/apt/lists/*
COPY docker/robot/entrypoint.sh /robot-entrypoint.sh
ENTRYPOINT ["/bin/bash", "/robot-entrypoint.sh"]
