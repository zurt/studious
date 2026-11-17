#!/usr/bin/env bash
# Prove the backups can be restored. Run weekly by studious-restore-test.timer
# (docs/deploy.md); run it by hand after the first backup.
#
# What it does, failing (exit 1) on the first problem:
#   1. `restic check` on the repository, reading a random slice of the data
#      packs (CHECK_READ_DATA_SUBSET, default 5%; empty turns the read off);
#   2. restores the latest snapshot into a temp directory (removed on exit);
#   3. the restore holds files, and every store/*.jsonl in it parses: one JSON
#      value per line. A last line with no newline is a half-written append
#      caught by the live backup and is tolerated with a warning;
#   4. every live file whose ctime is older than the snapshot (minus CTIME_MARGIN, a minute)
#      is in the restore with the same sha256. Newer files are skipped, since
#      the app keeps writing while the snapshot ages. ctime, not mtime: a
#      rename or an rsync keeps the mtime but changes the ctime.
#
# Disk. The restore needs the snapshot's full size free in RESTORE_TMP, and a
# 1 GB droplet's disk is small (the library was 728 MB on 2026-11-13, page
# images included). RESTORE_SUBSET picks what to restore:
#   auto   (default) everything when it fits in 70% of the free space, else
#          only store/ with a warning
#   full   everything; fails when it does not fit
#   store  only store/ (the vocab/grammar store and review log, which are the
#          part that cannot be rebuilt). Page images and transcriptions are
#          then checked only by `restic check`.
#
# Settings come from the environment with production defaults, so the selftest
# can run it against a temp directory and a local repository:
#   DATA_DIR, RESTIC_ENV_FILE, RESTIC, BACKUP_HOST  as in studious-backup.sh
#   RESTORE_TMP       where the temp directory goes       (/var/tmp)
#   RESTORE_SUBSET    auto | full | store                  (auto)
#   CHECK_READ_DATA_SUBSET                                 (5%)
#   CTIME_MARGIN      seconds before the snapshot a file must have
#                     last changed to be compared           (60)
# Needs GNU coreutils and findutils (Linux) and python3 (for the JSON check).
set -euo pipefail

DATA_DIR="${DATA_DIR:-/srv/studious/data}"
DATA_DIR="${DATA_DIR%/}"
RESTIC_ENV_FILE="${RESTIC_ENV_FILE:-/etc/studious/restic.env}"
RESTIC="${RESTIC:-restic}"
BACKUP_HOST="${BACKUP_HOST:-studious}"
RESTORE_TMP="${RESTORE_TMP:-/var/tmp}"
RESTORE_SUBSET="${RESTORE_SUBSET:-auto}"
CHECK_READ_DATA_SUBSET="${CHECK_READ_DATA_SUBSET-5%}"
CTIME_MARGIN="${CTIME_MARGIN:-60}"

log() { echo "studious-restore-test: $*"; }
fail() { echo "studious-restore-test: FAIL: $*" >&2; exit 1; }

if [ -f "$RESTIC_ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$RESTIC_ENV_FILE"
  set +a
fi

[ -d "$DATA_DIR" ] || fail "data directory $DATA_DIR does not exist"
[ -n "${RESTIC_REPOSITORY:-}" ] || fail "RESTIC_REPOSITORY is not set (see $RESTIC_ENV_FILE)"
case "$RESTORE_SUBSET" in auto | full | store) ;; *) fail "RESTORE_SUBSET must be auto, full or store" ;; esac

target=""
cleanup() {
  status=$?
  if [ -n "$target" ]; then rm -rf "$target"; fi
  exit "$status"
}
trap cleanup EXIT

# 1. Repository integrity.
log "restic check${CHECK_READ_DATA_SUBSET:+ (reading $CHECK_READ_DATA_SUBSET of the data)}"
if [ -n "$CHECK_READ_DATA_SUBSET" ]; then
  "$RESTIC" check --read-data-subset="$CHECK_READ_DATA_SUBSET" || fail "restic check failed"
else
  "$RESTIC" check || fail "restic check failed"
fi

# The snapshot to restore, and when it was taken.
snap_json="$("$RESTIC" snapshots --latest 1 --host "$BACKUP_HOST" --tag studious --json)" \
  || fail "cannot list snapshots"
