#!/usr/bin/env python3
"""Read-only deployment checks. Success never qualifies cameras, motors or safety."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/dubdash'))
from dubdash.missions import destinations
from dubdash.navigation_config import build_config
from dubdash.system_health import SystemHealth
from dubdash.ground import ground_support


def files(profile, places, database):
    import yaml
    settings = yaml.safe_load(Path(profile).read_text())
    # Validate the profile against the same policy as the real launch. The empty
    # config is not used for validation of installed Nav2 plugins.
    defaults = {name: {'ros__parameters': {}} for name in
        ('bt_navigator', 'controller_server', 'planner_server', 'velocity_smoother', 'behavior_server')}
    defaults['controller_server']['ros__parameters'] = {'FollowPath': {}, 'progress_checker': {}}
    defaults['planner_server']['ros__parameters'] = {'GridBased': {}}
    for kind in ('local', 'global'):
        defaults[kind+'_costmap'] = {kind+'_costmap': {'ros__parameters': {}}}
    build_config(defaults, settings)
    SystemHealth(settings.get('battery_min_fraction'))
    catalog = destinations(json.loads(Path(places).read_text()))
    if not catalog:
        raise ValueError('Configure actual named destinations; example catalog is empty')
    ground = settings.get('ground_validation', {})
    if ground.get('enabled'):
        ground_support([], radius=settings['robot_radius'], margin=settings['stop_margin'],
            **{key: ground[key] for key in ('ground_z', 'cell_size', 'height_tolerance', 'min_points', 'max_slope', 'horizon')})
    path = Path(database).resolve()
    if path.suffix != '.db' or not path.is_file():
        raise ValueError('Provide an existing saved route .db')
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as connection:
        if not connection.execute('SELECT count(*) FROM Node').fetchone()[0]:
            raise ValueError('Saved route has no map nodes')
    return settings, len(catalog)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'destinations', 'database'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--files-only', action='store_true', help='Laptop file checks only; skips host compatibility')
    args = parser.parse_args(argv)
    try:
        settings, count = files(args.profile, args.destinations, args.database)
        print(f'Configuration and saved-map checks passed; {count} named destinations')
        print('hardware_verified:', settings.get('hardware_verified') is True)
        if not args.files_only:
            if platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
                raise ValueError('Robot deployment requires Linux ARM64; use --files-only on the laptop')
            if not shutil.which('docker'):
                raise ValueError('Install Docker Engine and Compose on the Jetson')
            subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['docker', 'compose', 'version'], check=True)
            release = Path('/etc/nv_tegra_release')
            print('L4T:', release.read_text().strip() if release.exists() else 'UNKNOWN: verify this is the intended Jetson')
        print('Not checked: camera driver/sync/calibration, NVIDIA engine, live ground coverage, battery/BMS, motor adapter, emergency stop, braking, localization accuracy.')
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, subprocess.CalledProcessError) as error:
        print(f'Preflight blocked: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
