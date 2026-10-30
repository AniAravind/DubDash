#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

mode="${1:-test}"
case "$mode" in
    test|config|arm64-build) ;;
    *) echo "Usage: bash scripts/test_laptop.sh [test|config|arm64-build]" >&2; exit 2 ;;
esac
command -v docker >/dev/null || { echo "Install/start Docker Desktop or Docker Engine with Compose and Buildx." >&2; exit 1; }
docker compose version
docker buildx version
# An isolated project prevents cleanup from stopping an existing mapping desktop.
export COMPOSE_PROJECT_NAME="dubdash-laptop-${LAPTOP_RUN_ID:-$$}"
if [[ -z "${LAPTOP_PLATFORM:-}" ]]; then
    if [[ "$mode" == config ]]; then
        # Configuration validation does not require a running engine.
        arch="$(uname -m)"
    else
        arch="$(docker version --format '{{.Server.Arch}}')"
    fi
    case "$arch" in
        arm64|aarch64) export LAPTOP_PLATFORM=linux/arm64 ;;
        amd64|x86_64) export LAPTOP_PLATFORM=linux/amd64 ;;
        *) echo "Unsupported Docker architecture: $arch" >&2; exit 1 ;;
    esac
fi
compose=(docker compose -f compose.yaml -f compose.laptop.yaml)
docker compose -f compose.yaml config --quiet
"${compose[@]}" config --quiet
if [[ "$mode" == config ]]; then exit 0; fi
docker info >/dev/null
if [[ "$mode" == arm64-build ]]; then
    # QEMU/binfmt must already be available on x86 Linux; Desktop provides it.
    docker buildx build --platform linux/arm64 --load \
        -f docker/mapping/Dockerfile -t dubdash-laptop:humble-arm64 .
    exit 0
fi
cleanup() {
    status=$?
    trap - EXIT
    if [[ $status -ne 0 ]]; then "${compose[@]}" logs --no-color || true; fi
    "${compose[@]}" down --remove-orphans --timeout 10 || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Build once, then reuse this same CPU image for both services. Layer cache keeps
# repeated runs quick; tests are copied into the image (no host path mounts).
if [[ "${LAPTOP_SKIP_BUILD:-0}" != 1 ]]; then
    "${compose[@]}" build mapping
fi
"${compose[@]}" up -d --wait --wait-timeout 60 mock-inference
"${compose[@]}" run --rm --no-deps -T mapping
