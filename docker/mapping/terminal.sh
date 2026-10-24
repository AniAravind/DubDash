#!/usr/bin/env bash
set -eo pipefail
# Wait until Xvfb accepts connections; supervisor priority is not a readiness check.
for attempt in {1..60}; do
    if xdpyinfo -display :99 >/dev/null 2>&1; then break; fi
    sleep 0.5
done
exec xterm -fa 'DejaVu Sans Mono' -fs 12 -geometry 105x30+20+20 \
    -title 'DubDash Mapping - Start Here' -e bash -ic '
cat <<"GUIDE"
DubDash mapping desktop (ROS 2 Humble)

First download the recordings (about 1.64 GB):
  python3 scripts/mapping_demo.py fetch --session both

Start mapping in this terminal:
  python3 scripts/mapping_demo.py map

Open another terminal: right-click desktop -> Terminal, then:
  python3 scripts/mapping_demo.py play data/rtabmap/stereo_outdoorA_bag
  Press Space in the replay terminal to start/pause.

When replay finishes, Ctrl+C in the mapping terminal saves the map.
For pass B and localization, see docs/docker-mapping.md.
Use a new --database maps/another.db to start another map.
GUIDE
exec bash -i
'
