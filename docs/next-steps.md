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
3. `backend/data/` still lives inside the repo. The dev server no longer
   runs against it (step 4); `make run-backend` does, without `--reload`.
   It leaves the repo when production moves to the droplet; until then the
   real data and the real key are one command away, so run that target
   deliberately.
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
5. Salvage the Dockerfile commit (`5b06c4e`) from
   `claude/mobile-spike-audit-hosting-9jjv6k`, build the image in CI, run
   it locally against the real data and measure memory (the 2 GB droplet
   estimate is unmeasured).
6. Droplet, Tailscale, backups, CI deploy, data move.
7. Move the Mac and iOS apps from direct file access to the API.
8. **Features that rely on the service running on the Mac need a new
   home** once production is on Linux: the macOS voices (TTS), Anki sync
   through AnkiConnect on localhost, and anything else that calls a local
   Mac service. Inventory them before step 6. Likely shapes: a small
   Mac-side helper the server or client calls, or moving the feature into
   the Mac app.

### 2. Letting Claude Code sessions see the UI

Goal: agent visibility for UI/UX work (web first, spot checks are enough to
start), and solid test coverage during a period of rapid change, at low
cost. Then: how this works in a cloud session, which has neither the local
files nor the API key.

What already exists:

- A Playwright suite (`frontend/e2e/smoke.spec.ts`, 14 journeys) that boots
  an isolated backend with the **mock VLM provider**
  (`STUDIOUS_VLM_PROVIDER=mock`) and a fresh data dir on dedicated ports. It needs no API key and no local data, runs in CI, and
  was run inside a cloud session during this cleanup using the
  pre-installed Chromium (`docs/troubleshooting.md` describes the
  local-only config override needed for a pre-installed browser).
- So a cloud session can already start the real stack and take screenshots.
  What it sees is mock data: the E2E fixtures, not real textbook pages.

Gaps to design for:

- Seed data now exists (done 2026-11-13): `backend/seed/` holds an invented
  five-page N4 textbook as a manifest plus an image-only PDF, and
  `make dev-backend` seeds it. Still thin: one reading passage and one
  dialogue, no vertical text, no tables, no handwritten or scanned-looking
  pages. Grow it as UI work needs more shapes.
- No screenshot helper or `make` target for "show me page X in state Y".
- No visual regression checks (Playwright's screenshot assertions).
- No frontend linting of accessibility or layout.
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
    earlier estimate was 2 GB RAM, unmeasured.
  - The website is static and rarely updated. Keep it off any Studious
    server. Reworking it into a CV/portfolio site with occasional posts and
    photos is a separate project.
  - Moving the data off the Mac breaks the Mac app's direct file access and
    means setting up backups.
  - An unlanded Dockerfile and hosting guide sit on branch
    `claude/mobile-spike-audit-hosting-9jjv6k`. The Docker image has never
    been built.

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

Transcription provider (`backend/app/providers/vlm/anthropic.py`), both
found 2026-11-13 when a guest Wi-Fi network cut idle connections at 30
seconds (see the `APIConnectionError` entry in `docs/troubleshooting.md`).
Both touch provider logic, so run `make benchmark` before and after:

- **Stream the transcription call**, as the breakdown path already does.
  It is one non-streaming request today, and the model can think for
  longer than a network's idle cut-off before sending its first byte.
- **Log the underlying network error** in the `vlm_call_error` handlers.
  They record only the exception class, so the wrapped cause (reset,
  protocol error, DNS) is not in the log.

Small checks:

- Branch `claude/phase-1.6-improve-tests-ZBE7o` has nine commits from May
  that were never checked against `main`. Review, then delete or salvage.
- Before any network exposure, the deferred findings in
  `docs/archive/audit-2026-07-mobile-spike.md` apply: authentication,
  upload size limits, reconnect on the job progress stream.

## Working notes for future sessions

- Cloud sessions cannot delete remote branches (the push is refused) and
  cannot read or change repository settings. Those are done by the owner.
- Anything that needs the API key or `backend/data/` runs on the owner's
  Mac: `make benchmark`, the model eval, real-data spot checks.
- Work lands through pull requests. "Rebase and merge" is unavailable when
  a branch contains merge commits; use "Create a merge commit".
