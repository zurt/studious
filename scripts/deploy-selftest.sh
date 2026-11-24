#!/usr/bin/env bash
# Test the droplet tooling in deploy/ without a droplet, Docker, root or B2.
#
#   scripts/deploy-selftest.sh        (or: make deploy-selftest)
#
# Three parts, all Linux only (they use flock, timeout, GNU date/find/stat, and
# restic):
#   1. studious-update.sh against a fake `docker` on PATH, a stub backup and a
#      temp data directory: new image + idle -> pre-rollout backup, then
#      rollout (a failed backup only warns; a job that appears during it skips
#      the rollout); new image + a running job -> skipped; unhealthy after
#      rollout -> rollback and non-zero exit; and the edge cases around them.
#   2. The read-only user's wrappers (studious-logs, studious-stats) against
#      the same fake docker: argument checks, and docker is never called on a
#      bad one.
#   3. studious-backup.sh and studious-restore-test.sh against a local restic
#      repository: a good round trip passes; files changed since the snapshot
#      are tolerated; a checksum mismatch, bad JSONL and a damaged repository
#      each fail; pre-rollout snapshots are tagged and survive a daily run's
#      retention.
# Used by the `deploy` job in .github/workflows/ci.yml, which installs restic
# from apt. Touches nothing outside a temp directory, removed on exit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$(cd "$HERE/../deploy" && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/deploy-selftest.XXXXXX")"
trap 'rm -rf "$T"' EXIT

passed=0
failed=0
RC=0

# Run a command, keeping its output in $T/out.txt and its status in $RC.
run() {
  RC=0
  "$@" >"$T/out.txt" 2>&1 || RC=$?
}
pass() {
  passed=$((passed + 1))
  echo "ok: $1"
}
bad() {
  failed=$((failed + 1))
  echo "FAIL: $1"
  sed 's/^/    | /' "$T/out.txt"
}
expect_ok() {
  local name="$1"
  shift
  run "$@"
  if [ "$RC" -eq 0 ]; then pass "$name"; else bad "$name (exit $RC, wanted 0)"; fi
}
expect_fail() {
  local name="$1"
  shift
  run "$@"
  if [ "$RC" -ne 0 ]; then pass "$name"; else bad "$name (exit 0, wanted non-zero)"; fi
}
expect_output() {
  local name="$1" pattern="$2"
  if grep -Eq "$pattern" "$T/out.txt"; then pass "$name"; else bad "$name (no match for: $pattern)"; fi
}
expect_equal() {
  local name="$1" want="$2" got="$3"
  if [ "$want" = "$got" ]; then
    pass "$name"
  else
    echo "wanted '$want', got '$got'" >"$T/out.txt"
    bad "$name"
  fi
}

# ---- 1. studious-update.sh ----------------------------------------------------

S="$T/fake"
mkdir -p "$S" "$T/bin" "$T/data/jobs" "$T/state"

# A fake docker. It keeps what the update script reads in files under
# $FAKE_STATE: tag.<image> (the ID a name points at), running_id (the
# container's image; absent when there is no container), bad_ids (IDs whose
# container reports unhealthy), registry_id (what a pull fetches), pull_fails.
cat >"$T/bin/docker" <<'FAKE'
#!/usr/bin/env bash
S="${FAKE_STATE:?}"
echo "$*" >>"$S/calls"
tagfile() { echo "$S/tag.$(echo "$1" | tr '/:' '__')"; }
resolve() {
  case "$1" in
    sha256:*) echo "$1" ;;
    *) cat "$(tagfile "$1")" 2>/dev/null ;;
  esac
}
case "$1" in
  pull)
    [ ! -f "$S/pull_fails" ] || { echo "denied" >&2; exit 1; }
    cat "$S/registry_id" >"$(tagfile "${@: -1}")"
    ;;
  image)
    case "$2" in
      inspect)
        id="$(resolve "${@: -1}")"
        [ -n "$id" ] || exit 1
        echo "$id"
        ;;
    esac
    ;;
  inspect)
    [ -f "$S/running_id" ] || exit 1
    case "$3" in
      '{{.Image}}') cat "$S/running_id" ;;
      '{{.State.Running}}') if [ -f "$S/stopped" ]; then echo false; else echo true; fi ;;
      '{{.State.Health.Status}}')
        if grep -qxF "$(cat "$S/running_id")" "$S/bad_ids" 2>/dev/null; then echo unhealthy; else echo healthy; fi
        ;;
    esac
    ;;
  tag) resolve "$2" >"$(tagfile "$3")" ;;
  compose)
    resolve ghcr.io/zurt/studious:main >"$S/running_id"
    rm -f "$S/stopped"
    ;;
