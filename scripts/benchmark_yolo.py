#!/usr/bin/env python3
"""Sequential HTTP worker saturation test. Source is an explicitly supplied image."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/dubdash'))
from dubdash.performance import distribution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='JPEG; label source separately from stereo recording')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8090/')
    parser.add_argument('--samples', type=int, default=300)
    parser.add_argument('--warmup', type=int, default=20)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.samples <= 0 or args.warmup < 0:
        parser.error('samples must be positive and warmup nonnegative')
    payload = Path(args.image).read_bytes()
    with Path(args.output).open('x') as output:
        rows = []
        for i in range(args.warmup+args.samples):
            start = time.perf_counter()
            if i == args.warmup:
                measured_started = start
            with urlopen(Request(args.endpoint, data=payload,
                                 headers={'Content-Type': 'image/jpeg'}), timeout=30) as response:
                result = json.load(response)
            result['request_ms'] = (time.perf_counter()-start)*1000
            result['warmup'] = i < args.warmup
            output.write(json.dumps(result)+'\n')
            output.flush()
            if not result['warmup']:
                rows.append(result)
    measured_seconds = time.perf_counter()-measured_started
    summary = dict(sustained_fps=len(rows)/measured_seconds, wall_seconds=measured_seconds, source=str(Path(args.image).resolve()), sha256=hashlib.sha256(payload).hexdigest(),
                   samples=len(rows), input_shape=rows[0]['input_shape'],
                   # Sequential requests; excludes file I/O and sample logging between calls.
                   sequential_request_fps=1000*len(rows)/sum(r['request_ms'] for r in rows),
                   timings={k: distribution([r[k] for r in rows])
                            for k in ('request_ms','worker_ms','inference_ms')},
                   detected_people_per_frame=distribution([len(r['boxes']) for r in rows]))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
