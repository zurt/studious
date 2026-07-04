# iOS Companion App (Phase 5 — vocabulary & grammar study)

**Status:** In progress 2026-07-02. Implements the sync design in
`docs/cloudkit-sync-plan.md`.

## Goal

A native iOS/iPadOS app for studying the vocab and grammar harvested on
the Mac: browse and curate items (edit `status`/`notes` only), and run
FSRS flashcard sessions offline. It syncs with the desktop app through
the user's own iCloud private database per the Phase 3.5 design — the
Mac's JSONL store stays canonical; CloudKit is a transport.

## What ships where

```
apple/
  StudiousKit/            SwiftPM package — all logic and UI, testable with
    Sources/                `swift build` / `swift test` (CLT-only, no Xcode)
      StudiousCore/       models, JSONL store, FSRS-4.5 port, study queue
      StudiousSync/       CKRecord mapping, LWW conflict logic, CKSyncEngine
      StudiousUI/         SwiftUI views (cross-platform: iOS app + macOS compile check)
      studious-sync/      Mac-side sync CLI (executable target, macOS only)
    Tests/StudiousCoreTests/   golden-file FSRS parity + store/queue/sync-logic tests
  Studious.xcodeproj      minimal app shell (Xcode 16 synchronized folders)
  Studious/               @main app entry, entitlements
  project.yml             XcodeGen spec (regenerate the project if pbxproj drifts)
backend/scripts/generate_fsrs_golden.py   regenerates the Swift test fixtures
```

The package holds everything so the full logic surface builds and tests
on a Mac with only Command Line Tools. The Xcode project is a thin shell:
one `@main` file, entitlements, and a dependency on the local package.

## Data layer (device)

The device keeps the same store format as the Mac: append-only JSONL
(`vocab.jsonl`, `grammar.jsonl`, `reviews.jsonl`) in Application Support,
latest-line-per-id wins, deletes are tombstones, writes are
append+fsync. Items are held as raw JSON objects with typed accessors —
**never re-serialized through a typed struct** — so fields the app
doesn't know (e.g. `enriched_at`, future additions) survive the
round-trip through an iOS edit untouched. The app edits exactly
`status`, `notes`, and `updated_at`, matching the sync design.

## FSRS parity

`StudiousCore/FSRS.swift` is a line-for-line port of
`backend/app/services/srs.py` (FSRS-4.5, same 17 weights, desired
retention 0.9, 10-minute same-day relearn, 3650-day cap). Gotcha ported
deliberately: Python `round()` is round-half-to-even, so the Swift
interval computation uses `.rounded(.toNearestOrEven)`.

Parity is enforced by golden files: `generate_fsrs_golden.py` replays
deterministic review sequences (seeded random walks + edge cases)
through the Python scheduler and dumps per-step expected state; the
Swift test suite replays the same sequences and must match (stability/
difficulty to 1e-9 relative, `due` to 1ms, `interval_days` exactly). A
second fixture snapshots `build_queue` output over a synthetic store so
queue ordering (due-then-new, priority tuples, created_at ordering)
matches too.

## Sync

As designed in `docs/cloudkit-sync-plan.md`: one custom `StudiousZone`
in the private DB; `VocabItem`/`GrammarItem` records LWW on the
`updated_at` field with tombstones winning; `ReviewEvent` records
create-only, union-merged. FSRS state never syncs.

**One refinement to the record mapping:** item records carry the full
raw store record as a single `payload` JSON string field, plus a few
duplicated scalar fields (`headword`, `reading`, `pattern`, `status`,
`updated_at`, `deleted`) for CloudKit-dashboard queryability. The
receiver reads only `payload`. The design doc's field-by-field mapping
listed the known fields; mapping generically through `payload`
guarantees fields the design didn't enumerate (`meaning_source`,
`enriched_at`, `pattern_normalized`, …) and future fields survive
transport without mapper churn. `schema_version: 1` on every record.

- **iOS:** `CKSyncEngine` (iOS 17+) wired to the local JSONL store;
  runtime-gated on iCloud account availability, app is fully functional
  without it.
- **Mac:** `studious-sync` CLI (same package). `sync` pushes
  latest-per-id records whose `updated_at` moved since the last run and
  pulls zone changes back through append+fsync writes (the backend's
  mtime+size caches pick changes up automatically). Requires a
  developer-signed binary with the iCloud entitlement — documented in
  the CLI help.

**Manual sync fallback (works with zero Apple developer setup):** the
iOS app can import the Mac's JSONL files via the Files app (the data
dir is typically in iCloud Drive already) and export its own store via
share sheet; `studious-sync merge --from <dir>` LWW-merges items and
unions review events back into the Mac store. Same conflict semantics
as CloudKit, human-triggered.

## App UI (SwiftUI, iOS 17+)

Four tabs:

- **Study** — FSRS session against the local queue: `word` cards
  (headword → reading/meaning), `context` cards (sighting sentence with
  inline readings stripped → revealed with readings + meaning),
  `pattern` cards (grammar pattern → explanation). Four grade buttons
  showing predicted intervals; due/new counts.
- **Vocabulary** — search + status filter, JLPT/priority badges; detail
  view shows all enrichment read-only, edits limited to status + notes.
- **Grammar** — same for patterns.
- **Settings** — iCloud sync status, JSONL import/export, store stats.

## Explicitly out of scope (matches sync plan)

Documents/transcriptions/breakdowns, chapter grammar guides, reference
data (JMdict/JLPT/WaniKani — licensed/heavy; enrichment stays Mac-side),
LLM audit/costs.

## What still needs a machine with Xcode + an Apple Developer account

This machine has only Command Line Tools, so shipped here: the full
package (built + tested on macOS), the app shell, and the CLI. To run on
a device/simulator: open `apple/Studious.xcodeproj` in Xcode 16+, set
your team (Signing & Capabilities), and build — the iCloud/CloudKit
capability is pre-declared in the entitlements. First launch on device
creates the schema in your private database automatically in the
development environment; deploy the schema to production from the
CloudKit dashboard when done.
