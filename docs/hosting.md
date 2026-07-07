# Hosting the backend on a DigitalOcean droplet

Guidance for decoupling the FastAPI backend from the local machine,
written 2026-07-07 alongside the codebase audit
(`docs/audit-2026-07-mobile-spike.md`). The container/prep changes
described under "What was added" are already on this branch and do not
change local dev.

## TL;DR recommendation

Host it as **one Docker container behind Caddy**, with the droplet
reachable **either** over Tailscale (zero auth work, recommended if you
already use Tailscale or are willing to install it on your devices)
**or** publicly over HTTPS with Caddy's `basic_auth` in front (needs a
domain). Do **not** expose the API without one of those two — it has no
authentication, and it can delete your library and spend your Anthropic
credits.

Keep the SRS/store sync exactly as it is (CloudKit / file
export-import between your devices); the droplet hosts the
transcription pipeline and web app. The one structural casualty of the
move is **bridge mode** — see "What moving the backend breaks" below,
including the recommended follow-up (a small HTTP sync endpoint) if
you want the droplet's store and your devices' stores to converge
automatically.

## Current state (what the audit established)

- **No auth on any endpoint.** Includes `DELETE /api/documents/{id}`
  (recursive delete) and the transcribe/breakdown endpoints, which
  forward client-supplied `model`/`max_tokens` to the Anthropic API on
  your key. Fine on loopback; a public-internet incident otherwise.
- **CORS** was hardcoded to `http://localhost:5173`; now configurable
  (`STUDIOUS_CORS_ORIGINS`), and moot when the backend serves the
  built frontend itself (same origin).
- **The frontend is already host-agnostic**: every call in `api.ts`
  uses relative `/api/...` paths; no hardcoded origins anywhere in
  `frontend/src`. Serving `frontend/dist` from any origin just works.
- **State is one directory**: `STUDIOUS_DATA_DIR` holds documents,
  page images, transcriptions, jobs, the vocab/grammar store, the
  review log, the LLM audit log, and reference caches. One volume to
  mount, one path to back up.
- **Secrets** (`ANTHROPIC_API_KEY`, `WANIKANI_API_TOKEN`) come from the
  environment / `.env`; they are never logged.
- The server binds loopback by default (`make dev-backend` has no
  `--host`); the Docker image binds `0.0.0.0` *inside* the container
  and compose publishes it to `127.0.0.1` on the host only.

## What was added on this branch (all inert for local dev)

| Piece | What it does |
|---|---|
| `Dockerfile` | Multi-stage: builds `frontend/dist` with node 22, installs the backend with `uv sync --frozen` (lockfile verbatim, cooldown not re-resolved), installs tesseract (+jpn), serves everything with uvicorn on :8000. |
| `docker-compose.yml` | One service; publishes `127.0.0.1:8000` only; mounts `./data` as the data volume; reads `.env`. |
| `.dockerignore` | Keeps data, venvs, node_modules, apple/, benchmarks out of the build context. |
| `STUDIOUS_STATIC_DIR` | When set, FastAPI serves the built frontend at `/` with an SPA fallback (unknown paths → `index.html`, `/api/*` always wins). The container sets it; local dev leaves it unset and keeps vite. |
| `STUDIOUS_CORS_ORIGINS` | Comma-separated CORS allowlist, default unchanged (`http://localhost:5173`). Only needed if you serve the frontend from a *different* origin than the API. |
| `make docker-build` / `make docker-up` | Convenience targets. |

