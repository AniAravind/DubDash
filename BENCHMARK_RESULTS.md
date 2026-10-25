# DubDash perception benchmarking — development and verified results

Date: 2026-10-25. **GPU inference and SLAM workload measurements remain blocked by sandbox access.** The implementation below is prepared, with CPU unit tests passing; it has not been built or validated on the GPU. No claim of real-time robotics suitability can yet be made.

## Verified environment and access

Read-only checks observed:

- Device tree: NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super.
- ARM64, Ubuntu 24.04.4, kernel `6.8.12-1021-tegra`; Python 3.12.3.
- Jetson Linux R39 revision 2.1 (`/etc/nv_tegra_release`). This agrees with NVIDIA's [JetPack 7.2.1 release information](https://developer.nvidia.com/embedded/jetpack/downloads).
- CUDA runtime package `cuda-cudart-13-2` version `13.2.86-1`.
- TensorRT runtime `libnvinfer10` version `10.16.2.10-1+cuda13.2`; loading the shared library and calling `getInferLibVersion()` returned `101602`.
- `apt-cache policy` confirms matching `python3-libnvinfer` and `libnvinfer-bin` candidates in NVIDIA's configured `jetson/common r39.2` repository.
- NumPy and pytest are available. Host Python has no TensorRT bindings, PyTorch, Ultralytics, OpenCV, or ROS. `trtexec` is not installed at `/usr/src/tensorrt/bin/trtexec`.
- Docker socket connection is denied. No `/dev/nv*` devices are visible in the sandbox. CUDA driver `cuInit(0)` returns **100**, device query returns **100**, count **0**, with nvmap initialization errors. This proves inference is unavailable in this session, not that the hardware is defective. The user reports successful GPU and Docker access outside the sandbox.
- The dataset and saved database are in Docker persistent volumes, inaccessible here. Their sizes/content could not be independently verified.

Raw checks: `benchmark-runs/verified-sandbox/preflight.json` and `preflight.stderr`. No sandbox bypass, socket permission changes, sudo, host package installation, security changes, reboot, or destructive operation was attempted.

## Actual measured baseline

A separate **10-second host telemetry baseline**, with no benchmark workloads launched by this session, recorded ten samples. Other host activity was not controlled. These are whole-system readings, not detector/SLAM measurements.

| Metric | Mean | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| CPU busy, aggregate across cores (%) | 6.37 | 5.83 | 11.91 | 14.30 |
| GPU busy, tegrastats GR3D (%) | 0 | 0 | 0 | 0 |
| RAM used, MemTotal−MemAvailable (MiB) | 3573.11 | 3573.03 | 3577.92 | 3578.22 |
| GPU temperature (°C) | 43.92 | 43.95 | 44.07 | 44.09 |
| Swap used (KiB) | 0 | 0 | 0 | 0 |

Raw samples, raw tegrastats and statistics: `benchmark-runs/verified-sandbox/baseline/`. Memory usage includes all host processes; Jetson GPU allocations share system RAM. This short baseline cannot establish throttling behavior under load.

## Workload results

| Scenario | New workload measurements | Status |
|---|---|---|
| A: stereo VO, 0.5× / 1× / faster | None | Docker and recording access blocked |
| B: YOLO alone, FPS / inference latency | None | GPU devices, engine build, bindings and Docker blocked |
| C: VO + YOLO | None | Same access limits |
| D: RTAB-Map + VO + YOLO | None | Same access limits |
| SLAM + VO without detector | None | Docker and recording access blocked |

Previously supplied observations were approximately **5.2 Hz VO** and **0.45 Hz RTAB-Map information** during 0.5× replay. Those numbers were not reproduced here and are not maximum throughput results. No person detections on stereo frames or public images were verified in this session. No detection-quality or latency measurement is inferred from unit tests.

## Implemented changes

