import asyncio
import json
import socket
import struct
import time

import cv2
import numpy as np
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from iphone_stream import (decode_packet, aligned_images, orient, person_depth,
                           LatestFrame, IPhoneReceiver, visible_result, MAX_PACKET)


def packet(meta_update=None, depth=None):
    image = np.zeros((60, 80, 3), np.uint8)
    image[:, :40] = (20, 40, 160)
    _, jpeg = cv2.imencode('.jpg', image)
    depth = np.full((30, 40), 0.85, np.float32) if depth is None else depth
    meta = dict(version=1, sequence=1, timestamp=10.0,
                video_size=[80, 60], jpeg_bytes=len(jpeg), rotation_degrees=0,
                mirrored=False, geometry='apple_video_aligned', depth_size=[40, 30],
                depth_format='float32_le_m', depth_absolute=True,
                calibration=dict(reference_size=[640, 480],
                                 intrinsic_matrix=[[600, 0, 320], [0, 600, 240], [0, 0, 1]]))
    if meta_update:
        meta.update(meta_update)
    header = json.dumps(meta).encode()
    raw = b'' if meta.get('depth_size') is None else depth.astype('<f4').tobytes()
    return struct.pack('!I', len(header)) + header + jpeg.tobytes() + raw


def test_decode_packet_and_calibration_alignment():
    frame = decode_packet(packet(), now=100)
    image, depth = aligned_images(frame)
    assert frame.sequence == 1 and frame.received_at == 100
    assert image.shape == (60, 80, 3)
    assert depth.shape == image.shape[:2]
    assert np.allclose(depth, 0.85)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('mirrored', [True, False])
def test_orientation_and_mirroring_match_for_video_and_depth(rotation, mirrored):
    depth = np.tile(np.arange(40, dtype=np.float32), (30, 1)) + 1
    frame = decode_packet(packet(dict(rotation_degrees=rotation, mirrored=mirrored), depth))
    raw_frame = decode_packet(packet(depth=depth))
    raw_image, raw_depth = aligned_images(raw_frame)
    image, registered = aligned_images(frame)
    np.testing.assert_array_equal(image, orient(raw_image, rotation, mirrored))
    np.testing.assert_array_equal(registered, orient(raw_depth, rotation, mirrored))


def test_foreground_geometry_does_not_mix_background():
    depth = np.full((30, 40), 5, dtype=np.float32)
    depth[5:22, 10:30] = 0.85
    frame = decode_packet(packet(depth=depth))
    _, registered = aligned_images(frame)
    assert person_depth(registered, [20, 10, 60, 44]) == pytest.approx(0.85)
    # Partial-body boxes do not need to reach the feet or image bottom.
    assert person_depth(registered, [22, 12, 58, 38]) == pytest.approx(0.85)


@pytest.mark.parametrize('meta', [dict(version=2), dict(version=True), dict(sequence=-1),
    dict(timestamp=float('nan')), dict(video_size=[0, 60]), dict(video_size=[8000, 6000]),
    dict(video_size=[80, 61]), dict(rotation_degrees=45), dict(mirrored='yes'),
    dict(jpeg_bytes=-1), dict(depth_size=[20, 30]), dict(depth_size=[40, 31]),
    dict(depth_format='disparity'), dict(calibration=None), dict(geometry='unknown'),
    dict(calibration=dict(reference_size=[640, 480], intrinsic_matrix=[[0]*3]*3))])
def test_reject_invalid_metadata(meta):
    with pytest.raises((ValueError, TypeError)):
        decode_packet(packet(meta))


@pytest.mark.parametrize('raw', [b'', b'abc', b'\x00\x01\x00\x01{}',
                                 struct.pack('!I', 5) + b'nope!',
                                 b'x' * (MAX_PACKET + 1)])
def test_malformed_packets(raw):
    with pytest.raises(ValueError):
        decode_packet(raw)


