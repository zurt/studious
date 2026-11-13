# Hosting

How Studious is meant to run away from the Mac, what exists today, and what
is not done yet. The decision (2026-11-13, `next-steps.md` session 1): one
container on a small DigitalOcean droplet, reachable only over Tailscale,
real data on a volume, its own API key with a spend cap, encrypted backups.
CI builds the image and deploys it, so no deploy credential sits on the
laptop.

## Status

| Piece | State |
|---|---|
| Image (`Dockerfile`), settings, compose file, `make docker-*` | Written. CI builds it and runs a smoke test on every push (`docker` job). |
| Run against the real data, measure memory | Done 2026-11-13 on a copy of the real library: 437 MiB peak, and it survives a 512 MiB cap. See "Memory" below. |
| Droplet, Tailscale, backups, CI deploy, data move | Not done (`next-steps.md`, session 1, step 6). |
| Mac and iOS apps talking to the API instead of the files | Not done (step 7). |
| Features that need the Mac (speech, Anki) | Inventoried below; not fixed (step 8). |

Rejected: public HTTPS behind a reverse proxy with basic auth. It works from
anywhere, but then a password is all that stands between the internet and the
Anthropic key. The API has no authentication, so the network is the
authentication.

## The image

One container serves the API and the built frontend from the same origin.

- **Stage 1** (Node 24, `npm ci`, `npm run build`) builds `frontend/dist`. The
  stage fails if the base image's npm is older than 11.10, because
  `frontend/.npmrc` relies on `min-release-age`, which older npm ignores
  silently. The pinned image ships npm 11.19.1 (from the Node release index).
- **Stage 2** (Python 3.13 on Debian trixie slim) installs tesseract with the
  Japanese packs, then the backend from `backend/uv.lock` with
  `uv sync --frozen --no-dev` (dependency layer before code). It copies only
  `backend/app`, `refs.lock.json` and `scripts/fetch_refs.py`. The sample
  textbook seed (`backend/seed/`) is dev-only and is not in the image.
- Runs as UID 10001 (`studious`), `/data` is the volume, uvicorn listens on
  `0.0.0.0:8000` inside the container, no `--reload`. The healthcheck calls
  `/api/health` with Python, so curl is not installed.
- No secrets and no `.env` in the image (`.dockerignore` keeps `.env*`,
  `backend/data`, `backend/.dev-data`, `apple/`, `docs/` and the rest out of
  the build context). Keys arrive as environment variables at run time.

Pinning: `node`, `python` and `uv` are pinned to a version tag and the digest
of the multi-arch index (the digests were read from the registries, not from
a local pull). The uv version was more than 7 days old when pinned, in line
with the repo's cooldown rule. Dependabot's `docker` entry proposes new tags
and digests weekly with the same 7-day cooldown as the other ecosystems.

## Build and run locally

```bash
make docker-build            # docker build -t studious:local .
make docker-run              # mock VLM, throwaway named volume, http://127.0.0.1:8000
make docker-smoke            # the checks CI runs (scripts/docker-smoke.sh)
```

`make docker-run` never touches `backend/data`: `/data` is a named Docker
volume (`studious-local-data`) unless you set `DOCKER_DATA`. To run the real
model, give it an env file that is not committed:

```bash
printf 'ANTHROPIC_API_KEY=...\n' > .env.docker      # gitignored
make docker-run DOCKER_VLM=anthropic DOCKER_ENV_FILE=.env.docker
```

