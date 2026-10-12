#!/bin/bash
# Serves the generated lidarr-discovery.json feed over plain HTTP so Lidarr's
# "Custom List" import type can pull it as a list URL.
#
# Bound to all interfaces (not just loopback) since Lidarr often reaches host
# services through a container network gateway rather than 127.0.0.1. Only
# the feed is exposed: the server's root is a dedicated directory holding a
# symlink to the generated JSON, so the scripts, logs and lock file in the
# repo are not reachable. Still, don't expose the port beyond your own network.

set -euo pipefail

PORT="${PORT:-8098}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_PATH="${OUT_PATH:-$DIR/lidarr-discovery.json}"
FEED_DIR="$DIR/.feed"

if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  echo "already listening on :${PORT}"
  exit 0
fi

mkdir -p "$FEED_DIR"
ln -sfn "$OUT_PATH" "$FEED_DIR/lidarr-discovery.json"

cd "$DIR"
nohup python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$FEED_DIR" >> serve.log 2>&1 &
disown
echo "serving $FEED_DIR on :${PORT}"
