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

### 1. Safe local development with Claude Code on a personal Mac

Today: Claude Code runs in Terminal against a checkout inside **iCloud
Drive** (`~/Library/Mobile Documents/com~apple~CloudDocs/dev/cc/studious`).
The concern is side effects and exploits during development; the first
instinct is to containerize.

Facts that bear on the decision:

- The checkout being in iCloud Drive is a problem independent of isolation:
  `.git`, `node_modules`, `.venv` and `backend/data/` are all being synced,
  and anything written there replicates to every device on the account.
- `backend/data/` holds the real study data: copyrighted textbook scans,
  the vocab/grammar store, review history, and `preferences.json`. It is
  the thing most worth protecting and backing up.
- The Anthropic key lives in the macOS Keychain and is exported from the
  shell rc file (README "Quick start"); the benchmark tools fall back to a
  Keychain lookup. A container would need the key passed in deliberately.
- The Apple targets (`make test-apple`, `make run-mac`) need macOS and
  cannot run in a Linux container. Everything else can.
- Supply-chain posture already in place: 7-day package cooldown, frozen
  lockfiles, audits in CI.
- Cloud sessions (this one was one) are already isolated from the Mac, but
  have no access to `backend/data/` or the API key.

To decide: container (dev container / Docker) vs. Claude Code's own
sandboxing and permission settings vs. a separate macOS user account; where
the repo and the data directory should live; how the key reaches the dev
environment; what stays Mac-native.

### 2. Letting Claude Code sessions see the UI

Goal: agent visibility for UI/UX work (web first, spot checks are enough to
start), and solid test coverage during a period of rapid change, at low
cost. Then: how this works in a cloud session, which has neither the local
files nor the API key.

What already exists:

- A Playwright suite (`frontend/e2e/smoke.spec.ts`, 13 journeys) that boots
  an isolated backend with a **mock VLM provider** and a fresh data dir on
  dedicated ports. It needs no API key and no local data, runs in CI, and
  was run inside a cloud session during this cleanup using the
  pre-installed Chromium (`docs/troubleshooting.md` describes the
  local-only config override needed for a pre-installed browser).
- So a cloud session can already start the real stack and take screenshots.
  What it sees is mock data: the E2E fixtures, not real textbook pages.

Gaps to design for:

- No committed, realistic seed data. Real pages are copyrighted and stay
  out of the repo, so screens in a cloud session look sparse.
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
  not exist.** The model setting drives every job type; the Opus 5.5 switch
  is evaluated for transcription only. See the roadmap entry.
- **Sonnet 5.5 prompt fix** is worth testing only if volume makes the cost
  gap matter. See the roadmap entry.
- **`benchmarks/model_eval/dataset/v2` exists only on the owner's Mac.** It
  is gitignored because it contains textbook crops. Losing `v1` is why
  July's results cannot be compared item by item; keep `v2`.
- The regression fixture set is thin: six image fixtures, five of them
  vocab lists from one book, all scoring 10/10. Add an exercise, a grammar
  section, a reading passage and a workbook scan, each with a reference
  checked against the page by a person.
- Run transcriptions are not committed (public repo). They are in the run
  folder on the owner's Mac.

Dependencies:

- **Do not merge the `anthropic` 2.x Dependabot PR on green CI alone.** The
  tests use a mock provider and will not catch a real API break. Verify
  with `make benchmark` on the branch first. The eval's judge call also
  relies on `extra_body` for `fallbacks` because SDK 0.96 has no typed
  argument; a newer SDK may let that be simplified.
- Confirm Dependabot auto-merge has worked end to end on at least one
  patch/minor PR since it was enabled.
- The vitest 5 and GitHub Actions bump PRs need a manual look.
- CI uses Node 22, whose npm silently ignores `min-release-age`. Installs
  are protected by the lockfile, but the cooldown is not enforced there;
  moving CI to Node 24 fixes it.

Small checks:

- If a model was ever saved in Settings, `backend/data/preferences.json`
  overrides the new default. Clear it in Settings to pick up Opus 5.5.
- The app prices Sonnet 5.5 cache reads at $0.20 per million tokens;
  Anthropic's current figure appears to be $0.10. Check the pricing page
  and correct `MODEL_PRICING` in `backend/app/config.py`.
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
