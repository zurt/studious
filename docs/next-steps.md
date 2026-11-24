# Next steps

Handoff written 2026-11-11 at the end of the cleanup session. It records
what is decided, what is still open, and where the next sessions start.
Delete items as they are done; when the file is empty, delete the file.

## Where things stand

- `main` holds everything: the former `cc/mobile-spike` work (vocab/grammar
  store, SRS, Apple apps), the security and repo cleanup, linting, E2E in CI,
  the reorganised docs, and the benchmark rework.
- CI has five required checks on `main` (`backend`, `frontend`, `e2e`,
  `apple`, `audit`), enforced by a ruleset. It also runs weekly.
- Dependabot patch/minor PRs auto-merge on green; majors wait for a person.
- Default VLM is `claude-opus-5-5`, chosen on model-eval run
  `20261111-eval-v2` (`benchmarks/model_eval/reports/2026-11-11-model-comparison.md`).

## The next three sessions

The owner's stated near-term goals, in order.

### 1. Safe development, and where Studious runs

Decided 2026-11-13. The laptop was risky because development, the real
study data and the real credentials shared one directory. The answer is to
separate them, which is also the first slice of hub infrastructure (the
hub needs a backend that is up when the laptop lid is closed).

Three planes:

- **Production**: one container on a small DigitalOcean droplet, reachable
  only over Tailscale. Real data on a volume, its own API key with a spend
  cap, encrypted backups. CI builds and deploys the image, so no deploy
  credential sits on the laptop. The owner accepts the textbook scans
  living there.
- **Development**: native on the Mac (the Apple targets need macOS anyway),
  holding nothing valuable. Mock VLM plus seed data by default; keys read
  from the Keychain only by the targets that need them; Claude Code's
  sandbox on. Unattended or permission-bypassed agent work goes to cloud
  sessions.
- **Clients** (web, Mac, iOS): all talk to the production API. Apple builds
  stay local.

Rejected: a dev container (two environments to maintain, little gained once
data and keys are out of dev) and a macOS VM (heavy). A separate macOS user
account is held in reserve; it is the only Mac-native hard boundary for
commands the owner runs outside Claude Code.

Done 2026-11-13:

- Everything under iCloud Drive's `dev/` moved to `~/dev`; the repo is
  `~/dev/cc/studious`. Time Machine covers it when the backup drive is
  plugged in.
- The keys are no longer exported from `~/.zshrc`. `make run-backend` and
  `make benchmark` read them from the Keychain for that one process;
  `make dev-backend` needs no key (see step 4).
- Claude Code's sandbox is enabled in the owner's user settings, with
  reads of `~/.ssh`, iCloud Drive and other personal folders denied and a
  network allowlist. The project allowlist no longer auto-approves
  arbitrary `uv run`, `npm run` or `npx` commands.

Still to do, in order:

1. Done 2026-11-13: the sandbox is verified. `make test`, `make lint`,
   `make test-e2e` and `make test-apple` pass, `make dev-backend` starts
   and reads the key (it has since changed: see step 4), and `git push` and `gh` work from a Claude Code
   session. Nothing needed loosening; the one catch (the exclusions apply
   only to a command run on its own) is in `docs/troubleshooting.md`.
2. Done 2026-11-13: the Keychain item `ANTHROPIC_API_KEY` now holds a
   development key (expires about 2026-12-13; rotate it then). The former
   key is kept as `ANTHROPIC_API_KEY_PROD` for the droplet. The owner
   confirmed on 2026-11-13 that the dev key's workspace has a low spend cap.
3. Done 2026-11-24: the real data left the Mac with the droplet move
   (step 6). The copy taken at the move is renamed
   `backend/data.pre-droplet-2026-11-23` (gitignored, 602 MB); **delete it
   on or after 2026-12-23** if nothing has needed it (restic in B2 has the
   same data and everything since). `backend/data` now holds only `refs/`
   (rebuildable reference data that `make dev-backend` links), so
   `make run-backend` there sees an empty library until step 9 repoints it.
