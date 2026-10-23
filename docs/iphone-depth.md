# iPhone 16 front TrueDepth demo

Use your iPhone's front TrueDepth sensor to show people and **sensor-based surface
distances** in the Mac viewer. The iPhone runs a native capture app; the Mac runs
YOLO. Continuity Camera alone does not expose this depth stream.

## 1. Start the Mac viewer

From the repository folder, using Python 3.10 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-webcam.txt
python scripts/webcam_people.py --source iphone
```

The first launch downloads YOLO11 Nano weights. A window opens and the terminal
prints a `ws://<Mac address>:8765` address and a random session token. Keep the
terminal and viewer open. On Apple Silicon, optionally add `--device mps`;
CPU is the default. The receiver binds to all local IPv4 interfaces; use
`--host <Mac Wi-Fi IP>` to restrict it. Change the port with `--port` if needed.

Both devices must be on the same local Wi-Fi network with peer-to-peer traffic
allowed. If no address is printed, find the Mac's Wi-Fi IP in System Settings →
Wi-Fi → Details → TCP/IP. Allow incoming connections for Python in the Mac
firewall. Guest networks, corporate isolation and VPN routing may block access.
This is a token-protected, **unencrypted local demo**, not an Internet service;
use a trusted LAN and do not forward its port. No video or depth is saved.

## 2. Install the phone app

1. Open `ios/DubDashDepth/DubDashDepth.xcodeproj` in Xcode.
2. Under Xcode Settings → Accounts, add your Apple Account if needed.
3. Select the DubDashDepth target → Signing & Capabilities, choose your development
   team and leave automatic signing enabled. Change the bundle identifier if Xcode
   reports it is unavailable. A Personal Team can be used for local testing, subject
   to Apple's provisioning limits.
4. Connect the iPhone 16 to the Mac by cable for installation. Unlock it and trust
   the Mac. Enable Settings → Privacy & Security → Developer Mode if prompted
   (this may require a restart). Trust the developer profile in Settings → General
   → VPN & Device Management if iOS asks.
5. Select the physical iPhone as Xcode's run destination and press Run. Xcode may
   need to download device support for your iOS version. Minimum target: iOS 18.
   A simulator cannot validate or supply TrueDepth.

The cable installs the app; streaming uses Wi-Fi. USB transport is not implemented.
No App Store publication, paid service or ROS setup is required for this demo.

## 3. Connect and view distances

Enter the complete Mac address and session token into the phone app, then tap
**Connect**. Allow Camera and Local Network access. Keep the app foregrounded and
the phone upright, with its front camera pointing at a person. The phone shows a
mirrored preview; the Mac shows the same orientation with YOLO labels.

The Mac displays `person 92% | 0.85 m`. It also runs OpenCV's bundled frontal-face
detector, so a face-only view can display `person (face) | 0.65 m` even when YOLO
finds no body. No confidence percentage is invented for the face detector. If a
face overlaps a body detection, they are counted once and depth comes from the
central face area. Face detection works best looking toward the camera with good
lighting; strong profiles and occlusion can still be missed. Restart the Mac
viewer after updating; this change does not require reinstalling the phone app.

For face detections, distance is to the visible facial surface. Otherwise, this is median optical-axis depth to the
visible surface in the central upper part of the detection, not distance to the
person's centre, feet or an identity measurement. A cropped/partial body can work
because no assumed person height is used. Depth is available only where the
sensor returns enough consistent, finite positive samples. Out-of-range regions,
holes and mixed foreground/background produce **depth unavailable**, never a
height-based substitute.

Press **D** in the Mac window to toggle a translucent depth overlay. It uses a
fixed 0–3 m colour scale for visualization; 3 m is not a promised sensor range.
Press **Q** or **Esc** to quit. Tap **Stop**, lock the phone or leave the phone app
to stop capture. Restarting the Mac viewer generates a new session token.