esac
FAKE
chmod +x "$T/bin/docker"

# flock is in util-linux; a stub keeps the update tests runnable on a machine
# without it (the real lock is what runs in CI and on the droplet).
if ! command -v flock >/dev/null; then
  printf '#!/bin/sh\nexit 0\n' >"$T/bin/flock"
  chmod +x "$T/bin/flock"
fi

# A stub for studious-backup.sh. It records the kind and how many compose calls
# had happened (to show the backup comes first), exits with the code in
# $T/backup_rc, and when $T/backup_job exists starts a job, as one arriving
# during the backup would.
cat >"$T/backup-stub.sh" <<'STUB'
#!/usr/bin/env bash
echo "$BACKUP_KIND compose_before=$(grep -c '^compose' "$FAKE_STATE/calls" || true)" >>"$BACKUP_CALLS"
[ ! -f "$BACKUP_JOB" ] || echo '{"id": "jx", "status": "running"}' >"$BACKUP_JOB_FILE"
exit "$(cat "$BACKUP_RC" 2>/dev/null || echo 0)"
STUB
chmod +x "$T/backup-stub.sh"
# The file exists from the start, so a count with no calls is 0, not empty.
: >"$T/backup_calls"
backup_calls() { grep -c . "$T/backup_calls" || true; }

upd() {
  env PATH="$T/bin:$PATH" FAKE_STATE="$S" DATA_DIR="$T/data" STATE_DIR="$T/state" \
    LOCK_FILE="$T/lock" COMPOSE_FILE="$T/compose.yml" HEALTH_TIMEOUT=2 HEALTH_INTERVAL=0.2 \
    JOBS_STALE_MIN=60 BACKUP_CMD="$T/backup-stub.sh" PRE_ROLLOUT_BACKUP_TIMEOUT=30 \
    BACKUP_CALLS="$T/backup_calls" BACKUP_RC="$T/backup_rc" BACKUP_JOB="$T/backup_job" \
    BACKUP_JOB_FILE="$T/data/jobs/jx.json" bash "$DEPLOY/studious-update.sh"
}
reset_calls() { : >"$S/calls"; }
compose_calls() { grep -c '^compose' "$S/calls" || true; }
running() { cat "$S/running_id" 2>/dev/null || echo none; }
tag_of() { cat "$S/tag.ghcr.io_zurt_studious_$1" 2>/dev/null || echo none; }
old_file() { touch -d '3 hours ago' "$1"; }

# First install: no container yet, so no job check and no previous image.
echo sha256:aaa >"$S/registry_id"
reset_calls
expect_ok "update: first install" upd
expect_equal "update: first install runs the new image" sha256:aaa "$(running)"
expect_equal "update: first install takes no backup" 0 "$(backup_calls)"

# Nothing new: no rollout.
reset_calls
expect_ok "update: same image" upd
expect_output "update: same image says up to date" "up to date"
expect_equal "update: same image does not touch compose" 0 "$(compose_calls)"
expect_equal "update: same image takes no backup" 0 "$(backup_calls)"

# Same image, but the container was stopped by hand: started again.
touch "$S/stopped"
reset_calls
expect_ok "update: same image + stopped container" upd
expect_output "update: stopped container is started" "starting it"
expect_equal "update: stopped container calls compose once" 1 "$(compose_calls)"
expect_equal "update: restarting a stopped container takes no backup" 0 "$(backup_calls)"