Verified in this environment: frontend build, frozen backend install,
and hosted mode end-to-end (health, static index, SPA fallback for
`/vocab` and deep links, API precedence, CORS env parsing). The
**docker image build itself could not be executed here** (the
sandbox's network policy blocks the Docker Hub/GHCR CDNs) — run
`make docker-build` once locally or on the droplet as a smoke test.

## What moving the backend breaks: bridge mode

Today the Mac is the hub: the backend, the Mac app (`studious-mac`),
and the sync CLI (`studious-sync`) all read/write the *same*
`backend/data/store/*.jsonl` files, and iOS syncs with that canonical
store via CloudKit or file export/import. There is **no HTTP contract
between the backend and the Apple apps** — the integration surface is
the shared filesystem plus replicated merge semantics.

Put the backend on a droplet and that shared filesystem is gone:

- **Web app, uploads, transcription, breakdowns, harvest, enrichment,
  dashboards, web study sessions — all fine.** They live entirely
  behind the HTTP API. New harvests land in the droplet's store and
  the web UI sees them immediately.
- **Mac app bridge mode and `studious-sync` no longer see the
  backend's store.** The CLI can't run on the droplet (CloudKit needs
  Apple platforms + a signed binary). So harvested items appear in
  the web app but not on iOS/Mac automatically, and reviews/edits made
  on the devices don't reach the droplet.

Options, in increasing order of effort:

1. **Manual file transfer (works day one).** The store files are plain
   JSONL and merging is idempotent LWW/union on both sides.
   Periodically `scp`/`rsync` `droplet:/…/data/store/*.jsonl` to the
   Mac, run `studious-sync merge --from <dir>` (or the Mac app's
   Import), and push device-side changes back the same way
   (`studious-sync export`, `scp` up, then merge on the droplet — a
   merge there needs nothing more than appending lines the backend
   already knows how to read, but see option 3 for doing it properly).
   Clunky but zero new code, and no data-loss risk thanks to the merge
   semantics.
2. **Syncthing/rsync the store directory continuously.** Tempting,
   **not recommended**: file-level sync tools replace whole files and
   race against concurrent appends; the store's safety model assumes
   appenders, not replacers.
3. **Add a small HTTP sync endpoint (recommended follow-up).** The
   store design makes this almost trivial and transport-agnostic:
   - `GET /api/store/changes?since=<byte-offset-or-line-cursor>` →
     new JSONL lines per file (vocab/grammar/reviews) plus the new
     cursor. Append-only files make "changes since" a byte offset.
   - `POST /api/store/merge` → body is JSONL lines; the server applies
     items with the same LWW rule (`updated_at`, tombstones win) and
     unions review events by id. This is exactly what
     `ItemStore.merge`/`ReviewLog.union` do in Swift and what a
     ~40-line Python function can do server-side (the audit confirmed
     semantics parity).
   - Then `studious-sync` grows a `--remote https://…` mode (or the
     Mac app calls it directly), and the Mac remains the CloudKit
     bridge for iOS. Devices ↔ Mac stays CloudKit; Mac ↔ droplet
     becomes HTTP. iOS could later talk to the droplet directly and
     drop CloudKit entirely, but that's a bigger decision (auth on
     device, offline queueing) — don't start there.

## Access model: pick one

### Option A — Tailscale (recommended for a single user)

- Install Tailscale on the droplet, your Mac, and your iPhone; the
  droplet gets a stable `100.x` address / MagicDNS name.
- Publish nothing on the public interface (the compose file already
  binds loopback; either use `tailscale serve` to front :8000 with
  HTTPS on the tailnet, or bind the compose port to the tailscale IP).
- **Pros:** no auth code needed at all (network *is* the auth), no
  domain, no certificates to manage (tailscale serve does TLS),
  invisible to scanners. **Cons:** devices must run Tailscale; no
  sharing with others without inviting them to the tailnet.

### Option B — Public HTTPS + Caddy basic auth (needs a domain)

- Point `study.example.com` at the droplet; run Caddy with automatic
  Let's Encrypt.
