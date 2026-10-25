#!/usr/bin/env python3
"""Headless bag benchmark in the mapping container. Outputs new files only."""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/dubdash'))
sys.path.insert(0, str(ROOT/'src/dubdash_replay'))
# Mount paths in the existing container are deliberately separate from its install.
if Path('/benchmark-src').exists():
    sys.path[:0] = ['/benchmark-src/dubdash', '/benchmark-src/dubdash_replay']
from dubdash.performance import distribution
from dubdash_replay.replay import playback_command, inspect_bag

SCENARIOS = {'vo': ('vo', False), 'slam': ('slam', False),
             'yolo': ('decode', True), 'vo-yolo': ('vo', True), 'full': ('slam', True)}


def commands(scenario, bag, output, rate, endpoint):
    pipeline, detection = SCENARIOS[scenario]
    launch = ['ros2', 'launch', '/benchmark-src/dubdash_replay/launch/replay_mapping.launch.py',
              f'database_path:={output}/map.db', f'pipeline:={pipeline}', 'gui:=false']
    detector = [sys.executable, '-c', "import sys; sys.path[:0]=['/benchmark-src/dubdash','/benchmark-src/dubdash_replay']; from dubdash.person_detector import main; main()",
                '--ros-args', '-p', f'endpoint:={endpoint}', '-p', 'use_sim_time:=true',
                '-p', f'metrics_path:={output}/detector.jsonl',
                '-r', 'image:=/stereo_camera/left/image_raw', '-r', 'people:=/benchmark/people']
    return [launch] + ([detector] if detection else []), playback_command(bag, rate, paused=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=SCENARIOS)
    parser.add_argument('--bag', default='/workspace/data/rtabmap/stereo_outdoorA_bag')
    parser.add_argument('--output', required=True)
    parser.add_argument('--rate', type=float, default=1.)
    parser.add_argument('--seconds', type=float, default=60.)
    parser.add_argument('--settle', type=float, default=8.)
    parser.add_argument('--endpoint', default='http://127.0.0.1:8090/')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in (args.rate, args.seconds, args.settle)):
        parser.error('rate, seconds and settle must be finite and positive')
    output = Path(args.output).resolve()
    if output.exists():
        parser.error('output must be a new directory; existing files are never overwritten')
    jobs, play = commands(args.scenario, args.bag, output, args.rate, args.endpoint)
    if args.dry_run:
        print(json.dumps(dict(jobs=jobs, playback=play, options=vars(args)), indent=2))
        return
    inspect_bag(args.bag)
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, CompressedImage
    from nav_msgs.msg import Odometry
    from rtabmap_msgs.msg import Info
    from vision_msgs.msg import Detection2DArray
    output.mkdir(parents=True, exist_ok=False)
    (output/'manifest.json').write_text(json.dumps(dict(jobs=jobs, playback=play, options=vars(args)), indent=2))
    processes, handles = [], []
    shutdown_actions = []
    arrivals = defaultdict(list)
    stamps = defaultdict(set)
    left_times = {}
    e2e = []
    def spawn(command, label):
        handle = (output/f'{label}.log').open('x')
        handles.append(handle)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        processes.append(process)
        return process
    rclpy.init()
    node = Node('benchmark_observer')
    raw = (output/'arrivals.jsonl').open('x', buffering=1)
    active = False
    started = None
    def callback(label):
        def receive(msg):
            if not active:
                return
            now = time.perf_counter()
            stamp = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
            arrivals[label].append(now)
            stamps[label].add(stamp)
            if label == 'left':
                left_times.setdefault(stamp, now)
            if label == 'people' and stamp in left_times:
                e2e.append((now-left_times.pop(stamp))*1000)
            raw.write(json.dumps(dict(topic=label, elapsed_s=now-started, monotonic_s=now, stamp_ns=stamp))+'\n')
        return receive
    subscriptions = [node.create_subscription(kind, topic, callback(label), qos_profile_sensor_data)
                     for label, kind, topic in [
                         ('camera', CompressedImage, '/stereo_camera/left/image_raw_throttle/compressed'),
                         ('left', Image, '/stereo_camera/left/image_raw'),
                         ('vo', Odometry, '/vo'), ('info', Info, '/rtabmap/info'),
                         ('people', Detection2DArray, '/benchmark/people')]]
    failed = None
    try:
        for i, job in enumerate(jobs):
            spawn(job, f'job{i}')
        deadline = time.perf_counter()+args.settle
        while time.perf_counter() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('Pipeline exited during startup; inspect job logs')
        started = time.perf_counter()
        active = True
        player = spawn(play, 'playback')
        while time.perf_counter()-started < args.seconds:
            rclpy.spin_once(node, timeout_sec=.05)
            if any(p.poll() is not None for p in processes if p is not player):
                raise RuntimeError('Pipeline exited; inspect job logs')
            if player.poll() is not None:
                if player.returncode:
                    raise RuntimeError('Bag player failed; inspect playback.log')
                break
    except KeyboardInterrupt:
        failed = 'Interrupted by operator'
    except Exception as error:
        failed = str(error)
    finally:
        active = False
        elapsed = time.perf_counter()-started if started is not None else 0
        # Signal only process groups created by this script. Give SLAM time to save.
        for p in reversed(processes):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGINT)
        for p in reversed(processes):
            try:
                p.wait(timeout=45)
            except subprocess.TimeoutExpired:
                shutdown_actions.append(dict(pid=p.pid, signal='SIGTERM', reason='SIGINT timeout'))
                if not failed:
                    failed = 'Pipeline did not shut down cleanly after SIGINT'
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    shutdown_actions.append(dict(pid=p.pid, signal='SIGKILL', reason='SIGTERM timeout'))
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
        for handle in handles:
            handle.close()
        raw.close()
        node.destroy_node()
        rclpy.shutdown()
        rates = {label: dict(count=len(times), wall_hz=len(times)/elapsed if elapsed else None,
                             interarrival_ms=distribution([(b-a)*1000 for a,b in zip(times,times[1:])]))
                 for label,times in arrivals.items()}
        for label, row in rates.items():
            unique_stamps = stamps[label]
            span = (max(unique_stamps)-min(unique_stamps))/1e9 if len(unique_stamps)>1 else 0
            row['recorded_stamp_span_s'] = span
            row['unique_stamps'] = len(unique_stamps)
        expected = ['camera', 'left']
        if SCENARIOS[args.scenario][0] != 'decode':
            expected.append('vo')
        if SCENARIOS[args.scenario][0] == 'slam':
            expected.append('info')
        if SCENARIOS[args.scenario][1]:
            expected.append('people')
        missing = [name for name in expected if not arrivals[name]]
        if missing and not failed:
            failed = 'No observed messages on required streams: ' + ', '.join(missing)
        summary = dict(status='failed' if failed else 'completed', error=failed, wall_seconds=elapsed,
                       shutdown_escalations=shutdown_actions, measurement_started_monotonic_s=started,
                       topics=rates, observed_left_to_people_ms=distribution(e2e),
                       left_without_people=len(stamps['left']-stamps['people']) if SCENARIOS[args.scenario][1] else None,
                       left_without_vo=len(stamps['left']-stamps['vo']) if SCENARIOS[args.scenario][0] != 'decode' else None,
                       camera_without_left=len(stamps['camera']-stamps['left']),
                       note='Observer counts are not DDS loss counters. Unmatched frames include startup/tail and intentional skips.')
        metrics = output/'detector.jsonl'
        if metrics.exists():
            rows = [json.loads(line) for line in metrics.read_text().splitlines()]
            rows = [row for row in rows if not row['warmup']]
            summary['detector_post_warmup'] = {key: distribution([row[key] for row in rows])
                                               for key in ('inference_ms','worker_ms','callback_ms')}
        (output/'summary.json').write_text(json.dumps(summary, indent=2))
    if failed:
        raise SystemExit(failed)


if __name__ == '__main__':
    main()
