#!/bin/bash
# Run one generator instance at a time.  Cron treats a held lock as a skipped
# overlapping run, preserving the last complete feed.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec flock -n "$DIR/generate.lock" python3 "$DIR/generate.py"
