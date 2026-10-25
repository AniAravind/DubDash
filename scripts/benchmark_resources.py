#!/usr/bin/env python3
"""Read-only host telemetry. JSONL /proc samples plus optional raw tegrastats."""
import argparse
import json
from pathlib import Path
import shutil
import signal
import sys
import re
import subprocess
import time


sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/dubdash'))
from dubdash.performance import distribution


def stop(signum, frame):
    raise KeyboardInterrupt


def cpu_ticks():
    values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return sum(values), values[3]+values[4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New directory')
    parser.add_argument('--seconds', type=float, default=90.)
    args = parser.parse_args()
    import math
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error('seconds must be finite and positive')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    signal.signal(signal.SIGTERM, stop)
    telemetry = None
    rows = []
    with (output/'tegrastats.log').open('x') as tegra, (output/'resources.jsonl').open('x') as samples:
        if shutil.which('tegrastats'):
            telemetry = subprocess.Popen(['tegrastats', '--interval', '1000'], stdout=tegra, stderr=tegra)
        previous = cpu_ticks()
        started = time.perf_counter()
        try:
            while time.perf_counter()-started < args.seconds:
                time.sleep(min(1., args.seconds))
                current = cpu_ticks()
                total, idle = current[0]-previous[0], current[1]-previous[1]
                previous = current
                memory = {line.split(':')[0]: int(line.split()[1])
                          for line in Path('/proc/meminfo').read_text().splitlines()}
                temperatures = {}
                for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
                    try:
                        temperatures[(zone/'type').read_text().strip()] = int((zone/'temp').read_text())/1000
                    except (OSError, ValueError):
                        pass
                sample = dict(monotonic_s=time.perf_counter(), wall_time_ns=time.time_ns(),
                              elapsed_s=time.perf_counter()-started,
                              cpu_busy_percent=100*(1-idle/total) if total else None,
                              memory_used_kib=memory['MemTotal']-memory['MemAvailable'],
                              memory_available_kib=memory['MemAvailable'],
                              swap_used_kib=memory['SwapTotal']-memory['SwapFree'],
                              temperatures_c=temperatures)
                rows.append(sample)
                samples.write(json.dumps(sample)+'\n'); samples.flush()
        except KeyboardInterrupt:
            pass
        finally:
            if telemetry:
                telemetry.terminate()
                try:
                    telemetry.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    telemetry.kill(); telemetry.wait()

    gpu = [float(v) for v in re.findall(r'GR3D_FREQ\s+(\d+(?:\.\d+)?)%', (output/'tegrastats.log').read_text())]
    summary = {key: distribution([r[key] for r in rows if r[key] is not None])
               for key in ('cpu_busy_percent','memory_used_kib','memory_available_kib','swap_used_kib')}
    summary['gpu_busy_percent'] = distribution(gpu)
    summary['temperatures_c'] = {name: distribution([r['temperatures_c'][name] for r in rows if name in r['temperatures_c']])
                                 for name in {key for r in rows for key in r['temperatures_c']}}
    (output/'summary.json').write_text(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
