# Studious for iOS/iPadOS

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
