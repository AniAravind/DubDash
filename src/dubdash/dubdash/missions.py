"""Validated named destinations and a persistent, idempotent command ledger."""
import json
import math
import re
import sqlite3


def destinations(document):
    if not isinstance(document, dict) or document.get('frame_id') != 'map':
        raise ValueError('Destination frame_id must be map')
    places = document.get('destinations')
    if not isinstance(places, dict) or len(places) > 1000:
        raise ValueError('Expected at most 1000 destinations')
    result = {}
    for name, pose in places.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name):
            raise ValueError('Destination names use letters, numbers, underscores or hyphens')
        if not isinstance(pose, dict) or set(pose) != {'x', 'y', 'yaw'}:
            raise ValueError(f'{name}: provide x, y and yaw only')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in pose.values()):
            raise ValueError(f'{name}: coordinates must be finite numbers')
        if abs(pose['yaw']) > math.pi:
            raise ValueError('Yaw must be in radians between -pi and pi')
        result[name] = dict(pose)
    return result


def command(payload, places):
    if not isinstance(payload, dict) or set(payload)-{'request_id', 'operation', 'route'}:
        raise ValueError('Unknown command fields')
    request_id = payload.get('request_id')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request_id):
        raise ValueError('Provide a unique request_id (1-64 letters/numbers/_/-)')
    operation = payload.get('operation')
    if operation not in ('start', 'cancel'):
        raise ValueError('Operation must be start or cancel')
    route = payload.get('route', [])
    if not isinstance(route, list):
        raise ValueError('Route must be a list')
    if operation == 'start':
        if not isinstance(route, list) or not 1 <= len(route) <= 32:
            raise ValueError('Route must contain 1-32 named destinations')
        if any(not isinstance(name, str) or name not in places for name in route):
            raise ValueError('Route contains an unknown destination')
    elif route:
        raise ValueError('Cancel cannot contain a route')
    return dict(request_id=request_id, operation=operation, route=route)


class MissionLedger:
    """Every acknowledged request survives restart; old starts never auto-resume."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, payload TEXT, reply TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT)')
        self.db.commit()

    def previous(self, request):
        row = self.db.execute('SELECT payload,reply FROM requests WHERE id=?', (request['request_id'],)).fetchone()
        if row is None:
            return None
        if row[0] != json.dumps(request, sort_keys=True):
            raise ValueError('request_id was already used for a different command')
        return json.loads(row[1])

    def record(self, request, reply):
        with self.db:
            self.db.execute('INSERT INTO requests VALUES (?,?,?)',
                (request['request_id'], json.dumps(request, sort_keys=True), json.dumps(reply)))

    def event(self, status):
        with self.db:
            self.db.execute('INSERT INTO events(payload) VALUES (?)', (json.dumps(status),))

    def close(self):
        self.db.close()