# New image, but a job is running: skipped, exit 0, container untouched.
echo sha256:bbb >"$S/registry_id"
echo '{"id": "j1", "status": "running"}' >"$T/data/jobs/j1.json"
reset_calls
expect_ok "update: new image + running job is skipped" upd
expect_output "update: skip says why" "job is queued or running"
expect_equal "update: skip leaves the container alone" sha256:aaa "$(running)"
expect_equal "update: skip does not call compose" 0 "$(compose_calls)"
expect_equal "update: a skipped rollout takes no backup" 0 "$(backup_calls)"

# A queued job counts too.
echo '{"id": "j1", "status": "completed"}' >"$T/data/jobs/j1.json"
echo '{"id": "j2", "status": "queued"}' >"$T/data/jobs/j2.json"
reset_calls
expect_ok "update: new image + queued job is skipped" upd
expect_equal "update: queued job does not call compose" 0 "$(compose_calls)"

# A finished job does not block, and a stale "running" job (a crash leftover)
# is ignored.
rm "$T/data/jobs/j2.json"
echo '{"id": "j3", "status": "running"}' >"$T/data/jobs/j3.json"
old_file "$T/data/jobs/j3.json"
reset_calls
expect_ok "update: new image + idle (stale job ignored) rolls out" upd
expect_output "update: rollout is logged" "rollout done"
expect_equal "update: rollout runs the new image" sha256:bbb "$(running)"
expect_equal "update: rollout takes one pre-rollout backup, before compose" "pre-rollout compose_before=0" "$(cat "$T/backup_calls")"
expect_output "update: backup is logged" "pre-rollout backup done"
expect_equal "update: the previous image is kept as :previous" sha256:aaa "$(tag_of previous)"
if grep -q '^image prune' "$S/calls"; then pass "update: prunes after a good rollout"; else echo "no prune call" >"$T/out.txt" && bad "update: prunes after a good rollout"; fi

# A new image that never becomes healthy: roll back, exit non-zero.
rm -f "$T/data/jobs/"*.json
echo sha256:ccc >"$S/registry_id"
echo sha256:ccc >"$S/bad_ids"
reset_calls
expect_fail "update: unhealthy rollout exits non-zero" upd
expect_output "update: rollback is logged" "rolling back to sha256:bbb"
expect_equal "update: rollback runs the previous image again" sha256:bbb "$(running)"

# The same bad image is not retried every tick.
reset_calls
expect_fail "update: a known-bad image is not retried" upd
expect_equal "update: known-bad image does not call compose" 0 "$(compose_calls)"

# A newer good image goes out again.
echo sha256:ddd >"$S/registry_id"
reset_calls
expect_ok "update: a newer image after a rollback rolls out" upd
expect_equal "update: newer image is running" sha256:ddd "$(running)"

# A first install that is unhealthy has nothing to go back to.
rm -f "$S/running_id" "$T/state/failed-image"
echo sha256:ddd >"$S/bad_ids"
expect_fail "update: unhealthy first install exits non-zero" upd
expect_output "update: no rollback target is said" "no previous image"

# A pull that is refused (private package) is an error, not a rollout.
rm -f "$S/bad_ids"
echo sha256:ddd >"$S/running_id"
touch "$S/pull_fails"
expect_fail "update: a refused pull exits non-zero" upd
expect_output "update: refused pull points at the package visibility" "package is still private"
rm -f "$S/pull_fails"

# A failing backup (B2 down, or a timeout) only warns; the rollout happens.
echo sha256:eee >"$S/registry_id"
echo 3 >"$T/backup_rc"
: >"$T/backup_calls"
reset_calls
expect_ok "update: a failed backup does not stop the rollout" upd
expect_output "update: failed backup is logged as a warning" "pre-rollout backup failed \(exit 3\); rolling out anyway"
expect_equal "update: rollout went ahead after the failed backup" sha256:eee "$(running)"
expect_equal "update: failed-backup rollout tried the backup once" 1 "$(backup_calls)"

