#!/usr/bin/env python3
"""Validate Docker's *merged* Compose JSON, including CPU-only isolation."""
import json
import sys


def validate(config):
    if config.get("volumes"):
        raise ValueError("Laptop tests must not create persistent data volumes")
    services = config["services"]
    mapping, worker = services["mapping"], services["mock-inference"]
    for name, service in (("mapping", mapping), ("mock-inference", worker)):
        if service.get("runtime") != "runc":
            raise ValueError(f"{name}: expected explicit runc runtime")
        reserved = service.get("deploy", {}).get("resources", {}).get(
            "reservations", {}).get("devices", [])
        if service.get("gpus") or service.get("devices") or reserved:
            raise ValueError(f"{name}: laptop services must not request devices/GPUs")
        if service.get("ports") or service.get("volumes"):
            raise ValueError(f"{name}: tests must not expose ports or mount robot data")
        if service.get("environment", {}).get("NVIDIA_VISIBLE_DEVICES") != "void":
            raise ValueError(f"{name}: NVIDIA devices must be disabled")
    if mapping["platform"] != worker["platform"] or mapping["image"] != worker["image"]:
        raise ValueError("Tests and worker must use the same architecture/image")
    if mapping["environment"].get("DUBDASH_REQUIRE_ROS") != "1":
        raise ValueError("ROS tests must fail rather than skip inside Docker")
    if mapping["environment"].get("INFERENCE_URL") != "http://mock-inference:8000":
        raise ValueError("Tests must address the mock service over Compose networking")
    if mapping["entrypoint"] != ["/bin/bash", "/workspace/scripts/run_container_tests.sh"]:
        raise ValueError("Expected headless test entrypoint")


if __name__ == "__main__":
    validate(json.load(sys.stdin))
    print("Merged laptop Compose configuration is CPU-only and isolated")
