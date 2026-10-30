"""Open saved robot maps through a new SQLite snapshot, never overwrite them."""
from pathlib import Path
import sqlite3


def localization_copy(source, destination):
    source, destination = Path(source).expanduser().resolve(), Path(destination).expanduser().resolve()
    if not source.is_file() or source.suffix != '.db' or destination.suffix != '.db':
        raise ValueError('Provide an existing RTAB-Map .db and a new .db destination')
    if source == destination:
        raise ValueError('Localization requires a separate database')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as incoming:
        if incoming.execute('SELECT count(*) FROM Node').fetchone()[0] == 0:
            raise ValueError('Saved map has no nodes')
        with destination.open('xb'):
            pass
        try:
            with sqlite3.connect(destination) as outgoing:
                incoming.backup(outgoing)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return destination
