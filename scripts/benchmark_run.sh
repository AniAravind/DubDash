#!/usr/bin/env bash
# Run from an ordinary authorized host terminal; no sudo or Docker permission changes.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
scenario=${1:?Usage: bash scripts/benchmark_run.sh vo|slam|yolo|vo-yolo|full RATE SECONDS}
rate=${2:-1}
seconds=${3:-60}
case "$scenario" in vo|slam|yolo|vo-yolo|full) ;; *) exit 2 ;; esac
# Fail before starting telemetry if Docker access or required mounts are unavailable.
docker compose -f compose.yaml -f compose.benchmark.yaml exec -T mapping test -f /benchmark-scripts/benchmark.py
run="${scenario}-$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -p benchmark-runs
python3 scripts/benchmark_resources.py --output "benchmark-runs/${run}-resources" \
  --seconds "$(python3 -c 'import sys; print(float(sys.argv[1])+70)' "$seconds")" &
resource_pid=$!
trap 'kill "$resource_pid" 2>/dev/null || true; wait "$resource_pid" 2>/dev/null || true' EXIT
docker compose -f compose.yaml -f compose.benchmark.yaml exec -T \
  -e ROS_DOMAIN_ID=43 -e ROS_LOCALHOST_ONLY=1 \
  -e PYTHONPATH=/benchmark-src/dubdash:/benchmark-src/dubdash_replay \
  mapping bash -lc 'source /opt/ros/humble/setup.bash; source /workspace/install/setup.bash; exec python3 /benchmark-scripts/benchmark.py "$@"' \
  bash "$scenario" --rate "$rate" --seconds "$seconds" --output "/benchmark-runs/$run"