# A job that starts while the backup runs: skip the rollout, exit 0.
echo sha256:fff >"$S/registry_id"
echo 0 >"$T/backup_rc"
touch "$T/backup_job"
: >"$T/backup_calls"
reset_calls
expect_ok "update: a job appearing during the backup skips the rollout" upd
expect_output "update: says the job started during the backup" "job started during the backup"
expect_equal "update: skipped after the backup leaves the container alone" sha256:eee "$(running)"
expect_equal "update: skipped after the backup does not call compose" 0 "$(compose_calls)"
expect_equal "update: that skip had taken the backup" 1 "$(backup_calls)"
rm -f "$T/backup_job" "$T/data/jobs/jx.json"

# ---- 2. the read-only user's wrappers --------------------------------------------

logs() { env PATH="$T/bin:$PATH" FAKE_STATE="$S" bash "$DEPLOY/studious-logs.sh" "$@"; }
stats() { env PATH="$T/bin:$PATH" FAKE_STATE="$S" bash "$DEPLOY/studious-stats.sh" "$@"; }
docker_calls() { wc -l <"$S/calls" | tr -d ' '; }

reset_calls
expect_ok "logs: no argument" logs
expect_equal "logs: defaults to 200 lines" "logs --tail 200 studious" "$(cat "$S/calls")"
reset_calls
expect_ok "logs: a number" logs 50
expect_equal "logs: passes the number on" "logs --tail 50 studious" "$(cat "$S/calls")"
for bad_arg in 0 5001 abc "1; rm" -5 123456789012345678901234567890; do
  reset_calls
  run logs "$bad_arg"
  expect_equal "logs: '$bad_arg' exits 2" 2 "$RC"
  expect_equal "logs: '$bad_arg' does not call docker" 0 "$(docker_calls)"
done
reset_calls
run logs 5 6
expect_equal "logs: two arguments exit 2" 2 "$RC"
expect_equal "logs: two arguments do not call docker" 0 "$(docker_calls)"
reset_calls
expect_ok "stats: no argument" stats
expect_equal "stats: runs docker stats once" "stats --no-stream" "$(cat "$S/calls")"
reset_calls
run stats --all
expect_equal "stats: an argument exits 2" 2 "$RC"
expect_equal "stats: an argument does not call docker" 0 "$(docker_calls)"

# ---- 3. backup and restore test --------------------------------------------------

if ! command -v restic >/dev/null; then
  echo "restic is not installed: skipping the backup round trip (apt install restic)" >&2
  echo "$passed passed, $failed failed, backup round trip NOT run"
  [ "$failed" -eq 0 ] || exit 1
  exit 0
fi

D="$T/live"
REPO="$T/repo"
mkdir -p "$D/store" "$D/documents/d1" "$T/restore"
printf '{"id":"a","kind":"vocab"}\n{"id":"b","kind":"vocab"}\n' >"$D/store/vocab.jsonl"
printf '{"item":"a","grade":3}\n' >"$D/store/reviews.jsonl"
head -c 20000 /dev/urandom >"$D/documents/d1/page-1.png"
printf '# transcription\n' >"$D/documents/d1/t.md"
printf 'selftest-passphrase' >"$T/pw"
chmod 600 "$T/pw"
cat >"$T/restic.env" <<EOF
RESTIC_REPOSITORY=$REPO
RESTIC_PASSWORD_FILE=$T/pw
EOF
chmod 600 "$T/restic.env"

# Local repository, no root: the same variables the droplet sets, other paths.
tooling_env() {
  env DATA_DIR="$D" RESTIC_ENV_FILE="$T/restic.env" RESTIC_CACHE_DIR="$T/cache" \
    RESTORE_TMP="$T/restore" CTIME_MARGIN=0 CHECK_READ_DATA_SUBSET=100% "$@"
}
bk() { tooling_env "$@" bash "$DEPLOY/studious-backup.sh"; }
rt() { tooling_env "$@" bash "$DEPLOY/studious-restore-test.sh"; }

# shellcheck disable=SC2016
run tooling_env bash -c 'set -a; . "$RESTIC_ENV_FILE"; restic init'
[ "$RC" -eq 0 ] || {
  bad "restic init"
  exit 1
}

