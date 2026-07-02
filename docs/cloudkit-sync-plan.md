# CloudKit Sync Design (Phase 3.5 — design only, no code until Phase 5)

**Status:** Design documented 2026-07-01. Implementation is deliberately
deferred until the SwiftUI companion app starts (Phase 5); this document
exists so nothing shipped in Phase 3 has to change shape when it does.

## Goal

Let an iOS/iPadOS companion app read the vocab/grammar store and record
flashcard reviews offline, syncing through the user's own iCloud (private
database — no server infrastructure, no third-party sync service). The
Mac backend stays the harvest/enrichment brain; the store's on-disk JSONL
format stays the source of truth on the Mac.

## Why the Phase 3 schema is already CloudKit-shaped

Decisions locked in `docs/vocab-store-plan.md` map 1:1 onto CloudKit:

| Store property | CloudKit counterpart |
|----------------|----------------------|
| Full-UUID `id` on every record | `CKRecord.ID.recordName` (stable, globally unique) |
| `updated_at` bumped on every write | last-writer-wins conflict resolution |
| Tombstones (`deleted: true`, never removed) | deletes sync as normal record saves — no dependence on CloudKit deletion semantics or push timing |
| Append-only `reviews.jsonl`, one immutable event per line | create-only records: no updates → no conflicts, unions merge trivially |
| Flat fields, no cross-file joins | flat `CKRecord` key/value fields |

## Record types

All records live in one custom zone (`StudiousZone`) in the private
database. A custom zone is required for atomic batch saves and
`CKFetchRecordZoneChangesOperation` change tokens (delta sync).

### `VocabItem` / `GrammarItem`

One record per store item; `recordName` = the item's UUID. Scalar fields
map directly (`headword`, `reading`, `meaning`, `status`, `notes`,
`pattern`, `explanation`, `jmdict_seq`, `priority_group`, `updated_at`,
`deleted`, `merged_into`, `created_at`). Structured fields that CloudKit
can't index but the app only ever reads whole — `sightings`,
`classifications`, `links`, `pos`, `surface_variants`, `kana_variants` —
are stored as JSON-encoded `String` fields. That is acceptable because:

- sightings/classifications are produced only by the Mac-side harvest and
  enrichment pipelines; the iOS app never edits them, so intra-record
  merge granularity is unnecessary;
- the iOS app edits exactly the fields a human curates on the go:
  `status` and `notes`.

A `schema_version: Int` field on every record allows forward migration.

### `ReviewEvent`

One record per review; `recordName` = the event's UUID. Fields: `item_id`
(string, not a `CKReference` — referential integrity is enforced by the
stores, and dangling events are harmless), `kind`, `card_type`, `grade`,
`ts`, `elapsed_ms`, `schema_version`. **Create-only**: never modified,
never deleted. Both sides append; sync is a set union keyed on
`recordName`. FSRS state is derived by replay on each device (the
scheduler is a pure function, so both platforms compute identical state
from identical event sets — port `services/srs.py` to Swift with the same
weights and golden-file tests).

## Conflict policy

- **Items:** last-writer-wins per record on `updated_at` (compare the
  field, not CloudKit's server modification time, so offline edits win
  correctly). Whole-record LWW is acceptable because concurrent edits to
  the *same item* from two devices within one sync window are rare for a
  single-user tool, and the JSONL log preserves every superseded version
  on the Mac for manual recovery.
- **Tombstones:** `deleted: true` wins over any concurrent field edit
  (a delete is final, matching store semantics). `merged_into` pointers
  ride along on the tombstone record.
- **Review events:** no conflicts possible (create-only, unique UUIDs).

## Sync agents

- **Mac side:** a small daemon/CLI (`studious sync`, Phase 5) tails the
  JSONL stores (latest-per-id) and pushes changed records; pulls zone
  changes and appends them to the JSONL files through the existing
  store-write path (which preserves append-only + fsync semantics). The
  JSONL files remain canonical; CloudKit is a transport, not a database.
- **iOS side:** `CKSyncEngine` (iOS 17+) with a local store; writes
  create `ReviewEvent` records and item `status`/`notes` edits only.

## Explicitly out of scope for sync

- **Documents, pages, transcriptions, breakdowns** — large binary/derived
  data; the companion app is a study app, not a transcription app. If
  sentence context beyond stored sightings is ever wanted on iOS,
  revisit as CKAsset or on-demand fetch from the Mac.
- **Reference data** (JMdict index, JLPT lists, WaniKani cache) — each
  device builds/downloads its own; WK content is personal-use licensed
  and the cache must not transit through CloudKit either.
- **LLM audit log / costs** — Mac-only operational data.

## Open questions (decide when Phase 5 starts)

1. `CKSyncEngine` minimum-OS floor vs. hand-rolled
   `CKFetchRecordZoneChangesOperation` plumbing.
2. Whether the Mac agent runs inside the FastAPI process (background
   task) or as a separate launchd job.
3. Subscription/push (silent notifications) vs. periodic pull on iOS.