If no new pair arrives for one second, the Mac clears old pictures/distances and
shows **Connection lost / waiting for iPhone**. Slow inference similarly clears
results older than one second. If acknowledgements stop for two seconds, the phone
stops capture and asks you to reconnect. One phone is accepted at a time.

## Geometry and transport

The capture app selects a depth-capable front camera format near 640 pixels wide,
15 fps, zoom 1, no stabilization, no depth hole-filling and at most 10 transmitted
pairs/second. Exact dimensions depend on supported hardware formats. Video and
depth come from one `AVCaptureDataOutputSynchronizer` callback. A missing depth
sample can accompany a valid video frame; it never reuses an older depth map.

The app converts `AVDepthData` to float32 metres and packs rows without padding.
It sends camera intrinsics, their reference dimensions, distortion centre,
orientation, metric accuracy and sequence/capture timestamp with every pair.
Apple's AVDepthData maps are already distorted to match their corresponding
video. The receiver derives the RGB-to-depth sampling transform by scaling the
shared calibration intrinsics; it does not apply checkerboard calibration or
undistort only one of the two images. Different aspect ratios/crops are rejected.
Rotation and mirroring are applied identically to RGB and depth before inference.
This is a 2D registered-depth demo, not a rectified 3D point-cloud exporter.

Wire format v1: one binary WebSocket message contains a 4-byte big-endian JSON
header length, UTF-8 JSON header, JPEG bytes and optional tightly packed
little-endian float32 depth. Metadata describes payload sizes. Max message: 8 MiB;
max header: 64 KiB. Authentication is the initial JSON text message containing
`token`; the server replies `ready`. Each accepted pair receives an `ack` with its
sequence. Only one pair is unacknowledged on the phone; one pending pair is
replaced by the latest capture and expires after 0.5 seconds. Receiver and inference
also replace their pending frame instead of growing queues. Sequences and capture
timestamps must increase within a connection. Capture timestamps use the phone's
clock; GUI freshness uses the Mac's monotonic arrival clock, not cross-device
wall clocks. Relative-depth data is never labelled in metres.

## Validation status and physical acceptance checks

Automated checks cover packet bounds, JPEG dimensions, malformed messages,
missing/relative depth, camera geometry, all four right-angle rotations,
mirroring, invalid/mixed depth samples, latest-frame replacement and freshness.
A real loopback WebSocket test covers token rejection, acknowledgements,
sequence rejection, disconnect and reconnect. An unsigned generic iOS build
checks compilation; it does not test camera hardware, signing or LAN permissions.

**Physical phone testing is still required.**

- Start with a tape-measured target at 0.4, 0.6, 0.8 and 1.0 metres, adding other
  ranges only where valid depth exists. Measure from the front camera plane to
  the sampled torso surface. Record median displayed error and failure rate;
  aim for no more than 10 cm error at these initial close-range test points.
- Use D to inspect a foreground board/person edge against a far background,
  including both sides and corners. Confirm depth edges follow RGB under the
  preview's rotation and mirroring. Do not treat numeric labels as validated
  if the overlay is shifted.
- Test a face-only view, seated person and partial person at a measurable distance. Compare to the sampled
  surface, and test occlusion: the demo reports visible surface depth, so an
  object covering the torso may dominate the ROI.
- Cover the sensor, move beyond usable range and introduce depth holes. Confirm
  no invalid sample produces a plausible range. Uniform but incorrect depth
  cannot be rejected by the sampler alone.
- Stop the phone app, lock the phone, disable Wi-Fi, kill capture and reconnect.
  Check the Mac removes old frames within one second of the last received pair,
  and no old result appears after reconnecting.
- Benchmark latency and CPU/GPU load. If inference regularly exceeds one second,
  lower model image size in a future tuning step or use MPS; the demo intentionally
  hides stale results.

Upstream: [Apple TrueDepth sample](https://developer.apple.com/documentation/avfoundation/streaming-depth-data-from-the-truedepth-camera),
[Apple depth/image distortion alignment](https://developer.apple.com/documentation/avfoundation/avcameracalibrationdata/lensdistortionlookuptable).
