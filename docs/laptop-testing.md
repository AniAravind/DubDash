# Laptop development and CI

Run CPU tests on Windows, macOS or Linux before pulling a change onto the Jetson.
The default Docker test uses the Docker engine's native architecture, avoiding
ARM emulation on Intel/AMD laptops. It requires no NVIDIA GPU, model weights,
physical camera, desktop window or downloaded mapping datasets.

## Environment boundary

The team's reported Jetson environment is **ARM64, Ubuntu 24.04, JetPack 7.2.1,
CUDA 13.2 and TensorRT 10.16.2, with ROS 2 Humble inside Docker**. The host OS
and container OS are separate: the existing `docker/mapping/Dockerfile` is based
on `ros:humble-ros-base-jammy` (**Ubuntu 22.04 / Python 3.10**). Laptop tests use
that same ROS userspace; they do not install Humble directly on the host.

The base `compose.yaml` selects NVIDIA runtime/GPU access. The optional
`compose.benchmark.yaml` adds the production TensorRT worker from
`docker/inference/Dockerfile`. Both configurations stay unchanged.
`compose.laptop.yaml` is an explicitly selected override of the base file,
without the benchmark overlay. It resets GPU/device reservations, uses `runc`, hides
NVIDIA devices, removes desktop ports and persistent mounts, and replaces the
desktop entrypoint with tests. Do not apply this override on the robot.

The reported NVIDIA versions are deployment context, not a compatibility claim.
The ARM64 build below validates the existing Humble CPU image, not the Jetson
production image or the compatibility of its NVIDIA libraries with the host.

## Everyday use

Install Docker Desktop on Windows/macOS, or Docker Engine with Compose v2 and
Buildx on Linux. Use **Linux containers**, **Compose 2.30 or newer**, and Bash.
On Windows use Git Bash or WSL2 with Docker Desktop integration; on macOS/Linux
use a regular terminal. Docker Desktop supplies cross-architecture emulation
for the optional ARM64 build. No local ROS installation is needed.

From the checkout, run:

```bash
bash scripts/test_laptop.sh
```

The script validates both Compose configurations, builds the existing Humble
image with the current source, starts the mock service, waits for its HTTP health
check, and runs all Python and ROS integration tests headlessly. Missing ROS is
an error inside the test container. The exit status is nonzero on a failed test.
Logs appear on failure; containers and the temporary network are cleaned up on
success, failure and interruption. Tests use temporary data inside the container
and never mount the checkout's maps, bags, calibration or physical devices.

Each run has its own Compose project, so cleanup does not stop the existing
mapping desktop. Run one test session at a time on a laptop; the cached image tag
is shared. No images are pushed to a registry. Test image and build cache remain.

The first build installs the existing image's ROS/desktop dependencies and can
take several minutes and several GB. Later builds cache OS and ROS dependencies
independently of Python source changes. Tests use twelve synthetic stereo frames
and bounded polling rather than a multi-GB recording or full SLAM session.
Native tests should take seconds; the ROS smoke suite is intended to take under
a minute after building, depending on the laptop. These are targets, not measured
Jetson or laptop benchmarks. ARM64 emulation is never selected automatically on
an x86 laptop during the normal test command.

Optional commands:

```bash
# Configuration only. Setting the platform allows validation without a daemon.
LAPTOP_PLATFORM=linux/amd64 bash scripts/test_laptop.sh config

# Force an architecture when necessary; default comes from the Docker server.
LAPTOP_PLATFORM=linux/arm64 bash scripts/test_laptop.sh
```

For an even faster Python-only check, use Python 3.10 in a local virtual
environment. This includes real loopback HTTP tests but skips the ROS module:

```bash
python -m venv .venv
# macOS/Linux/Git Bash with a POSIX venv:
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q src scripts tests
```