def test_truncation_and_bad_jpeg():
    with pytest.raises(ValueError):
        decode_packet(packet()[:-1])
    raw = packet()
    start = 4 + struct.unpack('!I', raw[:4])[0]
    with pytest.raises(ValueError):
        decode_packet(raw[:start] + b'xx' + raw[start+2:])


def test_missing_or_relative_depth_does_not_produce_metres():
    for metadata in [dict(depth_size=None), dict(depth_absolute=False)]:
        frame = decode_packet(packet(metadata))
        image, depth = aligned_images(frame)
        assert image is not None and depth is None
        assert person_depth(depth, [1, 1, 50, 50]) is None


def test_invalid_sparse_and_mixed_depth():
    for value in [float('nan'), float('inf'), 0, -1]:
        assert person_depth(np.full((80, 80), value), [0, 0, 80, 80]) is None
    sparse = np.full((80, 80), np.nan)
    sparse[15:18, 30:33] = 0.8
    assert person_depth(sparse, [0, 0, 80, 80]) is None
    mixed = np.full((80, 80), 0.8)
    mixed[:, 40:] = 4
    assert person_depth(mixed, [0, 0, 80, 80]) is None
    assert person_depth(mixed, [5, 5, 5, 10]) is None


def test_latest_frame_replacement_stale_disconnect_and_reconnect():
    latest = LatestFrame()
    first = decode_packet(packet(), now=10)
    second = decode_packet(packet(dict(sequence=2)), now=10.1)
    latest.publish(first)
    latest.publish(second)
    assert latest.snapshot(10.2) is second
    assert latest.snapshot(11.1) is None
    assert latest.snapshot(9) is None
    rendered = (second, second.image)
    assert visible_result(second, rendered, 10.5) is second.image
    assert visible_result(second, rendered, 11.1) is None
    latest.clear()
    assert latest.snapshot(10.2) is None
    assert visible_result(None, rendered, 10.2) is None
    first.stream_id = 'new-connection'
    assert visible_result(first, rendered, 10.2) is None


def test_live_websocket_auth_frames_disconnect_and_sequence_rejection(capsys):
    # Bind an ephemeral local port for the actual WebSocket loopback test.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    receiver = IPhoneReceiver('127.0.0.1', port)
    receiver.start()
    capsys.readouterr()

    async def scenario():
        uri = f'ws://127.0.0.1:{port}'
        async with connect(uri) as client:
            await client.send(json.dumps(dict(token='wrong')))
            with pytest.raises(ConnectionClosed):
                await client.recv()
        async with connect(uri) as client:
            await client.send(json.dumps(dict(token=receiver.token)))
            assert json.loads(await client.recv())['type'] == 'ready'
            await client.send(packet())
            assert json.loads(await client.recv()) == dict(type='ack', sequence=1)
            assert receiver.latest.snapshot().sequence == 1
            # Repeated frames are rejected, never presented as fresh captures.
            await client.send(packet())
            with pytest.raises(ConnectionClosed):
                await client.recv()
        for _ in range(100):
            if receiver.latest.snapshot() is None:
                break
            await asyncio.sleep(0.01)
        assert receiver.latest.snapshot() is None
        # A new connection can restart capture IDs.
        async with connect(uri) as client:
            await client.send(json.dumps(dict(token=receiver.token)))
            await client.recv()
            await client.send(packet())
            assert json.loads(await client.recv())['type'] == 'ack'
    try:
        asyncio.run(scenario())
    finally:
        receiver.close()


def test_large_calibration_reference_dimensions_are_not_video_allocations():
    metadata = dict(calibration=dict(reference_size=[4032, 3024],
                                    intrinsic_matrix=[[3800, 0, 2016], [0, 3800, 1512], [0, 0, 1]]))
    frame = decode_packet(packet(metadata))
    _, depth = aligned_images(frame)
    assert np.allclose(depth, 0.85)