A host directory used as `/data` must be writable by UID 10001 (a named
volume is, because Docker copies the image's ownership into it).
`docker-compose.yml` does the same thing as a single service, publishing the
port on `127.0.0.1` only.

The smoke test (`scripts/docker-smoke.sh`) starts the image with
`STUDIOUS_VLM_PROVIDER=mock` and an empty volume, waits for the healthcheck,
and checks: `/api/health`; `/` is the built `index.html`; a deep path
(`/some/deep/spa/path`) returns the same `index.html`; a built JS asset is
served as JavaScript; an unknown `/api/...` path is a JSON 404, not HTML;
`/api/providers` reports the mock; the process is not root; no `.env` file is
in the image; `/data` is writable. It prints the image size and
`docker stats` memory, and fails on any check.

Reference data (JMdict, JLPT lists) is not baked in. Build it into the volume
once: `docker exec <container> python scripts/fetch_refs.py`.

## Settings

| Variable | Meaning | Default |
|---|---|---|
| `STUDIOUS_STATIC_DIR` | Directory with the built frontend. When set and it holds `index.html`, the backend serves it at `/` with a fallback to `index.html` for unknown paths. Registered after every API route, so `/api/*` always wins and an unknown `/api/...` path stays a JSON 404. | unset (vite serves the frontend in dev); `/app/frontend-dist` in the image |
| `STUDIOUS_CORS_ORIGINS` | Comma-separated CORS allowlist. Only needed when the frontend is served from another origin than the API (the vite dev server). | `http://localhost:5173` |
| `STUDIOUS_DATA_DIR` | The one data directory. | `./data`; `/data` in the image |
| `STUDIOUS_VLM_PROVIDER` | `anthropic` or `mock`. | `anthropic` |

A `STUDIOUS_STATIC_DIR` that does not exist, or has no `index.html`, is
ignored silently and the backend runs API-only.

## Things that stay true when it runs remotely

- **No authentication on any endpoint.** That includes the recursive document
  delete and the transcribe and breakdown endpoints, which spend the API key.
  Publish nothing on a public interface; the compose file binds loopback, and
  the droplet plan is Tailscale only. Deferred findings (upload size limits,
  reconnect on the job progress stream) are in
  `docs/archive/audit-2026-07-mobile-spike.md`.
- **State is one directory.** `STUDIOUS_DATA_DIR` holds documents, page
  images, transcriptions, jobs, the vocab/grammar store, the review log, the
  LLM audit log and reference caches. One volume to mount, one path to back
  up. The store is append-only JSONL, so incremental backups are small. There
  is no database.
- **The frontend is host-agnostic.** Every call uses relative `/api/...`
  paths, so serving `dist` from the backend, or through a proxy, just works.
- **Progress streams are SSE.** A proxy must not buffer them (Caddy:
  `flush_interval -1`; nginx: `proxy_buffering off` and a long
  `proxy_read_timeout`). `openJobStream` in `frontend/src/api.ts` closes on
  the first error with no reconnect, so a network blip freezes job progress
  until reload. Harmless on localhost; worth fixing before relying on it
  remotely.
- **Jobs do not survive a restart.** Check the jobs view is idle before
  restarting or deploying.
- **Uploads are unbounded.** Cap the body size at the proxy if there is one.
- **Region of the droplet** matters only for the round trip to the Anthropic
  API; jobs are API-latency-bound, not CPU-bound.

## What leaving the Mac breaks

Today the backend, the Mac app (`studious-mac`) and the sync CLI all read and
write the same `backend/data/store/*.jsonl` files, and iOS syncs against that
store through CloudKit or file export. There is no HTTP contract between the
backend and the Apple apps. Once the backend runs on a droplet:

- The web app, uploads, transcription, breakdowns, harvest, enrichment and
  web study sessions are unaffected; they live behind the HTTP API.
- The Mac app's direct file access and `studious-sync` no longer see the
  backend's store. Moving them to the API is step 7 of the plan.
- Do not sync the store directory with a file-sync tool: it replaces whole
  files and races against appends, and the store assumes appenders.

### Features that need the Mac

Inventory for step 8 (from `backend/app/services/`; nothing here is fixed).
In the container none of these crashes the server; each reports itself
unavailable.

- **macOS `say` voices** (`tts.py`, the default `STUDIOUS_TTS_ENGINE=say`).
  `_say_info` returns not-ok with "The Mac voice needs macOS with the `say`
  command" when `sys.platform != "darwin"` or `say` is missing. The speech
  status endpoint reports that reason, and the audio endpoints
  (`api/store.py`) answer 503 with it.
- **VOICEVOX / AivisSpeech** (`STUDIOUS_TTS_ENGINE=voicevox`) is an HTTP
  service on `STUDIOUS_TTS_URL` (default `http://127.0.0.1:50021`). Inside a
  container `127.0.0.1` is the container itself, so it reports unavailable
  unless the URL points at a reachable host. Its WAV output is converted to
  AAC with `afconvert` (macOS); without it the clip stays `.wav`, which still
  plays.
- **Anki through AnkiConnect** (`anki.py`, `anki_push.py`) calls
  `ANKI_CONNECT_URL` (default `http://127.0.0.1:8765`). Unreachable raises
  `AnkiUnavailable`, which the API turns into a 503 with the message "Anki is
  not reachable at ... Open Anki on this Mac"; the push endpoints do the same.
  Audio
  attached to a push degrades per clip (the failure is logged and counted, the
  card is sent without audio).
- **Keychain** is only a convenience of the Makefile for starting the backend
  on the Mac; the app itself reads plain environment variables. One error
  message in `api/store.py` (WaniKani) still says "Keychain".
- **Tesseract** is installed in the image, so the OCR provider works.

## Memory

Measured 2026-11-13 on the owner's Mac (Docker Desktop, linux/arm64). The
image is 818 MB. The container ran against a copy of the real library (728 MB,
copied into a Docker volume from a read-only mount) with the mock VLM, one
step at a time. The figures are the container's cgroup memory, peak per step:

| Step | Peak (MiB) |
|---|---|
| Idle after startup | 99 |
| Browsing: document list, 25 page images, vocab, grammar, study queue | 236 |
| Tesseract OCR job, 4 pages | 389 |
| Mock VLM transcription job, 6 pages (image preparation only) | 288 |
| Upload of a 197-page PDF, rendered at 300 DPI | 429 |
| Whole run | 437 |

The same run with the container capped at 512 MiB and no swap
(`--memory=512m --memory-swap=512m`) completed every step with the same
peak and was never killed.

What this supports: the app fits in 512 MiB with about 70 MiB to spare on
this workload, so a 1 GB droplet leaves room for the OS, Docker and
Tailscale. The earlier 2 GB estimate is more than this evidence asks for.

What it does not cover:

- x86-64. The droplet will not be arm64; expect similar numbers, not the
  same ones.
- Real model calls. The mock stands in for the Anthropic client, so the
  request and response handling of a real transcription is not in the
  figures.
- Concurrency. Two jobs at once, or an upload during an OCR job, were not
  tried.
- `fetch_refs.py` (the JMdict SQLite build) was not run in the container;
  the copied library already had its refs.

CI prints the idle numbers for an empty mock instance in the `docker` job
log (62 MiB locally), which is a floor, not the answer.

## Not done yet

- A droplet, the Tailscale setup (`tailscale serve` for HTTPS on the tailnet),
  the firewall, and the dedicated API key with a spend cap.
- Encrypted, tested backups of the data volume.
- CI deploy: push the image to a registry and roll it out, with no
  credential on the laptop. The `docker` job only builds and tests.
- Moving the real data off `backend/data`.