On Windows PowerShell, use `.venv\Scripts\python.exe` instead of `python` after
creating the venv; activation is optional. If your environment restricts the
system temporary directory, pass `--basetemp .cache/pytest-local` to pytest.
That directory is scratch space and pytest may replace its contents.

## Slower ARM64 pre-merge validation

```bash
docker buildx inspect --bootstrap
bash scripts/test_laptop.sh arm64-build
```

This runs `docker buildx build --platform linux/arm64 --load` against the existing
`docker/mapping/Dockerfile`, tags `dubdash-laptop:humble-arm64`, builds both ROS
packages, and runs the existing policy/replay tests and replay launch-argument
check during the image build. It does not run the new ROS integration suite.
On an ARM laptop it runs natively; on x86 it needs a builder advertising ARM64
support. If needed, create a builder once:

```bash
docker buildx create --name dubdash-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

On Linux without ARM emulation, an administrator must configure QEMU/binfmt
first; Docker's documented option is
`docker run --privileged --rm tonistiigi/binfmt --install arm64`.
The test script does not change host binfmt registration automatically.
See [Docker's multi-platform build guide](https://docs.docker.com/build/building/multi-platform/).

To additionally exercise CPU integration under ARM64 emulation after that build:

```bash
LAPTOP_PLATFORM=linux/arm64 LAPTOP_TEST_IMAGE=dubdash-laptop:humble-arm64 \
  LAPTOP_SKIP_BUILD=1 bash scripts/test_laptop.sh
```

`LAPTOP_SKIP_BUILD=1` is for a just-built image (also used by CI). Normal developers
should omit it so stale source cannot accidentally pass the tests.

## What is tested

| Check | Native Python | Native Docker / CI | ARM64 image build |
| --- | --- | --- | --- |
| Existing command policy, replay contracts, archive and map handling | Yes | Yes | Yes |
| Synthetic TensorRT decoder and benchmark timing contracts (no GPU execution) | Yes | Yes | No |
| HTTP request/response validation, mock opt-in, invalid input, timeout, server error and disconnected worker | Yes | Yes | No |
| Real ROS command topics, startup stop, enabling/disabling, clamping, stale command/health, unhealthy stop | No | Yes | No |
| Generated stereo rosbag played by `ros2 bag play` | No | Yes | No |
| Production stereo launch: rectification, disparity and point-cloud messages | No | Yes | No |
| Image pixels, dimensions, encoding, timestamps and optical frame propagation | No | Yes | No |
| Detector node to separate mock service over HTTP, person filtering and annotated image | No | Yes | No |
| Both ROS packages build and replay launch arguments resolve | No | Yes | Yes |
| ARM64 OS packages and Python/ROS build steps execute | No | Only on ARM hosts | Yes |

The stereo test checks the known synthetic disparity and point-cloud schema; it
does not establish real-world depth accuracy. The synthetic recording uses test
calibration and is intentionally unsuitable for hardware. It exercises the live
stereo launch, not the compressed outdoor replay launch or full RTAB-Map SLAM.
Existing replay unit tests check that recorded motion commands are excluded.

## Mock worker and HTTP contract

The production worker uses JPEG requests with `Content-Type: image/jpeg` and an
`X-Confidence` header, returning `boxes` with pixel `xyxy`, `score`, `label`,
`inference_ms` and `worker_ms`. The mock supports that interface at `/` and the
ROS integration suite tests the existing `endpoint` detector parameter against
it, preserving production timing instrumentation and the local YOLO backend.
Mock responses identify `backend: mock` and require `allow_mock_inference:=true`.
Their `inference_ms` is null: these are not GPU benchmark results.

An additional **version 1** raw-pixel JSON contract is available through the
optional `inference_url` parameter for CPU-only contract tests. The production
worker does not implement this protocol; use `endpoint` for real TensorRT.
Choose one HTTP parameter, or leave both empty to use in-process YOLO.

- `GET /health`: JSON `{"status":"ok","backend":"mock","version":1}`.
- `POST /infer`: JSON with `version: 1`, `confidence: 0.5`, and `image` containing
  integer `width`, `height`, `encoding: "bgr8"`, and `data` as base64 of tightly
  packed BGR pixels. No header, JPEG or row padding is transmitted.
- Response: `version: 1`, `backend: "mock"` (or `"tensorrt"` for a future real
  worker), and `detections`, a list of `{label, score, xywh}`. Boxes use pixel
  center x/y and width/height. The ROS adapter preserves the source ROS header.
- The mock always returns a deterministic person and car box, filtered by
  confidence. It never loads TensorRT, CUDA, PyTorch or Ultralytics, and does not
  recognize image content. Its health endpoint is not perception health.
- The client validates responses and has a configurable timeout (default one
  second). A failed request logs an error and publishes no detection/annotation
  for that frame. It never publishes `/perception/healthy` or enables motion.

For a manual test in a sourced ROS environment, start the worker:

```bash
PYTHONPATH=src/dubdash python3 scripts/mock_inference_worker.py
ros2 run dubdash person_detector --ros-args \
  -p inference_url:=http://127.0.0.1:8000 \
  -p allow_mock_inference:=true \
  -r image:=/stereo/left/image_rect