- The existing detector still supports local Ultralytics `.pt` / `.engine` models. It now also supports a local HTTP worker without importing Ultralytics in the ROS environment. It publishes annotated images, `Detection2DArray`, and JSON metrics, and can write a new exclusive JSONL file. Metrics include inference milliseconds, worker/predict duration, full callback duration, successful detection FPS, input stamp, frame ID, detection count and warmup flag. Camera subscription keeps the newest available image (depth one, best effort).
- `scripts/trt_worker.py` uses TensorRT 10.16 and CUDA runtime directly, avoiding GPU PyTorch. Static batch-one YOLOv8 COCO exports only: NCHW input, `[1,84,N]` output, no embedded NMS. It letterboxes, normalizes RGB, maps person boxes back to source coordinates, clips and applies CPU NMS. Inference timing synchronizes the CUDA stream before and after enqueue; it includes submission/completion overhead and scheduling contention, excludes host/device copies, JPEG decoding, preprocessing and NMS. Worker timing includes preprocessing, transfers and NMS but excludes HTTP/JPEG decoding. This is **untested GPU code**.
- `docker/inference/Dockerfile` targets Ubuntu 24.04 and pins TensorRT packages to the observed JetPack version. It installs the CUDA runtime rather than a complete CUDA SDK. `Dockerfile.export` is an optional disposable CPU exporter if an ONNX file is unavailable. Both builds remain unverified.
- `compose.benchmark.yaml` is opt-in. It retains the original mapping image and named volumes. The worker shares the mapping container's network namespace and listens on loopback; it exposes no additional host port. Models mount read-only during inference. No host networking is required, and `ROS_LOCALHOST_ONLY=1` is retained.
- Replay launch gains `pipeline:=decode|vo|slam`, defaulting to existing SLAM behavior. VO-only starts stereo odometry without RTAB-Map; YOLO-only bag replay decodes the left image without VO/SLAM.
- `benchmark.py` launches only its own process groups, records image/VO/info/detection arrivals and stamp correlations, checks for startup exits and missing streams, and saves JSON summaries. It uses exclusive new output directories and a new `map.db` inside each run; the saved stereo map is never selected. `benchmark_run.sh` collects host resources alongside each run. `benchmark_yolo.py` repeatedly requests inference on an explicit image to measure saturation separately from playback limits.

The pre-existing modifications to `compose.yaml` and `compose.yaml.backup` were preserved. No image, volume, recording or saved map was modified by this session.

## Tests completed in the sandbox

Run from the repository root:

```bash
python3 -m pytest -q
python3 -m compileall -q scripts src
bash -n scripts/benchmark_run.sh
git diff --check
python3 scripts/benchmark.py full --output /tmp/dubdash-benchmark-dry-run --dry-run
```

Tests cover statistics including empty/invalid samples and p50/p95/p99 interpolation; scenario commands and sensor-only playback; output overwrite refusal; dry-run without ROS; synthetic person filtering and letterbox coordinate inversion; the actual detector callback with fake ROS/HTTP interfaces, including annotation publication, stamp preservation and warmup metrics; and the actual engine predict path with mocked CUDA, verifying synchronization around enqueue and timing boundaries. OpenCV NMS, CUDA, TensorRT execution and ROS transport are **not** validated by mocks.

**38 tests passed** in the final unit-test run; see `benchmark-runs/verified-sandbox/pytest.txt`. The opt-in Compose configuration also passed `docker compose ... config --quiet` locally without daemon access. The dry-run artifact is `full-dry-run.json`. Container builds, engine export, TensorRT numerical correctness, ROS launch compatibility, real NMS behavior and complete pipeline shutdown/database saving still require execution outside this sandbox.

## Commands for the remaining GPU benchmarks

Run these in an ordinary authorized terminal on the Jetson, **outside this sandbox**, from `~/DubDash`. They require the already-working Docker/NVIDIA runtime; they do not change socket permissions or host security. Run one benchmark at a time. The benchmark uses ROS domain 43 for its own processes, separate from the desktop's default domain 42.

### Prepare the separate worker

```bash
mkdir -p models benchmark-runs
python3 scripts/benchmark_preflight.py > benchmark-runs/host-preflight.json
# This validates YAML without contacting the Docker daemon.
docker compose -f compose.yaml -f compose.benchmark.yaml config --quiet
docker compose -f compose.yaml -f compose.benchmark.yaml build inference
```

If a suitable **static YOLOv8n COCO ONNX without NMS** already exists, put it in `models/yolov8n.onnx` and skip the exporter. Otherwise the optional disposable export image downloads CPU PyTorch and Ultralytics; it is larger than the runtime and is not needed for normal inference. Export downloads YOLOv8n weights if absent. Use an empty models directory for this step; export can overwrite existing ONNX outputs, so the guard refuses that situation.

```bash
test ! -e models/yolov8n.onnx
docker build -f docker/inference/Dockerfile.export -t dubdash-yolo-export:cpu .
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/models:/models" dubdash-yolo-export:cpu \
  python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640, batch=1, dynamic=False, simplify=False, nms=False, opset=17, device='cpu')"
```

