"""Bounded TrueDepth wire format, geometry and latest-frame receiver."""
import asyncio
from dataclasses import dataclass
import hmac
import json
import math
import secrets
import socket
import struct
import threading
import time

import cv2
import numpy as np

MAX_PACKET = 8 * 1024 * 1024
MAX_HEADER = 64 * 1024


@dataclass
class DepthFrame:
    sequence: int
    image: np.ndarray
    depth: object
    metadata: dict
    received_at: float
    stream_id: str = ''


def dimensions(value, name, maximum=1920):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(v) is not int or not 1 <= v <= maximum for v in value)
            or value[0] * value[1] > (1920 * 1080 if maximum == 1920 else maximum ** 2)):
        raise ValueError(f'Invalid {name} dimensions')
    return tuple(value)


def decode_packet(packet, now=None):
    if not isinstance(packet, bytes) or not 5 <= len(packet) <= MAX_PACKET:
        raise ValueError('Invalid packet length/type')
    header_size = struct.unpack('!I', packet[:4])[0]
    if not 1 <= header_size <= MAX_HEADER or header_size + 4 > len(packet):
        raise ValueError('Invalid header length')
    try:
        meta = json.loads(packet[4:4 + header_size])
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid JSON header') from error
    if (not isinstance(meta, dict) or type(meta.get('version')) is not int
            or meta.get('version') != 1):
        raise ValueError('Unsupported protocol version')
    if type(meta.get('sequence')) is not int or meta['sequence'] < 0:
        raise ValueError('Invalid frame sequence')
    if (type(meta.get('timestamp')) not in (int, float)
            or not math.isfinite(meta['timestamp']) or meta['timestamp'] < 0):
        raise ValueError('Invalid capture timestamp')
    width, height = dimensions(meta.get('video_size'), 'video')
    rotation = meta.get('rotation_degrees')
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError('Unsupported rotation')
    if type(meta.get('mirrored')) is not bool:
        raise ValueError('Missing mirror convention')
    jpeg_size = meta.get('jpeg_bytes')
    if type(jpeg_size) is not int or jpeg_size < 1:
        raise ValueError('Invalid JPEG length')
    start = 4 + header_size
    if start + jpeg_size > len(packet):
        raise ValueError('Truncated JPEG')
    # Read JPEG SOF dimensions before decompression to bound decoded allocations.
    jpeg = packet[start:start + jpeg_size]
    if jpeg_dimensions(jpeg) != (width, height):
        raise ValueError('JPEG dimensions do not match header')
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (height, width):
        raise ValueError('Invalid JPEG image')
    raw_depth = packet[start + jpeg_size:]
    depth = None
    depth_size = meta.get('depth_size')
    if depth_size is None:
        if raw_depth:
            raise ValueError('Unexpected depth bytes')
    else:
        dw, dh = dimensions(depth_size, 'depth')
        if len(raw_depth) != dw * dh * 4 or meta.get('depth_format') != 'float32_le_m':
            raise ValueError('Invalid depth payload')
        calibration = meta.get('calibration')
        if not isinstance(calibration, dict) or meta.get('geometry') != 'apple_video_aligned':
            raise ValueError('Missing aligned-camera calibration')
        rw, rh = dimensions(calibration.get('reference_size'), 'calibration', maximum=16384)
        if abs(width / height - dw / dh) > 0.01 or abs(rw / rh - width / height) > 0.01:
            raise ValueError('Unsupported video/depth crop or aspect ratio')
        matrix = np.asarray(calibration.get('intrinsic_matrix'), dtype=float)
        if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
                or matrix[0, 0] <= 0 or matrix[1, 1] <= 0
                or not np.allclose(matrix[2], [0, 0, 1])
                or not np.isclose(matrix[1, 0], 0)):
            raise ValueError('Invalid camera intrinsics')
        if type(meta.get('depth_absolute')) is not bool:
            raise ValueError('Missing depth accuracy')
        depth = np.frombuffer(raw_depth, dtype='<f4').reshape(dh, dw).copy()
        # Relative depth must never be labelled in metres.
        if not meta['depth_absolute']:
            depth = None
    return DepthFrame(meta['sequence'], image, depth, meta,
                      time.monotonic() if now is None else now)


