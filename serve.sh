#!/bin/bash
# Serves the generated lidarr-discovery.json feed over plain HTTP so Lidarr's
# "Custom List" import type can pull it as a list URL.
#
# Bound to all interfaces (not just loopback) since Lidarr often reaches host
# services through a container network gateway rather than 127.0.0.1. This
# only serves the generated JSON (a list of public MusicBrainz artist IDs) --
# no sensitive data, but don't expose the port beyond your own network.

set -euo pipefail

PORT="${PORT:-8098}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  echo "already listening on :${PORT}"
  exit 0
fi

cd "$DIR"
nohup python3 -m http.server "$PORT" --bind 0.0.0.0 >> serve.log 2>&1 &
disown
echo "serving $DIR on :${PORT}"
