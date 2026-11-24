#!/usr/bin/env bash
# CPU and memory of the running containers, once. For the read-only user:
# installed root-owned as /usr/local/sbin/studious-stats and run through sudo
# (deploy/sudoers-studious-ro). Takes no arguments.
set -euo pipefail

[ "$#" -eq 0 ] || {
  echo "usage: studious-stats (no arguments)" >&2
  exit 2
}

exec docker stats --no-stream