snap_time="$(echo "$snap_json" | grep -o '"time": *"[^"]*"' | head -n 1 | cut -d'"' -f4)"
[ -n "$snap_time" ] || fail "no snapshot found for host $BACKUP_HOST (has studious-backup run?)"
snap_epoch="$(date -d "$snap_time" +%s)" || fail "cannot read the snapshot time '$snap_time'"
log "latest snapshot: $snap_time"

# Choose what to restore. The size comes from restic; if that cannot be read,
# assume it does not fit rather than fill the disk.
stats_json="$("$RESTIC" stats --mode restore-size --host "$BACKUP_HOST" --tag studious --json latest)" \
  || fail "cannot read the snapshot size"
snap_bytes="$(echo "$stats_json" | grep -o '"total_size": *[0-9]*' | head -n 1 | cut -d: -f2 | tr -d ' ')"
mkdir -p "$RESTORE_TMP"
free_bytes="$(df --output=avail -B1 "$RESTORE_TMP" | tail -n 1 | tr -d ' ')"
fits=no
if [ -n "$snap_bytes" ] && [ "$((snap_bytes * 10))" -le "$((free_bytes * 7))" ]; then fits=yes; fi

subset="$RESTORE_SUBSET"
if [ "$subset" = "auto" ]; then
  if [ "$fits" = "yes" ]; then
    subset=full
  else
    subset=store
    log "warning: the snapshot (${snap_bytes:-unknown} bytes) does not fit in 70% of the ${free_bytes} bytes free in $RESTORE_TMP: restoring store/ only"
  fi
elif [ "$subset" = "full" ] && [ "$fits" != "yes" ]; then
  fail "the snapshot (${snap_bytes:-unknown} bytes) does not fit in 70% of the ${free_bytes} bytes free in $RESTORE_TMP; use RESTORE_SUBSET=store"
fi

# 2. Restore.
target="$(mktemp -d "$RESTORE_TMP/studious-restore.XXXXXX")"
restored="$target$DATA_DIR"
if [ "$subset" = "store" ]; then
  scope_live="$DATA_DIR/store"
  scope_restored="$restored/store"
  log "restoring store/ of the latest snapshot into $target"
  "$RESTIC" restore latest --host "$BACKUP_HOST" --tag studious --target "$target" --include "$scope_live" \
    || fail "restic restore failed"
else
  scope_live="$DATA_DIR"
  scope_restored="$restored"
  log "restoring the whole latest snapshot into $target"
  "$RESTIC" restore latest --host "$BACKUP_HOST" --tag studious --target "$target" \
    || fail "restic restore failed"
fi

# 3. Contents.
count="$(find "$scope_restored" -type f 2>/dev/null | wc -l | tr -d ' ')"
[ "$count" -gt 0 ] || fail "the restore holds no files"
log "restored $count files"

live_jsonl="$(find "$DATA_DIR/store" -maxdepth 1 -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
restored_jsonl="$(find "$restored/store" -maxdepth 1 -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
if [ "$live_jsonl" -gt 0 ] && [ "$restored_jsonl" -eq 0 ]; then
  fail "the live data has $live_jsonl store/*.jsonl files and the restore has none"
fi

json_check='
import json, sys
bad = 0
for path in sys.argv[1:]:
    with open(path, "rb") as f:
        lines = f.read().split(b"\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except ValueError:
            if i == len(lines) - 1:
                print("warning: %s: last line has no newline and is incomplete, ignored" % path)
                continue
            print("bad JSON: %s line %d" % (path, i + 1))
            bad += 1
sys.exit(1 if bad else 0)
'
if [ "$restored_jsonl" -gt 0 ]; then
  find "$restored/store" -maxdepth 1 -name '*.jsonl' -print0 \
    | xargs -0 python3 -I -c "$json_check" \
    || fail "a restored store file is not valid JSONL"
  log "$restored_jsonl store files parse"
fi

# 4. Files older than the snapshot match the live ones.
cutoff=$((snap_epoch - CTIME_MARGIN))
checked=0
bad=0
while IFS= read -r -d '' live; do
  rel="${live#"$DATA_DIR"/}"
  copy="$restored/$rel"
  if [ ! -f "$copy" ]; then
    echo "studious-restore-test: missing from the restore: $rel" >&2
    bad=$((bad + 1))
    continue
  fi
  a="$(sha256sum "$live" | cut -d' ' -f1)"
  b="$(sha256sum "$copy" | cut -d' ' -f1)"
  if [ "$a" != "$b" ]; then
    echo "studious-restore-test: differs from the restore: $rel" >&2
    bad=$((bad + 1))
  fi
  checked=$((checked + 1))
done < <(find "$scope_live" -type f -not -newerct "@$cutoff" -print0)
[ "$bad" -eq 0 ] || fail "$bad of $((checked + bad)) older files do not match the snapshot"
log "$checked files older than the snapshot match by checksum"

log "ok (restored: $subset)"