4. Done 2026-11-13: mock VLM plus seed data is the dev default.
   `make dev-backend` runs `STUDIOUS_VLM_PROVIDER=mock` on a seeded
   `backend/.dev-data` (a committed sample textbook, `backend/seed/`) with
   no key, no WaniKani token and Anki pointed at a closed port;
   `make dev-reset` reseeds it; `make run-backend` is the real thing
   (Keychain keys, `backend/data`, no reload). Both take `BACKEND_PORT=`.
   The web UI shows a "Mock VLM · seed data" pill while the mock is
   active. Open: reference data (`make refs`) is linked into the dev dir
   from `backend/data/refs` only when that exists, so a fresh clone or
   cloud session has no JMdict/JLPT enrichment unless it builds the refs
   into `.dev-data`.
5. Partly done: the Dockerfile work from `5b06c4e` is brought up to date
   (`Dockerfile`, `.dockerignore`, `docker-compose.yml`, `make docker-*`,
   `STUDIOUS_STATIC_DIR` and `STUDIOUS_CORS_ORIGINS`, a `docker` CI job
   that builds the image and runs `scripts/docker-smoke.sh`, Dependabot for
   the base images). `docs/hosting.md` describes it. The image builds
   locally (818 MB) and passes the smoke test. Run against a copy of the
   real library on 2026-11-13, it peaked at 437 MiB and survived a 512 MiB
   cap, so a 1 GB droplet is enough on this evidence (limits of the
   measurement are in the hosting doc). Still open: the `docker` job is not
   a required check until the owner adds it to the ruleset.
6. Droplet, Tailscale, backups, CI deploy, data move. **Done 2026-11-23**:
   production runs on the droplet, reached over Tailscale; backups go to
   B2 daily and the first full restore test passed; the Mac's copy from
   the move is renamed (step 3). Fixes from the
   first run are in `deploy.md` and `provision.sh` (timers enabled by the
   runbook, automatic reboot at 09:00 UTC, Tailscale auto-update). Still
   open: alerting (a failed timer shows only in `systemctl --failed`).
   Built 2026-11-16: the `publish` CI job (image to `ghcr.io/zurt/studious`, `:main`
   and `:sha-<commit>`, on push to `main` only), `deploy/` (production
   compose file, env templates, pull-based update timer with a job-idle
   check and rollback, restic backup and weekly restore-test timers,
   idempotent `provision.sh` with ufw and Tailscale, `--lock-down` for
   public SSH), the `deploy` CI job (shellcheck, compose config, systemd
   verify, `scripts/deploy-selftest.sh`) and the runbook `docs/deploy.md`.
