#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

usage() {
    cat <<'GUIDE'
Usage: bash scripts/mapping_docker.sh COMMAND [options]
  start                Build/start browser desktop at http://localhost:6080/vnc.html?autoconnect=true&resize=remote
  fetch                Download stereo passes A and B into persistent Docker storage
  map [options]        Start mapping (leave terminal open; Ctrl+C saves the map)
  play A|B [options]   Replay a recording, initially paused; Space starts/pauses
  localize [options]   Localize against a copy of the saved map
  goal [options]       Show graph route, default destination node 1
  shell                Open a ROS-enabled container terminal
  status               Show desktop health
  stop                 Stop container; preserve data and saved maps
GUIDE
}

if ! command -v docker >/dev/null 2>&1; then
    echo 'Install Docker Desktop for Apple Silicon first.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo 'Open Docker Desktop and wait until its engine is running, then retry.' >&2
    exit 1
fi

command_name="${1:-}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command_name" in
    start)
        docker compose up --build -d --wait --wait-timeout 120
        echo 'Open http://localhost:6080/vnc.html?autoconnect=true&resize=remote'
        ;;
    stop) docker compose stop ;;
    status) docker compose ps ;;
    shell) docker compose exec mapping bash -i ;;
    fetch) set -- fetch --session both "$@" ;;
    map|localize|goal) set -- "$command_name" "$@" ;;
    play)
        session="${1:-A}"
        if [[ $# -gt 0 ]]; then shift; fi
        if [[ "$session" != A && "$session" != B ]]; then
            echo 'Choose recording A or B.' >&2
            exit 1
        fi
        set -- play "data/rtabmap/stereo_outdoor${session}_bag" "$@"
        ;;
    *) usage; exit 1 ;;
esac
case "$command_name" in
    fetch|map|localize|goal|play)
        docker compose exec mapping bash -lc \
            'source /opt/ros/humble/setup.bash; source /workspace/install/setup.bash; cd /workspace; exec python3 scripts/mapping_demo.py "$@"' \
            bash "$@"
        ;;
esac