# Files need a ctime older than the snapshot to be checked.
sleep 2
expect_ok "backup: first backup" bk
expect_output "backup: applies retention" "applying retention"
expect_ok "restore test: good round trip" rt
expect_output "restore test: compares older files by checksum" "[1-9][0-9]* files older than the snapshot match"
expect_equal "restore test: leaves no temp directory" 0 "$(find "$T/restore" -mindepth 1 | wc -l | tr -d ' ')"

# A pre-rollout backup is tagged as such and does not thin out snapshots. After
# daily, pre-rollout, daily, pre-rollout runs, a daily run's retention leaves
# one daily snapshot (KEEP_DAILY=1 and nothing else, so the count does not
# depend on when in the week the test runs) and both pre-rollout ones, which a
# single policy over all of them would have dropped as same-day duplicates.
count_tag() {
  # shellcheck disable=SC2016
  tooling_env bash -c 'set -a; . "$RESTIC_ENV_FILE"; restic snapshots --json --tag "$1"' _ "$1" |
    python3 -c 'import json, sys; print(len(json.load(sys.stdin)))'
}
expect_ok "backup: a pre-rollout backup" bk BACKUP_KIND=pre-rollout
expect_output "backup: a pre-rollout run skips retention" "no retention"
expect_equal "backup: the snapshot is tagged pre-rollout" 1 "$(count_tag pre-rollout)"
expect_ok "backup: a daily run" bk KEEP_DAILY=1 KEEP_WEEKLY=0 KEEP_MONTHLY=0
expect_ok "backup: a second pre-rollout backup" bk BACKUP_KIND=pre-rollout
expect_ok "backup: a daily run applies retention" bk KEEP_DAILY=1 KEEP_WEEKLY=0 KEEP_MONTHLY=0
expect_equal "backup: retention leaves one daily snapshot" 1 "$(count_tag daily)"
expect_equal "backup: retention keeps both pre-rollout snapshots" 2 "$(count_tag pre-rollout)"
expect_fail "backup: an unknown BACKUP_KIND fails" bk BACKUP_KIND=weekly

# Only store/ when asked, and automatically when the disk is too small.
expect_ok "restore test: subset store" rt RESTORE_SUBSET=store
expect_output "restore test: subset store says so" "restoring store/"

# The app keeps writing after the snapshot: that must not fail the test.
sleep 1
printf '{"id":"c","kind":"vocab"}\n' >>"$D/store/vocab.jsonl"
printf 'new\n' >"$D/documents/d1/added-later.md"
expect_ok "restore test: tolerates files changed since the snapshot" rt

# With the margin pushed past the snapshot, that same change is a mismatch.
expect_fail "restore test: a checksum mismatch fails" rt CTIME_MARGIN=-3600
expect_output "restore test: names the differing file" "differs from the restore: store/vocab.jsonl"

# An incomplete last line (a live append caught mid-write) is tolerated ...
sleep 1
printf '{"id":"d","ki' >>"$D/store/vocab.jsonl"
expect_ok "backup: snapshot with a half-written last line" bk
expect_ok "restore test: tolerates an incomplete last line" rt
expect_output "restore test: warns about it" "incomplete, ignored"

# ... but a bad line in the middle is not.
printf '\nnot json at all\n{"id":"e"}\n' >>"$D/store/vocab.jsonl"
expect_ok "backup: snapshot with a corrupt store file" bk
expect_fail "restore test: invalid JSONL fails" rt
expect_output "restore test: names the bad line" "bad JSON: .*vocab.jsonl"

# Repair, back up again: the latest snapshot is what is tested.
printf '{"id":"a","kind":"vocab"}\n' >"$D/store/vocab.jsonl"
expect_ok "backup: snapshot after the repair" bk
expect_ok "restore test: passes again" rt

# A damaged repository is caught by restic check.
pack="$(find "$REPO/data" -type f | head -n 1)"
chmod u+w "$pack"
head -c 4096 /dev/urandom >"$pack"
expect_fail "restore test: a damaged repository fails" rt
expect_equal "restore test: leaves no temp directory after a failure" 0 "$(find "$T/restore" -mindepth 1 | wc -l | tr -d ' ')"

echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