7. Move the Mac and iOS apps from direct file access to the API.
8. **Features that rely on the service running on the Mac need a new
   home** once production is on Linux: the macOS voices (TTS), Anki sync
   through AnkiConnect on localhost, and anything else that calls a local
   Mac service. Inventoried 2026-11-13 in `docs/hosting.md` ("Features
   that need the Mac"). Decided: Anki is reached on the Mac
   over Tailscale. Speech stays on the Mac's `say`
   voices: a small helper on the Mac behind the same tailnet route, a
   third engine in `tts.py`, and clips generated in the background at
   harvest with a catch-up list for when the Mac is unreachable. The
   droplet stays at 1 GB. VOICEVOX on the droplet was measured and set
   aside (2 GB, slow on one CPU); revisit if missing audio becomes a
   problem. Built: the helper (`make say-helper`), the `say_remote` engine,
   background generation at harvest with a catch-up list and
   `POST /api/tts/catch-up`, cached clips served while the engine is down,
   and the reworded messages (details in `docs/hosting.md`, "New homes").
   The `tailscale serve` routes for Anki and the helper work from the
   droplet (2026-11-23): audio plays and Anki sync works. Still to do: a
   LaunchAgent so the helper starts at login. The helper was run for real
   on the Mac over loopback: about 1.2 s a clip (`docs/hosting.md`); the
   tailnet path is untimed.
9. **Developing with real data. Planned 2026-11-24, start here next
   session.** The owner is the only user and developer and wants quick
   iteration, with restic as the safety net. Expected work: UI/study
   features, prompts and the VLM pipeline, store/data changes and the Apple
   apps. Decided with the owner:
   - **Where each kind of work runs.** UI changes: the local frontend
     against the droplet's live API (what the owner does there is real and
     kept), or the full local stack on a copy. Prompts/VLM and store
     changes: the Mac on a copy, with real model calls through the dev key
     (`ANTHROPIC_API_KEY`, low cap). Apple apps: the Mac pointed at the copy
     until step 7 moves them to the API (step 7 now gates them). Cloud
     sessions: code-only, on seed data, tests and `make shot`; the owner
     checks the result on a copy or after it is live. Troubleshooting
     production: Claude Code on the Mac, read-only over the tailnet.
   - **Not chosen:** Claude Code on the droplet (1 GB: the container may
     take 640 MiB and Claude Code needs 300–500 MB, and an agent as root
     next to the production key and B2 credentials), and a staging
     container (needs a 2 GB droplet). The droplet stays at 1 GB.
   - **A trade-off accepted for speed:** pulling a copy puts the real data
     back on the Mac, which plane 1 above set out to avoid. The copy is
     disposable and one-way (never pushed back), and the production key
     stays off the Mac.

   **PR 1, droplet side** (`deploy/`, `docs/deploy.md`; needs the owner to
   re-run `provision.sh` and check):
   - A read-only user `studious-ro`: in `systemd-journal` (reads the
     journal) and in a group that can read `/srv/studious/data` (for the
     pull below), **not** in `docker` (root-equivalent). A few root-owned
     wrapper scripts it may run through `sudo` with NOPASSWD, fixed
     arguments only: status (`systemctl --failed`, the timers, `docker ps`,
     health, `df`, `free`), the container's logs (`docker logs --tail N
     studious`, N a number checked by the script) and `docker stats
     --no-stream`. The tailnet policy's `ssh` section must allow this user
     from the owner's devices; write out the exact lines for the admin
     console. Tailscale SSH's "check" mode re-asks in a browser now and
     then, which is acceptable.
   - A backup before each rollout: when `studious-update.sh` is about to
     roll out a new image (not on a first install), run the backup first,
     tagged `pre-rollout` as well as `studious`. If it fails (B2 down),
     log a warning and roll out anyway: the night's snapshot exists, and
     the owner prefers speed. Then a bad data change is one `restic
     restore` to just before the version that caused it. Check that
     retention (`forget --keep-*`) still behaves with several snapshots a
     day, and that the self-test covers the new path.
   - The update timer every 2 minutes instead of 5 (a pull with no new
     image only fetches the manifest).
   - Docs: how to troubleshoot as `studious-ro` (`ssh
     studious-ro@<droplet-tailnet-name> sudo studious-logs 200`), and
     the restore-to-before-a-rollout recipe.

   **PR 2, Mac side:**
   - `make pull-data`: rsync from `studious-ro@<droplet>:/srv/studious/data/`
     into `backend/.prod-copy/` (gitignored), one way, `--delete`, printing
     its size and the time of the pull (keep that in a stamp file). The
     droplet's address comes from a gitignored local file (e.g.
     `.env.local`, `STUDIOUS_PROD_HOST`), never from the public repo.
   - `make run-backend` runs on `backend/.prod-copy` (Keychain dev key, no
     reload) and prints how old the copy is at start; it refuses to start
     when there is no copy and says to run `make pull-data`. `refs/` is
     in the copy, so the local `backend/data/refs` is only needed by
     `make dev-backend`; decide whether `--link-refs` should read refs
     from the copy instead, and whether `backend/data` can then go.
   - `make dev-frontend-prod`: Vite serving the local frontend with its
     API proxy pointed at `https://<droplet>.ts.net` (from the same local
     file). The UI should make it obvious, like the mock pill, that it is
     talking to production. Limit: a UI change that needs a new endpoint
     waits until that endpoint is live.
   - Point `make run-mac` (and the iOS dev setup, if it reads files) at
     the copy instead of `backend/data`; also `make logs`, which tails
     `backend/data/llm_audit.jsonl`.
   - `docs/dev-workflow.md`: which mode for which task, the commands, and
     how to troubleshoot production. Update `CLAUDE.md` (Development
     Commands), the README and `troubleshooting.md`.

   **Also:**
   - CI speed: on the 2026-11-24 merge the `e2e` job took 6 of the 7
     minutes (other jobs under 1 minute; earlier whole runs took 1–2).
     Find out why before considering letting `publish` skip waiting
     for it.
   - Claude Code's sandbox blocks `ssh` (it cannot read `~/.ssh`). The
     owner chose to approve each `ssh studious-ro@...` run outside the
     sandbox rather than exclude it.