Build the raw FP16-enabled plan **on this Jetson**, not another architecture or TensorRT release. `--fp16` allows mixed precision; it does not guarantee every layer executes in FP16. The worker deliberately accepts raw plans rather than Ultralytics metadata-prefixed `.engine` files. Save builder output and image identity with the run:

```bash
test ! -e models/yolov8n-640-fp16.engine
set -o pipefail
docker run --rm --runtime=nvidia --gpus all --user "$(id -u):$(id -g)" \
  -v "$PWD/models:/models" --entrypoint /usr/src/tensorrt/bin/trtexec \
  dubdash-inference:jp721 --onnx=/models/yolov8n.onnx \
  --saveEngine=/models/yolov8n-640-fp16.engine --fp16 \
  --memPoolSize=workspace:512 --skipInference \
  2>&1 | tee benchmark-runs/build-640-fp16.log
sha256sum models/yolov8n.onnx models/yolov8n-640-fp16.engine > benchmark-runs/model-sha256.txt
docker image inspect dubdash-inference:jp721 > benchmark-runs/inference-image.json
```

For FP32, omit `--fp16` and use a new output filename. For 320 resolution, export a new static ONNX with `imgsz=320` in a separate directory, build a separately named plan, and update the overlay's engine command. Never label a 640 static engine as 320 merely by changing an application parameter. Match both precision/resolution configurations against the same source imagery.

Start the mapping service with benchmark mounts and the worker. Adding mounts may recreate the mapping container; stop active demos cleanly first. Named volumes remain unchanged. This does not rebuild the mapping image.

```bash
docker compose -f compose.yaml -f compose.benchmark.yaml up -d --no-build mapping inference
docker compose -f compose.yaml -f compose.benchmark.yaml logs inference
docker compose -f compose.yaml -f compose.benchmark.yaml exec -T mapping \
  python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8090/').read().decode())"
```

A successful health response establishes engine deserialization, not successful inference. The next commands perform actual inference. `trtexec` also confirms CUDA/TensorRT operation independently of the HTTP/ROS bridge:

```bash
docker run --rm --runtime=nvidia --gpus all --user "$(id -u):$(id -g)" \
  -v "$PWD/models:/models:ro" -v "$PWD/benchmark-runs:/benchmark-runs" \
  --entrypoint /usr/src/tensorrt/bin/trtexec dubdash-inference:jp721 \
  --loadEngine=/models/yolov8n-640-fp16.engine --warmUp=2000 --duration=60 \
  --exportTimes=/benchmark-runs/trtexec-640-fp16-times.json \
  2>&1 | tee benchmark-runs/trtexec-640-fp16.log
```

`trtexec` uses generated inputs, not real images; it is a compute benchmark, not evidence of person detection. Stop the idle HTTP worker during this test if memory use is material (`docker compose -f compose.yaml -f compose.benchmark.yaml stop inference`), then start it again for image tests.

### Validate real people and saturate the worker

