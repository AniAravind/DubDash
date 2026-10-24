#!/usr/bin/env python3
"""Fetch, inspect and replay the RTAB-Map outdoor stereo mapping demo."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

# This development tool runs from a checkout as well as a sourced colcon workspace.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/dubdash_replay'))
from dubdash_replay.replay import (dataset_name, dataset_url, inspect_bag, playback_command,
                            validate_database, readonly_database, DATASET_SHA256)

MAX_DOWNLOAD = 8 * 1024 ** 3
MAX_EXTRACTED = 16 * 1024 ** 3


def extract_bag(archive, destination, name):
    """Only extract bag payloads, in a temporary directory; never overwrite data."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(f'Destination exists: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.bag-extract-') as work:
        work = Path(work)
        with zipfile.ZipFile(archive) as source:
            if sum(item.file_size for item in source.infolist()) > MAX_EXTRACTED:
                raise ValueError('Archive expands beyond the demo size limit')
            for item in source.infolist():
                relative = Path(item.filename)
                if (relative.is_absolute() or '..' in relative.parts
                        or '\\' in item.filename or stat.S_ISLNK(item.external_attr >> 16)):
                    raise ValueError('Unsafe archive path/link')
                if item.is_dir() or '__MACOSX' in relative.parts:
                    continue
                if relative.suffix not in ('.db3', '.yaml'):
                    continue
                output = work / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as incoming, output.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
        candidates = [file.parent for file in work.rglob('metadata.yaml')]
        if len(candidates) != 1:
            raise ValueError('Expected exactly one ROS 2 bag in archive')
        inspect_bag(candidates[0])
        candidates[0].rename(destination)
    return destination


def fetch(session, data_dir):
    name = dataset_name(session)
    data_dir = Path(data_dir).expanduser().resolve()
    target = data_dir / name
    if target.exists():
        inspect_bag(target)
        print(f'Already present: {target}')
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    url = dataset_url(session)
    print(f'Downloading {url}\nLarge download; allow several GB of disk space.', flush=True)
    checksum = hashlib.sha256()
    with tempfile.TemporaryDirectory(dir=data_dir, prefix='.bag-download-') as work:
        archive = Path(work) / f'{name}.zip'
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise ValueError('Download exceeds the demo size limit')
                output.write(chunk)
                checksum.update(chunk)
        if checksum.hexdigest() != DATASET_SHA256[session]:
            raise ValueError('Dataset checksum mismatch; download was not extracted')
        extract_bag(archive, target, name)
    # Keep the verified archive fingerprint alongside the extracted bag.
    (data_dir / f'{name}.archive.sha256').write_text(checksum.hexdigest() + '\n')
    print(f'Ready: {target}\nArchive SHA-256: {checksum.hexdigest()}')


def snapshot_map(source, target):
    source = validate_database(source, 'localization')
    target = Path(target).expanduser().resolve()
    if source == target or target.exists():
        raise ValueError('Localization snapshot must be a new .db path separate from the saved map')
    if target.suffix != '.db':
        raise ValueError('Localization snapshot must end in .db')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation prevents accidental clobbering by concurrent invocations.
    with target.open('xb'):
        pass
    try:
        with readonly_database(source) as incoming, sqlite3.connect(target) as outgoing:
            incoming.backup(outgoing)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def require_ros():
    if not shutil.which('ros2') or os.environ.get('ROS_DISTRO') != 'humble':
        raise ValueError('Run this command in ROS 2 Humble on Ubuntu 22.04; source /opt/ros/humble/setup.bash and install/setup.bash first.')


def launch_command(database, mode, gui=True):
    return ['ros2', 'launch', 'dubdash_replay', 'replay_mapping.launch.py',
            f'database_path:={database}', f'mode:={mode}', f'gui:={str(gui).lower()}']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('fetch', help='Download a published stereo bag')
    download.add_argument('--session', choices=['A', 'B', 'both'], default='A')
    download.add_argument('--data-dir', default='data/rtabmap')
    inspect = commands.add_parser('inspect', help='Validate SQLite bag topics before replay')
    inspect.add_argument('bag')
    play = commands.add_parser('play', help='Replay selected sensors with clock, paused initially')
    play.add_argument('bag')
    play.add_argument('--rate', type=float, default=0.5)
    play.add_argument('--autoplay', action='store_true', help='Start immediately instead of waiting for Space')
    play.add_argument('--dry-run', action='store_true')
    for name in ('map', 'localize'):
        command = commands.add_parser(name, help='Start mapping or saved-map localization')
        command.add_argument('--database', default='maps/stereo-demo.db')
        command.add_argument('--headless', action='store_true')
        command.add_argument('--dry-run', action='store_true')
        if name == 'localize':
            command.add_argument('--run-database', help='New localization snapshot path; default timestamped')
    goal = commands.add_parser('goal', help='Show a graph route to a saved map node (no driving)')
    goal.add_argument('--node-id', type=int, default=1)
    goal.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            for session in ('A', 'B') if args.session == 'both' else (args.session,):
                fetch(session, args.data_dir)
            return 0
        if args.command == 'inspect':
            print(json.dumps(inspect_bag(args.bag), indent=2))
            return 0
        if args.command == 'goal':
            if not 1 <= args.node_id <= 2147483647:
                raise ValueError('Choose a positive map node ID')
            command = ['ros2', 'service', 'call', '/rtabmap/rtabmap/set_goal',
                       'rtabmap_msgs/srv/SetGoal',
                       json.dumps(dict(node_id=args.node_id, node_label='', frame_id=''))]
        elif args.command == 'play':
            inspect_bag(args.bag)
            command = playback_command(args.bag, args.rate, paused=not args.autoplay)
        else:
            mode = 'mapping' if args.command == 'map' else 'localization'
            database = validate_database(args.database, mode)
            if mode == 'localization':
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                snapshot = Path(args.run_database or database.with_name(database.stem + f'-localization-{timestamp}.db')).expanduser().resolve()
                if snapshot == database or snapshot.exists() or snapshot.suffix != '.db':
                    raise ValueError('Choose a new .db localization snapshot path')
                if not args.dry_run:
                    require_ros()
                    database = snapshot_map(database, snapshot)
                    print(f'Localization copy: {database}\nOriginal saved map is preserved.', flush=True)
                else:
                    database = snapshot
            command = launch_command(database, mode, not args.headless)
        print(shlex.join(command), flush=True)
        if args.dry_run:
            return 0
        require_ros()
        return subprocess.call(command)
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        print(f'DubDash mapping: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
