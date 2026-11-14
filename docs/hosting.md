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

Inventory for step 8, taken 2026-11-13 across the backend, the web app, the
Apple package and the build scripts. Nothing here is fixed. In the container
none of these crashes the server; each reports itself unavailable.

| Feature | What it calls | On the droplet | Who notices |
|---|---|---|---|
| Card audio, `say` engine (the default, and what the owner uses) | `say` and `say -v '?'` as subprocesses (`tts.py`) | Unavailable: `/api/tts/status` gives the reason, `/api/vocab/{id}/audio` and `/api/tts/test` answer 503 | Study dashboard play button, speech settings, audio on Anki pushes |
| Card audio, VOICEVOX / AivisSpeech engine | HTTP on `STUDIOUS_TTS_URL` (default `127.0.0.1:50021`), then `afconvert` for AAC | Unavailable unless the URL points at a reachable host; clips stay `.wav` because `afconvert` is macOS only | Same as above |
| Anki state import ("already in Anki" badges) | AnkiConnect on `ANKI_CONNECT_URL` (default `127.0.0.1:8765`), read actions only (`anki.py`) | 503 "Anki is not reachable"; the last `data/refs/anki/snapshot.json` keeps working but goes stale | Vocab store badges, the sync button |
| Anki push (shortlist to deck) | AnkiConnect `createDeck` and `addNotes` (`anki_push.py`), plus card audio per note | 503; with Anki reachable but speech not, cards go without audio | Push dialog |
| Mac app and `studious-sync` | Read and write `backend/data/store/*.jsonl` directly | The files are no longer on the Mac (step 7) | Mac app, CLI, and iOS through CloudKit |
| Mac app settings | Health check on `127.0.0.1:8000`, "Open web app" link to `localhost:5173` (`SettingsView.swift`) | Both point at nothing | Mac app settings pane |

Details that matter for the fix:

- **Cached clips do not survive the move.** `synthesize` checks that the
  engine is available before it looks in `data/audio/`, and the cache key
  includes the voice name, so the existing clips (23 files, under 1 MB) are
  never served on Linux. They are cheap to regenerate; do not bother
  migrating them.
- **Audio is made on first play, on the server.** The web app never uses the
  browser's own speech synthesis; it plays `/api/vocab/{id}/audio`.
- **Anki only answers while the Anki desktop app is open on the Mac**, so
  both Anki features already depend on the Mac being awake, wherever the
  backend runs. AnkiConnect listens on `127.0.0.1` only by default.
- **Messages name the Mac.** "Open Anki on this Mac" (`anki.py`), "needs
  macOS with the ... voice installed" (`anki-push-dialog.ts`), "store your
  token in the Keychain" (`api/store.py`, WaniKani). Reword when the fix
  lands.

Not affected:

- **Keychain** is a convenience of the Makefile for starting the backend on
  the Mac; the app reads plain environment variables.
- **Tesseract** is installed in the image, so the OCR provider works.
- **WaniKani sync** and the Anthropic API are outbound HTTPS.
- **`backend/scripts/build_seed.py`** reads fonts from `/System/Library/Fonts`,
  but it only regenerates the committed seed PDF and runs on the Mac.
- **Apple builds, `make test-apple`, benchmarks and the model eval** stay on
  the Mac by design.

### New homes (decided 2026-11-13)

- **Anki: reach the Mac over Tailscale.** The Mac can be expected to be on
  for Anki exchanges, since Anki itself must be open. On the Mac,
  publish AnkiConnect to the tailnet without changing its bind address
  (`tailscale serve --tcp 8765 tcp://127.0.0.1:8765` or the equivalent;
  not yet tried); the droplet sets `ANKI_CONNECT_URL` to the Mac's tailnet
  name. No code change beyond the messages. Set an AnkiConnect API key if
  any other tailnet device is not trusted.
- **Speech: VOICEVOX on the droplet**, so that audio never needs the Mac.
  Feasible, but not on the 1 GB droplet (measurements below), so the
  owner chose a 2 GB droplet. It also costs a second container, one fixed speaker, and a lower cap on
  the text sent in one synthesis call. The voice changes from the Mac's
  Kyoko family to a VOICEVOX character. Wrapping `say` on the Mac is the
  fallback if this disappoints.
- **Mac app:** covered by step 7; the two hard-coded URLs become one
  backend URL setting.

### VOICEVOX memory and speed

Measured 2026-11-13 with `voicevox/voicevox_engine:cpu-latest` (engine
0.26.1, 2.1 GB image, linux/arm64 under Docker Desktop on the owner's Mac),
limited to one CPU. A droplet's x86 vCPU will differ, so repeat the timing
there.

| Text sent in one call | Time on one CPU | Peak memory |
|---|---|---|
| 2 characters (a word) | 2 s | about 205 MiB |
| 33 characters | 9 s | 342 MiB |
| 66 characters | 19 s | 528 MiB |
| 99 characters | 26 s | 735 MiB |
| 198 characters (near `MAX_CHARS`) | 51 s | 1,478 MiB |

- Idle, before any synthesis: 89 MiB. Ready about 4 seconds after start.
- **Memory grows with the length of the text**, roughly 7 MiB per
  character. Capped at 512 MiB the engine was OOM-killed on a 208-character
  text. Words and example sentences (8 to 25 characters) stay under
  350 MiB, so either lower the limit for this engine or split long text by
  sentence and join the clips.
- **Each further voice model stays loaded.** Eight speakers from different
  model files took the engine from 342 MiB to 1,853 MiB. Use one speaker.
- **Speed is about a quarter of a second per character on one CPU.**
  Without the CPU limit the same 21-character sentence took half a second.
  Clips are cached, so only the first play waits; an Anki push of 20 new
  cards with word and sentence audio would take a few minutes.
- With Studious peaking at 437 MiB (below), the two together need about
  800 MiB plus the system: too tight for 1 GB, comfortable in 2 GB.
- The image has no `afconvert`, so clips stay `.wav` (190 KB for a
  sentence) until the Studious image gains a converter such as `ffmpeg`.

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
Tailscale. The earlier 2 GB estimate is more than Studious alone asks
for; the droplet is 2 GB anyway because VOICEVOX runs beside it (see
"VOICEVOX memory and speed").

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
