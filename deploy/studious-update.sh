#!/usr/bin/env bash
# Pull the :main image and roll the container over to it when it changed.
# Run by studious-update.timer every few minutes (docs/deploy.md). The droplet
# pulls; nothing pushes to it, and CI holds no credential for the droplet.
#
# Each run:
#   1. takes a lock, so two runs cannot overlap;
#   2. pulls $STUDIOUS_IMAGE and compares its ID with the running container's;
#   3. when they differ, skips the rollout while any job is queued or running
#      (jobs do not survive a restart, docs/hosting.md) and tries again on the
#      next run;
#   4. otherwise runs `docker compose up -d` and waits for the healthcheck;
#   5. on an unhealthy result, retags the previous image back and restarts it,
#      remembers the bad image ID, and exits non-zero so `systemctl status` and
#      the journal show it;
#   6. after a good rollout prunes dangling images. The previous image stays,
#      tagged :previous, for a rollback by hand.
#
# The API has no endpoint that lists jobs, so "busy" is read from the data
# directory: one JSON file per job in $DATA_DIR/jobs with a "status" field
# (backend/app/services/storage.py). queued and running count as busy. A job
# file last written more than $JOBS_STALE_MIN minutes ago is a leftover from a
# crash, not work in progress, and is ignored, or the timer would skip forever.
#
# Every path and name comes from the environment with the production default,
# so scripts/deploy-selftest.sh runs this against a fake `docker` and a temp
# directory. Needs bash, flock (util-linux) and docker with the compose plugin.
set -euo pipefail

IMAGE="${STUDIOUS_IMAGE:-ghcr.io/zurt/studious:main}"
CONTAINER="${CONTAINER:-studious}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/studious/compose.yml}"
DATA_DIR="${DATA_DIR:-/srv/studious/data}"
STATE_DIR="${STATE_DIR:-/var/lib/studious}"
LOCK_FILE="${LOCK_FILE:-/run/lock/studious-update.lock}"
JOBS_STALE_MIN="${JOBS_STALE_MIN:-360}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-3}"
PREVIOUS_IMAGE="${IMAGE%:*}:previous"
FAILED_FILE="$STATE_DIR/failed-image"

log() { echo "studious-update: $*"; }

mkdir -p "$STATE_DIR"

# Only one run at a time. A second run while the first waits for a healthcheck
# is harmless to skip: the timer fires again.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another run holds the lock, skipping"
  exit 0
fi

# Job files that count as work in progress. Prints their paths.
busy_jobs() {
  local jobs_dir="$DATA_DIR/jobs"
  [ -d "$jobs_dir" ] || return 0
  find "$jobs_dir" -maxdepth 1 -name '*.json' -mmin "-$JOBS_STALE_MIN" \
    -exec grep -lE '"status": *"(queued|running)"' {} + 2>/dev/null || true
}

stale_jobs() {
  local jobs_dir="$DATA_DIR/jobs"
  [ -d "$jobs_dir" ] || return 0
  find "$jobs_dir" -maxdepth 1 -name '*.json' -mmin "+$JOBS_STALE_MIN" \
    -exec grep -lE '"status": *"(queued|running)"' {} + 2>/dev/null || true
}

# 0 when the container reports healthy within $HEALTH_TIMEOUT seconds.
wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) running=none health=none
  while [ "$SECONDS" -lt "$deadline" ]; do
    running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo false)"
    health="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo none)"
    [ "$health" = "healthy" ] && return 0
    if [ "$health" = "unhealthy" ]; then
      log "container is unhealthy"
      return 1
    fi
    sleep "$HEALTH_INTERVAL"
  done
  log "container not healthy after ${HEALTH_TIMEOUT}s (running=$running, health=$health)"
  return 1
}

# docker compose up -d, then wait. 0 only when the container comes up healthy.
bring_up() {
  if ! docker compose -f "$COMPOSE_FILE" up -d; then
    log "docker compose up failed"
    return 1
  fi
  wait_healthy
}

current_id="$(docker inspect --format '{{.Image}}' "$CONTAINER" 2>/dev/null || true)"

if ! docker pull --quiet "$IMAGE" >/dev/null; then
  log "cannot pull $IMAGE. If the error says denied or unauthorized, the GHCR package is still private (docs/troubleshooting.md)"
  exit 1
fi
new_id="$(docker image inspect --format '{{.Id}}' "$IMAGE")"

if [ -z "$current_id" ]; then
  log "no container named $CONTAINER yet: first install of $new_id"
else
  if [ "$new_id" = "$current_id" ]; then
    log "up to date ($new_id)"
    exit 0
  fi
  if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$new_id" ]; then
    log "$new_id failed its healthcheck on an earlier run and was rolled back. Waiting for a newer :main (rm $FAILED_FILE to try it again)"
    exit 1
  fi
  stale="$(stale_jobs)"
  if [ -n "$stale" ]; then
    log "ignoring job files not updated for ${JOBS_STALE_MIN} minutes (crash leftovers): $(echo "$stale" | tr '\n' ' ')"
  fi
  busy="$(busy_jobs)"
  if [ -n "$busy" ]; then
    log "new image $new_id is waiting: a job is queued or running ($(echo "$busy" | tr '\n' ' ')). Jobs do not survive a restart, so trying again next run"
    exit 0
  fi
  log "rolling out $new_id (running: $current_id)"
  # Keep the old image reachable by name, so the prune below cannot take it.
  docker tag "$current_id" "$PREVIOUS_IMAGE"
fi

if bring_up; then
  rm -f "$FAILED_FILE"
  log "rollout done: $new_id is healthy"
  docker image prune -f >/dev/null || log "image prune failed (ignored)"
  exit 0
fi

# The new image did not come up. Put the old one back.
if [ -z "$current_id" ]; then
  log "first install did not become healthy and there is no previous image to go back to. Read: docker logs $CONTAINER"
  exit 1
fi
echo "$new_id" >"$FAILED_FILE"
log "rolling back to $current_id"
docker tag "$current_id" "$IMAGE"
if bring_up; then
  log "rolled back: $current_id is healthy again. $new_id is marked bad until a newer :main arrives"
else
  log "the rollback to $current_id is not healthy either. Read: docker logs $CONTAINER"
fi
exit 1