### 2. Letting Claude Code sessions see the UI

Goal: agent visibility for UI/UX work (web first, spot checks are enough to
start), and solid test coverage during a period of rapid change, at low
cost. Then: how this works in a cloud session, which has neither the local
files nor the API key.

What already exists:

- A Playwright suite (`frontend/e2e/smoke.spec.ts`, 15 journeys) that boots
  an isolated backend with the **mock VLM provider**
  (`STUDIOUS_VLM_PROVIDER=mock`) and a fresh data dir on dedicated ports. It needs no API key and no local data, runs in CI, and
  runs inside a cloud session on the pre-installed Chromium
  (`STUDIOUS_CHROMIUM_PATH=/opt/pw-browsers/chromium make test-e2e`).
- So a cloud session can already start the real stack and take screenshots.
  What it sees is mock data: the E2E fixtures, not real textbook pages.

Gaps to design for:

- Seed data now exists (done 2026-11-13): `backend/seed/` holds an invented
  five-page N4 textbook as a manifest plus an image-only PDF, and
  `make dev-backend` seeds it. Still thin: one reading passage and one
  dialogue, no vertical text, no tables, no handwritten or scanned-looking
  pages. Grow it as UI work needs more shapes.
- Done 2026-11-14: `make shot` takes PNGs of named views or any path, with
  click/press/fill steps, on a freshly seeded mock stack
  (`docs/screenshots.md`). Verified in a cloud session.