```

Run these in separate terminals. Mock responses are rejected unless
`allow_mock_inference` is explicitly enabled. The worker is a development fixture,
without authentication or TLS; Compose exposes it only on its internal network.

## GitHub Actions

`.github/workflows/checks.yml` runs:

1. The normal Python suite on Windows, macOS and Linux with Python 3.10.
2. Bash syntax checks, base/override Compose validation, and assertions against
   Docker's merged JSON that GPU requests, desktop ports and data mounts are gone.
   The production benchmark overlay is also checked for Compose validity.
3. A cached AMD64 build and the same laptop test script, requiring actual ROS
   integration and the networked mock worker on every push/PR.
4. An ARM64 Buildx/QEMU image build on pull requests. It can also be requested via
   **Actions → Checks → Run workflow → arm64**. No image publishing or GPU runner
   is required. See [Docker's CI example](https://docs.docker.com/build/ci/github-actions/multi-platform/).

Passing these checks means CPU contracts and the tested Humble userspace paths
work. Emulation does **not** verify GPU compatibility or performance. The base
ROS tag and apt repositories are moving inputs, as before; this workflow is
repeatable, not a byte-for-byte locked NVIDIA deployment. Record production image
digests and installed versions separately when qualifying a Jetson release.

## Required Jetson validation

Before a hardware release, record the host and container OS, image digest,
architecture, JetPack/L4T, CUDA, TensorRT, PyTorch, ROS and camera-driver versions.
Then verify on the actual device:

- NVIDIA container runtime/device access and the production image's compatibility
  with the reported host software stack.
- Real TensorRT engine generation/loading, supported operations, numerical results
  against reference inputs, and compatibility with TensorRT 10.16.2/CUDA 13.2.
- Camera driver, capture synchronization, calibration, measured depth accuracy,
  transforms and timestamp behavior under real lighting and robot movement.
- Concurrent stereo, SLAM and inference frame rate, end-to-end latency, memory,
  thermal behavior and power budget.
- Full mapping/localization, real worker failures, physical motor watchdog,
  emergency stop, braking distance and perception-loss trials.

The mock does not make any of these checks unnecessary. The existing recorded
demo's image-transport shutdown crash is also outside the new synthetic test.

## Validation when this workflow was added

On the available Windows laptop (Python 3.14), the native suite passed **65 tests**
and skipped the ROS integration module. Python compilation, Bash syntax and
workflow YAML parsing also passed. Docker Engine/Desktop, WSL and ROS were not
installed, so container builds, Docker's merged-config validation, ROS integration
and ARM64/QEMU execution could not be run there. Those checks are configured in
CI and must pass before treating the container workflow as validated. No NVIDIA
GPU compatibility or performance was tested.
