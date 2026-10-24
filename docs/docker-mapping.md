# Mapping on an M4 Mac with Docker

Docker runs the ARM64 Ubuntu/ROS environment and exposes a Linux desktop in your
Mac browser. Run the commands on this page in **macOS Terminal**, from the
repository folder. Do not run `apt` or source `/opt/ros` on the Mac.

## Start

1. Install [Docker Desktop for Apple Silicon](https://docs.docker.com/desktop/setup/install/mac-install/)
   if needed, open it and wait for the engine to run. Complete any first-run
   setup in Docker Desktop. Start with at least 8 GB of Docker memory if the Mac
   has enough RAM, and leave several GB available for macOS. Allow at least 15 GB
   free disk space for the ROS image, recordings, build cache and maps.
2. Build and start the demo:

```bash
bash scripts/mapping_docker.sh start
```

The first build downloads ROS and desktop packages and can take several minutes.
The image uses native `linux/arm64`, with CPU/software rendering for RViz.
Docker Desktop does not provide the Mac GPU to this container.

3. Open [the mapping desktop](http://localhost:6080/vnc.html?autoconnect=true&resize=remote).
   A Linux terminal shows instructions. You can use either that terminal or the
   Mac helper commands below. Right-click the Linux desktop → **Open ROS terminal**
   for another terminal inside the container.

The desktop is bound only to your Mac's localhost address. No XQuartz, manual
Ubuntu VM, VNC client or ROS installation on macOS is needed. Keep the Docker
engine running while using the demo. The desktop is shared across browser tabs.

## Download and build a map

In a Mac terminal:

```bash
bash scripts/mapping_docker.sh fetch
bash scripts/mapping_docker.sh map
```

The download fetches passes A and B (about 1.64 GB compressed), verifies their
published archive digests and stores them inside Docker's persistent data volume.
The map command starts ROS and RViz in the browser desktop. Leave this terminal
open. In a **second Mac terminal**, from the same repository folder:

```bash
bash scripts/mapping_docker.sh play A
```

Press **Space in that second Mac terminal** to start/pause playback. The browser
shows the scene, occupancy grid, odometry and optimized trajectory. If processing
falls behind, stop and restart the session with slower replay:

```bash
bash scripts/mapping_docker.sh play A --rate 0.25
```

When playback finishes, **Ctrl+C in the map terminal** and wait for ROS to exit.
That saves `maps/stereo-demo.db` inside the container's persistent maps volume.
Re-running `map` refuses to overwrite it; use `map --database maps/second.db` for
a new map.

## Localization and route display

Start a fresh localization session in the first terminal:

```bash
bash scripts/mapping_docker.sh localize
```

Then in the second terminal:

```bash
bash scripts/mapping_docker.sh play B
```

Press Space to start. Localization uses a timestamped copy of the saved map,
preserving the original. In a third terminal, after a successful match:

```bash
bash scripts/mapping_docker.sh goal --node-id 1
```

This requests a route through the learned graph; it does not move a robot or
provide live obstacle avoidance. See [the full replay guide](mapping-demo.md) for
what to look for and how to interpret missing localization/path results.

## Stop, restart and keep maps

Stop the replay and mapping processes cleanly first. Then:

```bash
bash scripts/mapping_docker.sh stop
```

Data and map volumes survive stop/rebuild/recreate. Restart with `start`.
Do not use `docker compose down -v` unless you intend to delete those volumes.
The map files are **not** automatically copied into the Mac checkout's `maps/`.
To export them to a new folder on your Mac:

```bash
mkdir -p outputs/docker-maps
docker compose cp mapping:/workspace/maps/. outputs/docker-maps/
```

Run `bash scripts/mapping_docker.sh shell` for a ROS-enabled Linux shell or
`bash scripts/mapping_docker.sh status` for container health. To inspect desktop
startup errors, use `docker compose logs mapping`.

The welcome terminal can be closed/reopened without stopping the desktop. If the
browser disconnects, refresh the page; running ROS commands continue in their
terminal sessions. If Docker reports an out-of-memory exit, increase Docker's
memory allocation or slow down replay. A healthy desktop alone does not prove
SLAM or localization is succeeding; inspect the RTAB-Map outputs described in
the replay guide.

## Validation on this Mac

The ARM64 image built successfully; HTTP and VNC connection checks passed. A short
recorded pass-A run started RViz, produced stereo visual odometry and an occupancy
map, and saved 17 map nodes. Both dataset archives are already downloaded and
verified in this checkout's Docker data volume. Localization startup against a
snapshot was checked; a same-recording replay returned a connected 15-node graph
route back to node 1. Full mapping and independent pass-B relocalization still
need a complete run. The small `docker-smoke.db` map is a test artifact;
start your own full map with the default `stereo-demo.db` name.

## Known issue from the robot-scope cleanup check

After separating `dubdash_replay` from `dubdash`, both ROS packages build and the
replay components start. In a headless startup/shutdown smoke test, the two
`image_transport/republish` processes exited with signal 11 on SIGINT. RTAB-Map
and stereo odometry shut down cleanly, and RTAB-Map reported a completed database
save. The decoder shutdown crash remains unresolved; do not interpret the build
and startup checks as clean end-to-end shutdown validation. These decoder
processes belong to the recorded-data tools, not the live robot launch.