For a clearly separate public-image test, fetch [Ultralytics' bus image](https://github.com/ultralytics/assets/blob/main/im/bus.jpg) to a new file. This is not a frame from the stereo recording. The output reports boxes/scores but detection quality must still be checked against the image, ideally through the annotated ROS view.

```bash
test ! -e benchmark-runs/public-bus.jpg
curl -fL https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg -o benchmark-runs/public-bus.jpg
docker compose -f compose.yaml -f compose.benchmark.yaml exec -T \
  -e PYTHONPATH=/benchmark-src/dubdash mapping \
  python3 /benchmark-scripts/benchmark_yolo.py \
  --image /benchmark-runs/public-bus.jpg --warmup 20 --samples 300 \
  --output /benchmark-runs/yolo-public-640-fp16.jsonl \
  | tee benchmark-runs/yolo-public-640-fp16-summary.json
```

Collect resources in another terminal during this saturation test:

```bash
python3 scripts/benchmark_resources.py --seconds 90 --output benchmark-runs/yolo-public-resources
```

All output directories/JSONL filenames must be new for reruns. The JSONL contains detections per image and timing samples. `sustained_fps` includes sequential HTTP requests and JSONL logging; `sequential_request_fps` excludes between-request logging. Both include JPEG decode and transport in each request. Neither is the engine-only FPS. Inference/worker/request means and p50/p95/p99 are reported separately.

### Playback workloads

The recorded bag must already exist at `/workspace/data/rtabmap/stereo_outdoorA_bag`. Run the same 60-second **wall-clock** window for each scenario/rate:

```bash
bash scripts/benchmark_run.sh vo 0.5 60
bash scripts/benchmark_run.sh vo 1 60
bash scripts/benchmark_run.sh slam 0.5 60
bash scripts/benchmark_run.sh slam 1 60
bash scripts/benchmark_run.sh yolo 0.5 60
bash scripts/benchmark_run.sh yolo 1 60
bash scripts/benchmark_run.sh vo-yolo 0.5 60
bash scripts/benchmark_run.sh vo-yolo 1 60
bash scripts/benchmark_run.sh full 0.5 60
bash scripts/benchmark_run.sh full 1 60
```

If 1× remains healthy, repeat VO/YOLO/combined/full at rate 2 and then higher rates within the bag's duration; do not call publication FPS maximum compute throughput unless input demand exceeds processing capacity. For comparisons over identical content, keep `rate × wall_seconds` constant instead (e.g. 0.5× for 120 s, 1× for 60 s, 2× for 30 s). Repeat runs to assess variability, then use longer steady-state/thermal runs. A 236-second bag at 2× ends after approximately 118 wall seconds.

The annotated bag stream is `/image_annotated`, people messages `/benchmark/people`, timing messages `/metrics`; these use benchmark domain 43. View from a domain-43 ROS terminal in the existing desktop:

```bash
docker compose -f compose.yaml -f compose.benchmark.yaml exec \
  -e ROS_DOMAIN_ID=43 mapping bash -lc \
  'source /opt/ros/humble/setup.bash; ros2 run rqt_image_view rqt_image_view /image_annotated'
```

Run directories contain `manifest.json`, logs, raw `arrivals.jsonl`, optional `detector.jsonl`, `summary.json`, and a new SLAM database where applicable. Adjacent resource directories contain whole-host telemetry. Graceful shutdown allows map saving; timeout escalation is recorded in `summary.json` and marks the run failed; check this before using any run database. None of these commands targets `/workspace/maps/stereo-demo.db`.

## Measurement interpretation and remaining limits

- Topic FPS uses `perf_counter` elapsed wall time, never bag timestamps. Recorded stamp spans and unique-stamp counts are reported separately. Initial discovery/startup and playback cutoff affect these rates.
- Inference timing brackets enqueue with stream synchronization. It excludes transfers; HTTP callback/request timing includes additional work. GPU CUDA-event timing could further separate kernel time from host overhead after hardware validation. Local Ultralytics mode reports its inference-stage timer and a separately synchronized total predict time; the native worker is preferred for the new environment.
- The first ten detector frames and first twenty saturation requests are marked/excluded from their latency summaries. Topic rates and observer latency still include startup/warmup. Percentiles interpolate sorted raw samples.
- Observer end-to-end latency correlates the source stamp from receipt of the decoded left image to receipt of the corresponding detection. It includes ROS delivery, queuing, bridge and inference, but excludes capture, bag storage and image decoding before the observer. DDS callback ordering can prevent matching; unmatched and tail frames are reported rather than fabricated as latency samples. This is not physical camera-to-actuator latency.
- Camera/left/VO/detection stamp differences are **observed unmatched frames**, not confirmed DDS drops. They include intentional latest-frame skipping, missed observer callbacks, warmup/startup and unfinished tail work. No DDS transport-loss claim is made.
- HTTP JPEG encoding and CPU NMS add CPU cost and lossy image compression. Confirm detection quality on both public people imagery and the actual recording. A recording with no people can verify transport and throughput, not person recall.
- Monitor resource logs for rising temperature, reduced clocks, swap use, GPU busy saturation and growing latency under combined load. No thermal-throttling conclusion is justified from the baseline. The runner's resource window includes setup/shutdown, so align its raw monotonic timestamps with `measurement_started_monotonic_s` in the workload summary for steady-state comparisons.

## Conclusions and optimization priorities

The verified blocker is sandbox access; TensorRT runtime presence alone does not establish usable GPU inference. The separate container design avoids installing Ubuntu 24.04 TensorRT/PyTorch dependencies into the working Ubuntu 22.04 ROS environment. Runtime compatibility, launch behavior and all workload performance remain to be tested.

For a slow-moving robot, establish an explicit perception deadline based on speed, stopping distance and sensing range before declaring the pipeline sufficient. No such suitability claim can be made from the available measurements. Start with YOLOv8n at 640 FP16, compare 320 FP16 and FP32 accuracy/latency, then consider detector rate limiting, skipping annotation when unused, eliminating JPEG round trips with shared-memory transport, or reducing RTAB-Map update frequency if the measured bottleneck warrants it. Keep low-latency latest-frame processing and measure unmatched frames alongside latency; a high output FPS alone is insufficient.
