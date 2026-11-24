#!/usr/bin/env bash
# Back up the data directory with restic, then thin out old snapshots.
# Run daily by studious-backup.timer (docs/deploy.md), and by
# studious-update.sh just before it rolls out a new image (BACKUP_KIND below).
#
# The container keeps running while this reads. That is acceptable: the vocab
# and grammar store is append-only JSONL, and every other file is written by an
# atomic temp-file rename, so a reader sees a whole old file or a whole new one.
# The worst case is a snapshot that is a few seconds behind, or a file that
# vanishes under restic mid-run (restic exits 3 and still saves the snapshot;
# that is logged as a warning here, not a failure).
#
# Settings come from the environment, with production defaults, so the
# selftest (scripts/deploy-selftest.sh) can run this against a temp directory
# and a local repository:
#   DATA_DIR          what to back up                    (/srv/studious/data)
#   RESTIC_ENV_FILE   root-only file with RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE
#                     and the B2 keys; skipped when absent (/etc/studious/restic.env)
#   RESTIC            the restic binary                  (restic)
#   BACKUP_HOST       host name recorded in snapshots, so a renamed droplet
#                     keeps one history                  (studious)
#   BACKUP_KIND       daily or pre-rollout; becomes a snapshot tag. Only a
#                     daily run thins out snapshots           (daily)
#   KEEP_DAILY / KEEP_WEEKLY / KEEP_MONTHLY   for daily snapshots (7 / 4 / 12)
#   KEEP_PRE_ROLLOUT  how long pre-rollout snapshots stay     (14d)
#   RESTIC_BACKUP_ARGS  extra arguments for `restic backup`, e.g. "--exclude refs"
set -euo pipefail

DATA_DIR="${DATA_DIR:-/srv/studious/data}"
RESTIC_ENV_FILE="${RESTIC_ENV_FILE:-/etc/studious/restic.env}"
RESTIC="${RESTIC:-restic}"
BACKUP_HOST="${BACKUP_HOST:-studious}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"
KEEP_PRE_ROLLOUT="${KEEP_PRE_ROLLOUT:-14d}"
BACKUP_KIND="${BACKUP_KIND:-daily}"

log() { echo "studious-backup: $*"; }
fail() { echo "studious-backup: FAIL: $*" >&2; exit 1; }

if [ -f "$RESTIC_ENV_FILE" ]; then
  mode="$(stat -c '%a' "$RESTIC_ENV_FILE" 2>/dev/null || echo unknown)"
  case "$mode" in
    600 | 400 | unknown) ;;
    *) log "warning: $RESTIC_ENV_FILE has mode $mode, it holds keys: chmod 600" ;;
  esac
  set -a
  # shellcheck source=/dev/null
  . "$RESTIC_ENV_FILE"
  set +a
fi

case "$BACKUP_KIND" in
  daily | pre-rollout) ;;
  *) fail "BACKUP_KIND must be daily or pre-rollout, not '$BACKUP_KIND'" ;;
esac

[ -d "$DATA_DIR" ] || fail "data directory $DATA_DIR does not exist"
[ -n "${RESTIC_REPOSITORY:-}" ] || fail "RESTIC_REPOSITORY is not set (see $RESTIC_ENV_FILE)"
[ -n "${RESTIC_PASSWORD_FILE:-}${RESTIC_PASSWORD:-}" ] || fail "no RESTIC_PASSWORD_FILE set"

log "backing up $DATA_DIR to $RESTIC_REPOSITORY"
status=0
# --retry-lock: the 03:30 backup and a rollout's backup can meet; wait for the
# other one's lock instead of failing.
# RESTIC_BACKUP_ARGS is split on purpose: it holds a few plain flags.
# shellcheck disable=SC2086
"$RESTIC" backup "$DATA_DIR" --host "$BACKUP_HOST" --tag studious --tag "$BACKUP_KIND" \
  --retry-lock 10m ${RESTIC_BACKUP_ARGS:-} || status=$?
case "$status" in
  0) ;;
  3) log "warning: some files could not be read (changed during the backup); the snapshot was saved" ;;
  *) fail "restic backup exited $status" ;;
esac

# A pre-rollout run stops here: it should be quick, and prune takes the
# repository's exclusive lock.
if [ "$BACKUP_KIND" != "daily" ]; then
  log "done ($BACKUP_KIND snapshot saved, no retention)"
  exit 0
fi

# Two policies, one per kind. With a single --keep-daily over every `studious`
# snapshot, only the last snapshot of each day survives, so the pre-rollout
# snapshots from earlier in the day would be forgotten the next night: exactly
# the ones a "restore to before that rollout" needs.
# --host keeps the policy to this machine's snapshots. `--tag a,b` means a
# snapshot with both tags. A snapshot tagged only `studious` (taken by hand) is
# in neither pass and is never forgotten, which is safe.
log "applying retention: $KEEP_DAILY daily, $KEEP_WEEKLY weekly, $KEEP_MONTHLY monthly; pre-rollout for $KEEP_PRE_ROLLOUT"
# --prune on both passes: restic prunes only when that same call forgot
# something, so a single prune on the second pass would leave the first pass's
# data in the repository on most nights.
"$RESTIC" forget --retry-lock 10m --prune --host "$BACKUP_HOST" --tag studious,daily \
  --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" \
  || fail "restic forget exited non-zero"
"$RESTIC" forget --retry-lock 10m --prune --host "$BACKUP_HOST" --tag studious,pre-rollout \
  --keep-within "$KEEP_PRE_ROLLOUT" \
  || fail "restic forget (pre-rollout) exited non-zero"

log "done"
