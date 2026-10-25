#!/usr/bin/env python3
"""Read-only capability check. No privilege escalation or socket/device changes."""
import ctypes
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys


def command(argv):
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=10)
        return dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(error=str(error))


def main():
    result = dict(platform=platform.platform(), python=sys.version,
                  nvidia_devices=sorted(str(p) for p in Path('/dev').glob('nv*')),
                  docker=command(['docker', 'ps', '--format', '{{.Names}} {{.Image}}']),
                  packages=command(['dpkg-query', '-W', 'libnvinfer10', 'cuda-cudart-13-2']))
    for name, path in [('jetson_release','/etc/nv_tegra_release'), ('os_release','/etc/os-release')]:
        result[name] = Path(path).read_text() if Path(path).exists() else None
    result['python_modules'] = {m: bool(importlib.util.find_spec(m))
                               for m in ('tensorrt','torch','ultralytics','cv2','numpy','rclpy')}
    try:
        cuda = ctypes.CDLL('libcuda.so.1')
        result['cuInit_status'] = cuda.cuInit(0)
        count = ctypes.c_int()
        result['cuDeviceGetCount_status'] = cuda.cuDeviceGetCount(ctypes.byref(count))
        result['cuda_device_count'] = count.value
    except OSError as error:
        result['cuda_error'] = str(error)
    try:
        trt = ctypes.CDLL('libnvinfer.so.10')
        trt.getInferLibVersion.restype = ctypes.c_int
        result['tensorrt_runtime_encoded_version'] = trt.getInferLibVersion()
    except OSError as error:
        result['tensorrt_error'] = str(error)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
