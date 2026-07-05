# Studious for iOS/iPadOS

(See "Studious for macOS" below for the native Mac companion, which also
lives in this package.)

Native study companion for the vocab/grammar harvested by the Mac app:
browse and curate items (status + notes), run FSRS flashcard sessions
offline, and sync through your own iCloud private database. Design:
`docs/ios-app-plan.md`; sync protocol: `docs/cloudkit-sync-plan.md`.

## What's here

- `StudiousKit/` — SwiftPM package with everything that matters:
  - `StudiousCore` — models, append-only JSONL store (identical format
    to the backend's `data/store/`), FSRS-4.5 scheduler (golden-file
    parity with `backend/app/services/srs.py`), study queue.
  - `StudiousSync` — CloudKit record mapping + `CKSyncEngine` adapter.
  - `StudiousUI` — the SwiftUI app (Study / Vocabulary / Grammar /
    Settings).
  - `studious-sync` — Mac-side sync CLI.
  - `studious-mac` — the native Mac companion app; see "Studious for
    macOS" below.
  - `studious-tests` — the test suite (`swift run studious-tests` or
    `make test-apple` from the repo root; plain executable because
    Command Line Tools ship no XCTest).
- `Studious/` + `Studious.xcodeproj` — thin app shell (entry point,
  entitlements). `project.yml` is an XcodeGen fallback spec if the
  hand-written project ever fights Xcode: `xcodegen generate`.

## Building the app (needs Xcode 16+)

1. Open `apple/Studious.xcodeproj`.
2. Signing & Capabilities → select your team, and change
   `PRODUCT_BUNDLE_IDENTIFIER` (`com.example.Studious`) to something in
   your namespace. The iCloud container follows automatically
   (`iCloud.$(CFBundleIdentifier)`).
3. Run on a device or simulator signed into iCloud. First launch
   auto-creates the CloudKit schema in the development environment;
   deploy it to production from the CloudKit Console when ready.

Everything except the app shell builds and tests without Xcode:
`cd StudiousKit && swift build && swift run studious-tests`.

## Getting your data onto the phone

**Zero-setup path (works today):** in the app, Settings → *Import store
files…* and pick the Mac's `vocab.jsonl` / `grammar.jsonl` /
`reviews.jsonl` (if the repo lives in iCloud Drive they're already in
the Files app; otherwise AirDrop them, or run
`studious-sync export --out <dir>`). Re-importing is idempotent.
To get phone-side reviews/edits back: Settings → *Export store files*,
share to the Mac, then:

```bash
cd apple/StudiousKit
swift run studious-sync merge --from <exported-dir> --data-dir ../../backend/data
```

Items merge last-writer-wins on `updated_at` (tombstones win); review
events union by id. The backend picks the appended lines up
automatically — no restart needed.

**CloudKit path (continuous):** enable *Sync with iCloud* in the app's
Settings. On the Mac, run the same engine via the CLI:

```bash
swift run studious-sync sync --container iCloud.<your-bundle-id> --data-dir ../../backend/data
```

Caveat: a CLI binary only gets CloudKit access when codesigned with an
iCloud entitlement under your developer team (build it as a small
launchd agent or run it from an Xcode-managed scheme). Until you've set
that up, use the manual path above — it exercises exactly the same
merge semantics.

## Keeping the FSRS ports in lockstep

The scheduler exists twice (Python + Swift) by design — the sync plan
derives SRS state on each device by replaying the shared review log.
Parity is enforced by generated fixtures:

```bash
make golden       # regenerate fixtures from the Python scheduler
make test-apple   # Swift suite must still pass bit-identically
```

Run both after touching `backend/app/services/srs.py` or
`StudiousKit/Sources/StudiousCore/FSRS.swift`, and commit the fixture
changes.

# Studious for macOS

Native Mac companion with the same Study/Vocabulary/Grammar/Settings UI
as the iOS app, plus a role the phone can't play: it reads and writes the
backend's own `data/store/*.jsonl` files directly, so edits made in the
Mac app, the web app, and the backend all show up in each other with no
sync layer, no HTTP, and no Apple developer account. Design:
`docs/mac-app-plan.md`.

It's a plain SwiftPM executable (`studious-mac`), not a signed `.app`
bundle — the Command-Line-Tools-only build in this repo has no way to
codesign one. That's why the two modes below matter, and why CloudKit is
out of reach here (see below).

## Running it

```bash
make run-mac
```

This points the app at the repo's real `backend/data` via
`STUDIOUS_DATA_DIR`, so by default you get **bridge mode**: the app is a
second reader/writer of the canonical store the backend and frontend use.
Edit an item's status or notes, or run a study session, and the change is
visible in the web app immediately (a ~2s foreground poll picks up
appends made by the backend too — see "External-change refresh" in the
plan doc). Run it without `STUDIOUS_DATA_DIR` (or clear the data
directory in Settings) to fall back to **standalone mode**: the same
Application-Support-backed store the iOS app uses when unpaired.

Settings → *Data directory* shows the resolved store path and lets you
point at a different `data/` folder (`fileImporter`, persisted to
UserDefaults, effective on relaunch). Settings → *Backend* is purely
informational — a health check against `GET /api/health` and a link to
the web app — the Mac app never depends on the backend running.

## Import replaces `studious-sync merge` for the common case

Settings → *Import store files…* on the Mac app runs the exact same
LWW/union merge code (`AppModel.importJSONL`) as `studious-sync merge`,
so pulling an iOS export into the canonical store no longer requires the
terminal: export from the iPhone (AirDrop or Files), then import them
here. The CLI still exists for scripting/automation.

## No CloudKit here (yet)

Settings hides the iCloud sync section on macOS (`AppModel.syncSupported
== false`): an unsigned process has no iCloud entitlement, and touching
`CKContainer` would throw. In bridge mode this doesn't matter — the Mac
app *is* the canonical store, so it has nothing to sync. `studious-sync
sync` remains the CloudKit path until a signed `.app` bundle exists (see
"Later, on a machine with Xcode" in `docs/mac-app-plan.md`).
