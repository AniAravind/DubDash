FROM ros:humble-ros-base-jammy

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-colcon-common-extensions python3-rosdep python3-pytest \
    ros-humble-rtabmap-ros ros-humble-rviz2 ros-humble-image-pipeline \
    ros-humble-image-transport-plugins ros-humble-rosbag2 \
    xvfb x11-utils x11vnc openbox xterm novnc websockify supervisor tini \
    libgl1-mesa-dri libglx-mesa0 mesa-utils dbus-x11 fonts-dejavu-core \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY src/ src/
# rosdep is initialized in the ROS base image. Resolve only this workspace's needs.
RUN apt-get update && rosdep update --rosdistro humble \
    && rosdep install --from-paths src --ignore-src -r -y --rosdistro humble \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/ scripts/
COPY tests/ tests/
COPY pytest.ini README.md ./
COPY docs/ docs/
RUN source /opt/ros/humble/setup.bash && colcon build --symlink-install \
    && source install/setup.bash \
    && PYTHONPATH="/workspace/scripts:${PYTHONPATH}" python3 -m pytest -c /dev/null -q tests/test_mapping_demo.py tests/test_guard.py \
    && ros2 launch dubdash_replay replay_mapping.launch.py --show-args

RUN useradd --create-home --uid 1000 --shell /bin/bash demo \
    && mkdir -p /workspace/data /workspace/maps /home/demo/.config/openbox /home/demo/.ros \
    && chown -R demo:demo /workspace /home/demo
COPY docker/mapping/entrypoint.sh /usr/local/bin/dubdash-desktop
COPY docker/mapping/terminal.sh /usr/local/bin/dubdash-terminal
COPY docker/mapping/menu.xml /home/demo/.config/openbox/menu.xml
COPY docker/mapping/supervisord.conf /etc/supervisor/dubdash.conf
RUN chmod +x /usr/local/bin/dubdash-desktop /usr/local/bin/dubdash-terminal \
    && printf '\nsource /opt/ros/humble/setup.bash\nsource /workspace/install/setup.bash\ncd /workspace\n' >> /home/demo/.bashrc

ENV DISPLAY=:99 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    QT_X11_NO_MITSHM=1 \
    ROS_DOMAIN_ID=42 \
    ROS_LOCALHOST_ONLY=1 \
    PYTHONUNBUFFERED=1
USER demo
EXPOSE 6080
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:6080/vnc.html >/dev/null && DISPLAY=:99 xdpyinfo >/dev/null
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dubdash-desktop"]