- No visual regression checks (Playwright's screenshot assertions).
- No frontend linting of accessibility or layout.
- No narrow layout: `make shot SHOT="reading --mobile"` shows the chapter
  view overflowing sideways at 390 px. Matters only if the web UI is meant
  to be used on a phone.
- `frontend/src/pages/chapter-view.ts` is still one 1,200-line closure and
  is the file most UI work will touch.

### 3. The Studious Language Hub

The owner has written up the problems to be solved; start from that
document. Context gathered so far:

- **The idea:** the Mac and iOS apps become the student's central hub,
  collecting vocab, grammar, references to textbooks and other learning
  material, quotes and notes. Reading books is one of the goals.
- **Single user.** Designed for the owner alone.
- **What the Apple code is today:** about 3,400 lines of Swift covering
  vocab, grammar and flashcard review only. It compiles and its tests pass
  in CI on macOS; it has never been run on a device.
- **What stands between that and a hub:**
  - No first-class sources, quotes or notes in the data model. Items carry
    a notes field; nothing links an item to "第14課, p. 47" or holds a saved
    passage.
  - Sync is file-level. The Mac app reads the backend's JSONL files
    directly; iOS uses CloudKit or manual export/import. That cannot carry
    page images, transcriptions or breakdowns.
  - Two flashcard schedulers (Python and Swift) kept identical by generated
    fixtures. Only worth carrying if offline review matters.
  - The API has no authentication.
- **Digital-text books.** There is no path for PDFs that already contain
  text (a novel was uploaded: 魔女の宅急便). Every page is rendered and sent
  to the model, which is slow, costs money and can corrupt exact text.
  Extraction is easy; the hard parts are furigana (separate small text
  runs that must be reattached to the right word), vertical text reading
  order, and mixed books that need a per-page choice with the model as
  fallback. A book is also a different shape from a textbook: continuous
  text with chapters, not regions on a page.
- **Hosting is part of this discussion.** Undecided between leaving the
  backend on the Mac and reaching it over Tailscale (zero cost, works when
  the Mac is on) and a small server. Known constraints:
  - Do not expose the app publicly; a private network avoids building a
    login system.
  - The owner's website runs on DigitalOcean App Platform's smallest
    container (512 MB). That cannot host Studious (too little memory, and
    the app needs files that persist). A server means a new droplet; the
    earlier estimate was 2 GB RAM; measured 2026-11-13, 1 GB is enough
    (`docs/hosting.md`, "Memory").
  - The website is static and rarely updated. Keep it off any Studious
    server. Reworking it into a CV/portfolio site with occasional posts and
    photos is a separate project.
  - Moving the data off the Mac breaks the Mac app's direct file access and
    means setting up backups.
  - The Dockerfile and hosting guide from branch
    `claude/mobile-spike-audit-hosting-9jjv6k` were rewritten for today's
    tree (`docs/hosting.md`); that branch can be deleted.

## Open items, smaller

Benchmarks:

- **Benchmarks for breakdowns, exercise completions and grammar guides do
  not exist.** The model setting drives every job type except the region
  check, which runs on the separate helper model (default
  `claude-haiku-5-5`); the Opus 5.5 switch is evaluated for transcription
  only. See the roadmap entry.
- **The region check prompt has no benchmark or fixtures yet.** A one-off
  dry run on real regions looked good (numbers in the roadmap, Phase 2.6),
  but nothing repeatable measures its label and reading-reference answers.
  Build a handful of deliberately mislabeled regions (a vocab list tagged
  as reading, an exercise with and without its own passage, a grammar
  explanation tagged as exercises) and score the tag/`needs_reference`
  output, ideally per helper model.
- **Sonnet 5.5 prompt fix** is worth testing only if volume makes the cost
  gap matter. See the roadmap entry.
- **`benchmarks/model_eval/dataset/v2` exists only on the owner's Mac.** It
  is gitignored because it contains textbook crops. Losing `v1` is why
  July's results cannot be compared item by item; keep `v2`.
- The regression fixture set is thin: seven image fixtures, five of them
  vocab lists from one book. A vertical reading passage was added
  2026-11-13 (`reading-vertical-shiroi-kami`); its reference still wants a
  character-level pass by a person. Add an exercise, a grammar section and
  a workbook scan, each with a reference checked against the page by a
  person.
- Run transcriptions are not committed (public repo). They are in the run
  folder on the owner's Mac.

Dependencies:

- The `anthropic` SDK is on 2.x (verified with `make benchmark` before and
  after, no regression). `beta.messages.create` now has a typed `fallbacks`
  argument, so the `extra_body` workaround in the provider and the eval's
  judge call can be simplified. A future major SDK bump needs the same
  check: the tests use a mock provider and will not catch a real API break.

Transcription provider (`backend/app/providers/vlm/anthropic.py`), two items
found 2026-11-13 when a guest Wi-Fi network cut idle connections at 30
seconds (see the `APIConnectionError` entry in `docs/troubleshooting.md`).
The second, logging the underlying network error, is done (2026-11-14:
`error` and `error_cause` on `vlm_call_error` / `vlm_tool_call_error`; log
fields only, so no benchmark run). The first touches provider logic, so run
`make benchmark` before and after:

- **Stream the transcription call**, as the breakdown path already does.
  It is one non-streaming request today, and the model can think for
  longer than a network's idle cut-off before sending its first byte.

Small checks:

- Branch `claude/phase-1.6-improve-tests-ZBE7o` can be deleted (owner:
  cloud sessions cannot). Reviewed 2026-11-14: its nine commits from May
  (copy buttons, text size toggle, region auto-select, hover fade, cost
  API, settings modal, logging tests) are all on `main` already, in later
  form; it shares no history with `main` since the rewrite, and none of its
  test names is missing from `main`.
- Before any network exposure, the one remaining deferred finding in
  `docs/archive/audit-2026-07-mobile-spike.md` applies: authentication (the
  plan is Tailscale only, no login). Upload limits and reconnect on the job
  progress stream, the read-modify-write races (one re-entrant lock in
  `storage.py`, unique temp files) and blocking harvest work (moved to
  threads) were all done 2026-11-14 (`docs/hosting.md`).

## Working notes for future sessions

- Cloud sessions cannot delete remote branches (the push is refused) and
  cannot read or change repository settings. Those are done by the owner.
- Anything that needs the API key or `backend/data/` runs on the owner's
  Mac: `make benchmark`, the model eval, real-data spot checks.
- Work lands through pull requests. "Rebase and merge" is unavailable when
  a branch contains merge commits; use "Create a merge commit".
