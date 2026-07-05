# Study-routine shakedown

A short walkthrough to exercise everything shipped since the vocab/
grammar store (Phases 3–5) through real use, in the order a normal
study session would hit it. Each step says what to look for; if
something's off, `docs/troubleshooting.md` is organized by symptom.

## 0. Start the apps

```bash
make dev-backend    # :8000
make dev-frontend   # :5173
```

Note: `backend/data/store/` doesn't exist until the first harvest —
empty dashboards before step 1 are expected, not a bug.

## 1. Populate the store from what you already have

On the vocab dashboard (`/vocab`), run the **backfill** — it replays
every existing breakdown and vocab-list transcription into the store,
idempotently. This is the fastest way to get months of past material
in. Look for: inbox (unreviewed) filling up, each item carrying
sightings that link back to the chapter it came from.

Then harvest something *new*: transcribe a `vocab_list` region in a
current chapter, and generate a sentence breakdown on a reading
passage. Both should append to the store automatically (vocab from
both; grammar patterns from the breakdown).

## 2. Curate the inbox

Still on `/vocab` (and `/grammar`):

- Work the inbox: bulk-accept the words you're actually studying,
  ignore the noise. Statuses: unreviewed → active / known / ignored —
  **only `active` items enter the study queue**, so this step gates
  everything after it.
- Spot-check enrichment: JLPT/common badges, a homograph's meaning
  (right reading picked?), the WaniKani drill-down on a row if your
  token is set up.
- Try a merge: select two spellings of the same word, merge, confirm
  the survivor keeps its sightings and the old spelling still finds it
  in search.
- Edit one meaning by hand — it should survive a later
  `POST /api/store/enrich` untouched (`meaning_source: "user"`).
- Back in a chapter with breakdowns: known words should render dimmed,
  and the "Vocab N/M known" chip should move as you toggle statuses
  from the word popover.

## 3. Study on the web

`/study` (topbar link): run a session. Space/enter to reveal, 1–4 to
grade. Look for: due-then-new ordering, new words arriving in priority
order, "Again" cards coming back at the end of the session, sensible
predicted intervals on the grade buttons. Reviews append to
`backend/data/store/reviews.jsonl` — the log is the source of truth.

## 4. Same store, native: the Mac app

```bash
make run-mac
```

Bridge mode against the same `backend/data` store. Try:

- Vocabulary/Grammar tabs show the same items and statuses as the web
  dashboards; search and status filters work.
- Run a study session here. Grades recorded in the Mac app must be
  visible to the web `/study` queue (same review log) — a card graded
  Easy on the Mac shouldn't come due on the web.
- Edit a status or note in the Mac app → it appears in the web
  dashboard on refresh. Change one in the web app → the Mac app's list
  picks it up within a couple of seconds (the poll).
- Settings tab: the Data directory row should show `backend/data/store`,
  the Backend row "Running" while uvicorn is up. No iCloud section on
  the Mac — intentional.

## 5. iOS (when you're at an Xcode machine)

The app itself needs Xcode 16 + a developer team to install
(`apple/README.md`, "Building the app"). Until then you can still
exercise the transfer path from this Mac:

```bash
cd apple/StudiousKit
swift run studious-sync status                  # store counts
swift run studious-sync export --out /tmp/sx    # the files the phone would import
```

On the phone (once installed): Settings → Import store files, study
offline, export back, and `studious-sync merge --from <dir>` on the
Mac — statuses/notes should LWW-merge and reviews union.

## What "passed" looks like

One store, three surfaces: a word harvested from a textbook page shows
up enriched in the web dashboard, gets activated once, and is then
studyable from the web, the Mac app, and (eventually) the phone — with
a single shared review history and no manual export in daily use.
