"""Regression tests for the merged-configuration safety validator."""
import copy

import pytest

from check_laptop_compose import validate


def config():
    service = {"runtime": "runc", "platform": "linux/amd64", "image": "test",
               "environment": {"NVIDIA_VISIBLE_DEVICES": "void"}}
    mapping = copy.deepcopy(service)
    mapping["environment"].update(DUBDASH_REQUIRE_ROS="1", INFERENCE_URL="http://mock-inference:8000")
    mapping["entrypoint"] = ["/bin/bash", "/workspace/scripts/run_container_tests.sh"]
    return {"services": {"mapping": mapping, "mock-inference": service}}


def test_cpu_only_config():
    validate(config())


@pytest.mark.parametrize("change", [
    {"runtime": "nvidia"}, {"gpus": "all"}, {"devices": ["/dev/video0"]},
    {"deploy": {"resources": {"reservations": {"devices": [{"driver": "nvidia"}]}}}},
    {"ports": ["6080:6080"]}, {"volumes": ["maps:/workspace/maps"]},
])
def test_rejects_gpu_and_host_access(change):
    merged = config()
    merged["services"]["mapping"].update(change)
    with pytest.raises(ValueError):
        validate(merged)