def jpeg_dimensions(jpeg):
    """Accept baseline/progressive JPEG headers without decoding image data."""
    if not jpeg.startswith(b'\xff\xd8'):
        raise ValueError('Missing JPEG signature')
    offset = 2
    while offset + 4 <= len(jpeg):
        if jpeg[offset] != 0xff:
            raise ValueError('Invalid JPEG marker')
        while offset < len(jpeg) and jpeg[offset] == 0xff:
            offset += 1
        if offset >= len(jpeg):
            break
        marker = jpeg[offset]
        offset += 1
        if marker in (0xd9, 0xda):
            break
        if marker == 0x01 or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(jpeg[offset:offset + 2], 'big')
        if length < 2 or offset + length > len(jpeg):
            raise ValueError('Truncated JPEG segment')
        if marker in (0xc0, 0xc1, 0xc2):
            if length < 8:
                break
            return (int.from_bytes(jpeg[offset + 5:offset + 7], 'big'),
                    int.from_bytes(jpeg[offset + 3:offset + 5], 'big'))
        offset += length
    raise ValueError('Missing JPEG dimensions')


def orient(array, rotation, mirrored):
    if array is None:
        return None
    output = np.rot90(array, k=-(rotation // 90))
    return np.ascontiguousarray(output[:, ::-1] if mirrored else output)


def aligned_images(frame):
    """AVDepthData already shares the distorted RGB FOV; do not undistort only one.

    Derive the video-to-depth sampling transform from intrinsics scaled from the
    same Apple calibration reference. No 3D reprojection or guessed baseline.
    """
    depth = None
    if frame.depth is not None:
        h, w = frame.image.shape[:2]
        dh, dw = frame.depth.shape
        calibration = frame.metadata['calibration']
        rw, rh = calibration['reference_size']
        intrinsic = np.asarray(calibration['intrinsic_matrix'], dtype=float)
        video_k = np.diag([w / rw, h / rh, 1]) @ intrinsic
        depth_k = np.diag([dw / rw, dh / rh, 1]) @ intrinsic
        transform = depth_k @ np.linalg.inv(video_k)
        yy, xx = np.mgrid[:h, :w].astype(np.float32)
        # Transform pixel centres rather than array corners.
        map_x = (transform[0, 0] * (xx + 0.5) + transform[0, 2] - 0.5).astype(np.float32)
        map_y = (transform[1, 1] * (yy + 0.5) + transform[1, 2] - 0.5).astype(np.float32)
        depth = cv2.remap(frame.depth, map_x, map_y, cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    angle, mirror = frame.metadata['rotation_degrees'], frame.metadata['mirrored']
    return orient(frame.image, angle, mirror), orient(depth, angle, mirror)


def person_depth(depth, box, face=False):
    """Median visible-surface Z in the face centre or upper-body ROI."""
    if depth is None or len(box) != 4 or not np.isfinite(box).all():
        return None
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return None
    h, w = depth.shape
    left_fraction, right_fraction = (0.25, 0.75) if face else (0.3, 0.7)
    top_fraction, bottom_fraction = (0.25, 0.75) if face else (0.15, 0.5)
    left = max(0, min(w, int(x1 + left_fraction * (x2 - x1))))
    right = max(0, min(w, int(math.ceil(x1 + right_fraction * (x2 - x1)))))
    top = max(0, min(h, int(y1 + top_fraction * (y2 - y1))))
    bottom = max(0, min(h, int(math.ceil(y1 + bottom_fraction * (y2 - y1)))))
    roi = depth[top:bottom, left:right]
    if roi.size < 25:
        return None
    valid = roi[np.isfinite(roi) & (roi > 0)]
    if valid.size < 25 or valid.size / roi.size < 0.5:
        return None
    median = float(np.median(valid))
    # Mixed surfaces / discontinuities should not yield a plausible blended range.
    if float(np.quantile(valid, 0.9) - np.quantile(valid, 0.1)) > max(0.15, median * 0.2):
        return None
    return median


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None

    def publish(self, frame):
        with self.lock:
            self.frame = frame

    def clear(self):
        with self.lock:
            self.frame = None


    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            frame = self.frame
            if frame is None or not 0 <= now - frame.received_at < 1.0:
                return None
            return frame


def visible_result(current, rendered, now):
    if (current is None or rendered is None or current.stream_id != rendered[0].stream_id
            or not 0 <= now - rendered[0].received_at < 1.0):
        return None
    return rendered[1]


class IPhoneReceiver:
    def __init__(self, host='0.0.0.0', port=8765):
        self.host, self.port = host, port
        self.token = secrets.token_urlsafe(18)
        self.latest = LatestFrame()
        self.ready = threading.Event()
        self.error = None
        self.loop = None
        self.stop_event = None
        self.active = None
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError('Receiver did not start')
        if self.error:
            raise RuntimeError(f'Cannot start iPhone receiver: {self.error}')
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None,
                         socket.AF_INET) if not info[4][0].startswith('127.')}
        except socket.gaierror:
            addresses = set()
        import sys
        if sys.platform == 'darwin':
            import subprocess
            for interface in ('en0', 'en1'):
                result = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface],
                                        capture_output=True, text=True, check=False)
                if result.returncode == 0 and result.stdout.strip():
                    addresses.add(result.stdout.strip())
        addresses = sorted(addresses)
        print(f'iPhone receiver listening on port {self.port}.')
        for address in addresses:
            print(f'Mac address: ws://{address}:{self.port}')
        if not addresses:
            print('Use ws://<your Mac Wi-Fi IP>:' + str(self.port))
        print(f'Session token: {self.token}\nEnter this address and token in the iPhone app.')

    def _thread_main(self):
        try:
            asyncio.run(self._serve())
        except Exception as error:
            self.error = error
            self.ready.set()
            self.latest.clear()

    async def _serve(self):
        from websockets.asyncio.server import serve
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        async with serve(self._handle, self.host, self.port, max_size=MAX_PACKET,
                         max_queue=1, compression=None, ping_interval=10, ping_timeout=10, close_timeout=1):
            self.ready.set()
            await self.stop_event.wait()

    async def _handle(self, connection):
        # First message is authentication; tokens are never placed in URLs/logs.
        try:
            hello = await asyncio.wait_for(connection.recv(), 5)
            auth = json.loads(hello) if isinstance(hello, str) else {}
            if (not isinstance(auth, dict) or not isinstance(auth.get('token'), str)
                    or not hmac.compare_digest(auth['token'], self.token)):
                await connection.close(1008, 'Invalid session token')
                return
            if self.active is not None:
                await connection.close(1008, 'A phone is already connected')
                return
            self.active = connection
            stream_id = secrets.token_hex(8)
            await connection.send(json.dumps({'type': 'ready', 'version': 1}))
            last_sequence, last_timestamp = -1, -1.0
            async for packet in connection:
                frame = decode_packet(packet)
                timestamp = frame.metadata['timestamp']
                if frame.sequence <= last_sequence or timestamp <= last_timestamp:
                    raise ValueError('Non-increasing capture sequence/timestamp')
                last_sequence, last_timestamp = frame.sequence, timestamp
                frame.stream_id = stream_id
                self.latest.publish(frame)
                # Phone permits one unacknowledged frame, bounding transport queues.
                await connection.send(json.dumps({'type': 'ack', 'sequence': frame.sequence}))
        except (ValueError, TypeError, TimeoutError):
            await connection.close(1008, 'Invalid capture message')
        except Exception:
            # Network disconnect is expected; no image or token logging.
            pass
        finally:
            if self.active is connection:
                self.active = None
                self.latest.clear()

    def close(self):
        self.latest.clear()
        if self.loop and not self.loop.is_closed() and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.thread.join(timeout=3)
