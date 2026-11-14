#!/usr/bin/env bash
# Pull the latest code; rebuild and restart the container only when it changed.
set -euo pipefail
cd /opt/aiquant/src
OLD=$(git rev-parse HEAD 2>/dev/null || echo none)
git fetch -q --depth 1 origin main && git reset -q --hard origin/main
NEW=$(git rev-parse HEAD)
if [ "$OLD" != "$NEW" ] || ! sudo docker ps --format '{{.Names}}' | grep -q '^aiquant$'; then
  sudo docker build -q -t aiquant . >/dev/null
  sudo docker rm -f aiquant >/dev/null 2>&1 || true
  sudo docker run -d --name aiquant --restart unless-stopped --env-file /opt/aiquant/env \
    -p 127.0.0.1:10000:10000 aiquant >/dev/null
  echo "$(date -u +%FT%TZ) deployed ${NEW::7}"
fi
