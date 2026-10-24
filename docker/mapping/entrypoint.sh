#!/usr/bin/env bash
set -euo pipefail
mkdir -p /tmp/dubdash-runtime
chmod 700 /tmp/dubdash-runtime
export XDG_RUNTIME_DIR=/tmp/dubdash-runtime
exec /usr/bin/supervisord -n -c /etc/supervisor/dubdash.conf
