#!/usr/bin/env bash
# Smoke-test the Studious image: run it with the mock VLM and an empty data
# volume, wait until Docker reports it healthy, then check the hosted-mode
# behaviour from the outside. Exits non-zero on the first failed check.
#
#   scripts/docker-smoke.sh [image]        (default image: studious:smoke)
#
# Used by the `docker` job in .github/workflows/ci.yml; run it the same way
# locally after `make docker-build`. Needs docker and curl. It touches no
# real data: the volume is a fresh one, removed on exit.
set -euo pipefail

IMAGE="${1:-studious:smoke}"
PORT="${SMOKE_PORT:-18000}"
NAME="studious-smoke-$$"
VOLUME="studious-smoke-data-$$"
BASE="http://127.0.0.1:${PORT}"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- container logs (smoke test failed) ---"
    docker logs "$NAME" 2>&1 | tail -n 60 || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

echo "image: $IMAGE"
docker image ls "$IMAGE" --format 'image size: {{.Size}}'

docker volume create "$VOLUME" >/dev/null
docker run -d --name "$NAME" \
  -p "127.0.0.1:${PORT}:8000" \
  -v "${VOLUME}:/data" \
  -e STUDIOUS_VLM_PROVIDER=mock \
  "$IMAGE" >/dev/null

echo "waiting for the container to become healthy (up to 120 s)"
health=""
for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$NAME")"
  running="$(docker inspect --format '{{.State.Running}}' "$NAME")"
  [ "$running" = "true" ] || fail "container exited early"
  [ "$health" = "healthy" ] && break
  sleep 2
done
[ "$health" = "healthy" ] || fail "container never became healthy (last status: $health)"
ok "container healthy"

# /api/health
body="$(curl -fsS "$BASE/api/health")"
[ "$body" = '{"ok":true}' ] || fail "/api/health returned: $body"
ok "/api/health"

# The built frontend at / and at a deep SPA path.
root="$(curl -fsS "$BASE/")"
echo "$root" | grep -qi '<!doctype html' || fail "/ is not an HTML document"
echo "$root" | grep -q '/assets/' || fail "/ does not reference built assets (is it index.html from vite build?)"
ok "/ serves the built index.html"
deep="$(curl -fsS "$BASE/some/deep/spa/path")"
[ "$deep" = "$root" ] || fail "deep SPA path did not return index.html"
ok "deep SPA path falls back to index.html"

# A built asset is really served (not the HTML fallback).
asset="$(echo "$root" | grep -o '/assets/[^"]*\.js' | head -n 1)"
[ -n "$asset" ] || fail "no .js asset referenced from index.html"
ctype="$(curl -fsS -o /dev/null -w '%{content_type}' "$BASE$asset")"
case "$ctype" in
  *javascript*) ok "asset $asset served as $ctype" ;;
  *) fail "asset $asset served as $ctype" ;;
esac

# Unknown API paths stay a JSON 404, never the HTML shell.
code="$(curl -sS -o "${TMPDIR:-/tmp}/smoke-404.$$" -w '%{http_code} %{content_type}' "$BASE/api/does-not-exist")"
case "$code" in
  "404 application/json"*) ok "unknown /api path is a JSON 404" ;;
  *) fail "unknown /api path returned: $code" ;;
esac
rm -f "${TMPDIR:-/tmp}/smoke-404.$$"

# The mock VLM is what is running.
providers="$(curl -fsS "$BASE/api/providers")"
echo "$providers" | grep -Eq '"mock" *: *true' || fail "/api/providers does not report the mock VLM: $providers"
ok "/api/providers reports the mock VLM"

# Not root, and nothing secret baked in.
uid="$(docker exec "$NAME" id -u)"
[ "$uid" != "0" ] || fail "container process runs as root"
ok "runs as uid $uid"
docker exec "$NAME" sh -c 'find /app /data \( -name ".env" -o -name ".env.*" \) -not -name ".env.example" 2>/dev/null | grep -q .' \
  && fail "an env file exists inside the image"
ok "no .env file inside the image"
docker exec "$NAME" sh -c 'test -w /data' || fail "/data is not writable by the container user"
ok "/data is writable"

echo "--- resource use ---"
docker stats --no-stream --format 'memory: {{.MemUsage}} ({{.MemPerc}})  cpu: {{.CPUPerc}}' "$NAME"
echo "all smoke checks passed"
