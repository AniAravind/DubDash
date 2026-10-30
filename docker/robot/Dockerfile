# CPU ROS userspace; inference runs in the separately qualified Jetson host worker.
FROM ros:humble-ros-base-jammy
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace
COPY src/dubdash/package.xml /tmp/robot-manifest/dubdash/package.xml
RUN apt-get update && apt-get install -y --no-install-recommends python3-colcon-common-extensions python3-rosdep \
    && rosdep update --rosdistro humble \
    && rosdep install --from-paths /tmp/robot-manifest --ignore-src -r -y --rosdistro humble \
    && rm -rf /var/lib/apt/lists/*
COPY src/dubdash src/dubdash
COPY scripts/robot_preflight.py scripts/robot_preflight.py
RUN source /opt/ros/humble/setup.bash && colcon build --symlink-install \
    && source install/setup.bash \
    && ros2 launch dubdash navigation.launch.py --show-args \
    && ros2 launch dubdash robot.launch.py --show-args
COPY docker/robot/entrypoint.sh /robot-entrypoint.sh
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
ENTRYPOINT ["/bin/bash", "/robot-entrypoint.sh"]
