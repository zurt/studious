#!/usr/bin/env bash
# The container's last N log lines, for the read-only user. Installed
# root-owned as /usr/local/sbin/studious-logs and run through sudo
# (deploy/sudoers-studious-ro). sudoers cannot check the argument, so this
# does: a plain number from 1 to 5000, nothing else reaches docker.
#
#   studious-logs [N]     N defaults to 200
#   CONTAINER             (studious)
set -euo pipefail

CONTAINER="${CONTAINER:-studious}"

usage() {
  echo "usage: studious-logs [N]   (N from 1 to 5000, default 200)" >&2
  exit 2
}

[ "$#" -le 1 ] || usage
n="${1:-200}"
[[ "$n" =~ ^[0-9]+$ ]] || usage
# 10# so a leading zero is not read as octal. Five digits at most, so the
# arithmetic cannot overflow on a long string of digits.
[ "${#n}" -le 5 ] || usage
n=$((10#$n))
{ [ "$n" -ge 1 ] && [ "$n" -le 5000 ]; } || usage

exec docker logs --tail "$n" "$CONTAINER"
