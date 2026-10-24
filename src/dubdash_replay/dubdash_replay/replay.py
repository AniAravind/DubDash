"""Recorded-stereo demo contracts and validation (no ROS imports)."""
import math
from pathlib import Path
import sqlite3

RELEASE = '0.23.13'
# GitHub release asset digests checked during setup; archives remain external.
DATASET_SHA256 = {
    'A': '051a368f897b3c539f44c7110e1f4856bec9ccbe2fe7b44ec8dafd7f6f8805a5',
    'B': 'b56c8092f93201b5b8fc7ed870c0c54cc09aa18864e565b4c377b885ee098188',
}
SENSOR_TOPICS = {
    '/stereo_camera/left/image_raw_throttle/compressed': 'sensor_msgs/msg/CompressedImage',
    '/stereo_camera/right/image_raw_throttle/compressed': 'sensor_msgs/msg/CompressedImage',
    '/stereo_camera/left/camera_info_throttle': 'sensor_msgs/msg/CameraInfo',
    '/stereo_camera/right/camera_info_throttle': 'sensor_msgs/msg/CameraInfo',
}
PLAY_TOPICS = [*SENSOR_TOPICS, '/tf', '/tf_static']


def dataset_name(session):
    if session not in ('A', 'B'):
        raise ValueError('Dataset must be A (mapping) or B (localization)')
    return f'stereo_outdoor{session}_bag'


def dataset_url(session):
    name = dataset_name(session)
    return f'https://github.com/introlab/rtabmap_ros/releases/download/{RELEASE}/{name}.zip'


def readonly_database(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def inspect_bag(path):
    path = Path(path).expanduser().resolve()
    if not (path / 'metadata.yaml').is_file():
        raise ValueError(f'No ROS 2 metadata.yaml in {path}')
    segments = sorted(path.glob('*.db3'))
    if not segments:
        raise ValueError('This demo requires the upstream SQLite3 ROS 2 bag, not MCAP/ROS 1')
    topics = {}
    total = 0
    for segment in segments:
        with readonly_database(segment) as connection:
            topics.update(connection.execute('SELECT name, type FROM topics').fetchall())
            total += connection.execute('SELECT count(*) FROM messages').fetchone()[0]
    missing = [name for name, kind in SENSOR_TOPICS.items() if topics.get(name) != kind]
    if missing:
        raise ValueError('Missing/wrong stereo topics: ' + ', '.join(missing))
    if not any(topic in topics for topic in ('/tf', '/tf_static')):
        raise ValueError('Bag has no camera/body transforms')
    if total == 0:
        raise ValueError('Bag contains no recorded messages')
    return dict(path=str(path), segments=len(segments), messages=total, topics=topics)


def validate_database(path, mode):
    path = Path(path).expanduser().resolve()
    if path.suffix != '.db':
        raise ValueError('Choose a .db file for the RTAB-Map database')
    if mode not in ('mapping', 'localization'):
        raise ValueError('Mode must be mapping or localization')
    if mode == 'mapping':
        if path.exists():
            raise ValueError(f'Map already exists: {path}. Choose a new --database; no maps are deleted.')
    else:
        if not path.is_file():
            raise ValueError(f'No saved map: {path}. Run mapping first.')
        try:
            with readonly_database(path) as connection:
                count = connection.execute('SELECT count(*) FROM Node').fetchone()[0]
        except sqlite3.Error as error:
            raise ValueError(f'Not a readable RTAB-Map map: {path}') from error
        if not count:
            raise ValueError('Saved map has no nodes; finish a mapping replay first')
    return path


def playback_command(path, rate=0.5, paused=True):
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError('Playback rate must be finite and positive')
    command = ['ros2', 'bag', 'play', str(Path(path).expanduser().resolve()),
               '--clock', '30', '--rate', str(rate)]
    if paused:
        command.append('--start-paused')
    # No recorded commands, odometry topics or /clock are replayed.
    return [*command, '--topics', *PLAY_TOPICS]


def stereo_launch_arguments(database, mode, rviz_config, gui=True):
    """Raw images are rectified separately; generic launch computes stereo VO."""
    return {
        'stereo': 'true', 'depth': 'false', 'subscribe_rgbd': 'false',
        'visual_odometry': 'true', 'frame_id': 'base_footprint',
        'vo_frame_id': 'odom', 'map_frame_id': 'map', 'odom_topic': '/vo',
        'use_sim_time': 'true', 'approx_sync': 'false',
        'database_path': str(database), 'localization': str(mode == 'localization').lower(),
        'left_image_topic': '/stereo_camera/left/image_rect',
        'right_image_topic': '/stereo_camera/right/image_rect',
        'left_camera_info_topic': '/stereo_camera/left/camera_info_throttle',
        'right_camera_info_topic': '/stereo_camera/right/camera_info_throttle',
        'rviz': str(gui).lower(), 'rtabmap_viz': 'false', 'rviz_cfg': str(rviz_config),
        'args': '--Grid/Sensor 1',
    }