- Basic auth at the proxy protects every route including SSE and
  uploads (the browser attaches credentials automatically —
  app-level bearer tokens would break `EventSource`, which can't set
  headers; that's why proxy-level auth is the right first move).
- **Pros:** works from anywhere, nothing to install on clients.
  **Cons:** you own the exposure: keep Caddy updated, expect scanner
  noise, and basic-auth credentials are all that stands between the
  internet and your Anthropic key. Use a long random password.

Caddyfile that covers the important details (SSE, uploads, size cap):

```caddyfile
study.example.com {
    basic_auth {
        # caddy hash-password
        you $2a$14$...hashed...
    }
    reverse_proxy 127.0.0.1:8000 {
        # SSE: don't buffer job-progress streams
        flush_interval -1
    }
    request_body {
        max_size 200MB   # textbook PDFs; the app has no cap of its own yet
    }
}
```

(nginx works too but needs `proxy_buffering off`,
`proxy_read_timeout` ≥ the longest job, and `client_max_body_size` —
Caddy's defaults get more of this right, hence the recommendation.)

## Droplet runbook

Sizing: **2 GB RAM minimum** (PyMuPDF at 300 DPI on large pages plus
the JMdict SQLite build are the peaks; 1 GB works with swap but
uploads of big textbooks will crawl). 1 vCPU is fine — the job worker
is deliberately sequential. Disk: page images dominate; a rendered
300-page textbook at 300 DPI is roughly 1–2 GB, so size the volume for
your library and prefer a block-storage volume you can grow.

```bash
# 1. Base setup (Ubuntu 24.04 droplet)
apt update && apt install -y docker.io docker-compose-v2   # or Docker's official repo
ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable    # skip 80/443 for Tailscale-only

# 2. Get the code and configure
git clone https://github.com/zurt/studious.git && cd studious
cp .env.example .env       # then edit: set ANTHROPIC_API_KEY=... (no Keychain on Linux)
                           # optionally WANIKANI_API_TOKEN=...

# 3. Build and run
make docker-up             # = docker compose up -d --build
curl -s localhost:8000/api/health   # {"ok":true}

# 4. Front it (pick your access model)
#    Tailscale:  tailscale up && tailscale serve --bg 8000
#    Public:     install caddy, use the Caddyfile above

# 5. Reference data (JMdict enrichment), once, inside the container:
docker compose exec studious uv run --no-sync python scripts/fetch_refs.py
```

Updates: `git pull && make docker-up` (compose rebuilds; the uv/npm
layers cache so rebuilds are quick). In-flight jobs do not survive a
restart (same as local dev) — check the jobs UI is idle first.

Backups: everything is `./data` next to the compose file. A nightly
`restic`/`rclone` push to DO Spaces or Backblaze of that one directory
is a complete backup; the JSONL stores are append-only so incremental
backups are tiny. Test a restore once: `STUDIOUS_DATA_DIR` pointed at
a restored copy must boot cleanly (it will — there's no database).

The `.env` on the droplet now holds your real Anthropic key on disk —
that's a deliberate departure from the repo's Keychain guidance
(Linux has no Keychain). `chmod 600 .env`, and treat droplet root
access as key access. DO's reserved metadata/firewalls don't protect
it; the container never logs it.

## Things to do before/soon after going remote

Ranked; the first is non-negotiable, the rest are quality-of-life.

1. **Auth in front (Tailscale or Caddy basic_auth)** — see above. The
   API itself trusts every caller.
2. **SSE resilience in the frontend** (`api.ts` `openJobStream`): it
   closes the stream on the first error with no reconnect and no
   status poll fallback. On localhost this never fires; through a
   proxy an idle blip permanently freezes job progress in the UI until
   reload. Fix: on `onerror`, retry with backoff and/or poll
   `GET /api/jobs/{id}` for terminal status. (Deliberately not done in
   this pass — it deserves its own tested change.)
3. **Upload limits**: enforce `max_size` at the proxy now (done in the
   Caddyfile above); later add an app-level cap + page-count sanity
   check so a fat-fingered 2 GB PDF fails fast instead of rendering
   for an hour.
4. **Rate/abuse guard on LLM endpoints** if the service is ever shared
   beyond you: per-day token budget or job-count cap, reusing the LLM
   audit log (it already records per-call tokens and cost).
5. **Latency check for VLM traffic**: the droplet region changes the
   round-trip to the Anthropic API; pick a US region (or wherever your
   account's endpoint is fastest) — transcription jobs are
   API-latency-bound, not CPU-bound.
6. **Container hardening** (nice-to-have): run as a non-root user
   (needs a `chown` on the data volume), pin the uv image tag instead
   of `latest`, add `docker compose logs` rotation
   (`logging: options: max-size`).

## What was deliberately NOT done

- **No app-level auth**: bearer tokens break `EventSource`, cookies
  need a login flow — proxy/network auth is strictly better for a
  single-user deployment, and doing auth properly is its own project.
- **No droplet-side store sync endpoint** (option 3 above): it touches
  the sync semantics that the Apple apps replicate; design it with the
  golden-test discipline the FSRS port used, not as a hosting side
  quest.
- **No Kubernetes/managed-DB/anything**: file-based storage on one
  small droplet with one backup path is the right shape for this tool.
  A managed Postgres would add operational surface and remove the
  JSONL properties the sync design depends on.
