#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /workspace/install/setup.bash
set -u
cd /workspace
export PYTHONPATH="/workspace/scripts:${PYTHONPATH:-}"
export DUBDASH_REQUIRE_ROS=1
python3 -m compileall -q src scripts tests
# Use the installed ROS overlay; Ubuntu's pytest predates pytest.ini's pythonpath.
python3 -m pytest -c /dev/null -q tests
ros2 launch dubdash stereo.launch.py --show-args
ros2 launch dubdash mapping.launch.py --show-args
ros2 launch dubdash_replay replay_mapping.launch.py --show-args
