#!/usr/bin/env bash
# One screen of "is it healthy?" for the read-only user. Installed root-owned
# as /usr/local/sbin/studious-status and run through sudo
# (deploy/sudoers-studious-ro), because docker needs root or the docker group
# and that user is in neither. Takes no arguments.
#
# Each section runs on its own: a failing command prints its error and the
# next section still runs.
#   CONTAINER, DATA_DIR  as in studious-update.sh
#   HEALTH_URL           (http://127.0.0.1:8000/api/health)
set -euo pipefail

CONTAINER="${CONTAINER:-studious}"
DATA_DIR="${DATA_DIR:-/srv/studious/data}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"

[ "$#" -eq 0 ] || {
  echo "usage: studious-status (no arguments)" >&2
  exit 2
}

section() { printf '\n== %s ==\n' "$1"; }

section "failed units"
systemctl --failed --no-pager || true
section "timers"
systemctl list-timers 'studious-*' --no-pager || true
section "containers"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' || true
section "health ($CONTAINER)"
curl -fsS --max-time 5 "$HEALTH_URL" || echo "unreachable"
echo
section "disk"
df -h / "$DATA_DIR" || true
section "memory (MB)"
free -m || true
